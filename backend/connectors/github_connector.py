"""GitHub 저장소의 Issue/PR(본문+댓글)과 저장소 자체(설명+README)를 읽어와
Topic Thread AI의 공통 문서 포맷(dict)으로 변환한다. 쓰기 작업은 하지 않는다.
위키는 Out of scope (PRD.md FR-6 참고).

저장소 문서(설명+README)를 따로 만드는 이유: fox-devil처럼 막 만들었거나 Issue/PR
없이 코드만 있는 개인 프로젝트는, Issue/PR만 색인하면 검색 결과에 영원히 안 잡힌다
(계정 연동으로 저장소 자체는 정상 탐색됐는데도). 저장소당 최대 1개 문서로 항상 만든다.

사전 준비 (사용자가 GitHub에서 직접 해야 하는 것):
1. https://github.com/settings/tokens 에서 Personal Access Token 발급
   (fine-grained token이면 대상 저장소에 Issues: Read-only 권한만 부여)
2. backend/.env 의 GITHUB_TOKEN 에 토큰 입력
3. backend/.env 의 GITHUB_REPOS 에 대상 저장소를 "owner/repo,owner/repo2" 형태로 입력
   (Notion의 "페이지 공유"처럼, 여기 명시한 저장소만 읽는다)
"""

import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_API_BASE = "https://api.github.com"
GITHUB_LOOKBACK_DAYS = 90


def _headers(token: Optional[str] = None) -> dict:
    """token을 명시하면 그 토큰(계정 연동으로 받은 사용자 본인 access token)을 쓰고,
    없으면 관리자가 .env에 미리 넣어둔 정적 GITHUB_TOKEN을 쓴다."""
    token = token or os.getenv("GITHUB_TOKEN")
    if not token or token == "your_github_token_here":
        raise RuntimeError(
            "GITHUB_TOKEN이 설정되지 않았습니다. backend/.env 에 GitHub Personal Access Token을 입력하세요."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_target_repos() -> list[str]:
    raw = os.getenv("GITHUB_REPOS", "")
    repos = [r.strip() for r in raw.split(",") if r.strip()]
    if not repos:
        raise RuntimeError(
            "GITHUB_REPOS가 설정되지 않았습니다. backend/.env 에 'owner/repo,owner/repo2' 형태로 대상 저장소를 입력하세요."
        )
    return repos


def _request(method: str, path: str, headers: dict, **kwargs) -> requests.Response:
    """GitHub API 요청 공통 래퍼. rate limit이면 X-RateLimit-Reset까지 기다렸다 재시도."""
    url = f"{GITHUB_API_BASE}{path}" if path.startswith("/") else path
    for attempt in range(3):
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            reset_at = int(resp.headers.get("X-RateLimit-Reset", time.time() + 5))
            wait = max(reset_at - time.time(), 1)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp


def _paginate(path: str, params: dict, headers: dict) -> list[dict]:
    """GitHub의 Link 헤더 기반 페이지네이션을 따라간다."""
    results = []
    url: Optional[str] = f"{GITHUB_API_BASE}{path}"
    query = dict(params)
    while url:
        resp = _request("GET", url, headers, params=query)
        results.extend(resp.json())
        query = {}  # next 링크에 파라미터가 이미 포함돼 있음
        url = resp.links.get("next", {}).get("url")
    return results


def _list_user_repos(headers: dict) -> list[str]:
    """이 토큰 소유자 본인이 접근 가능한 저장소 전체(소유+협업+소속 조직)를 나열한다.
    .env의 GITHUB_REPOS처럼 관리자가 미리 정해둔 고정 목록이 아니라, 계정 연동 시점에
    그 사람이 실제로 볼 수 있는 저장소를 자동으로 대상으로 삼기 위함."""
    repos = _paginate(
        "/user/repos",
        {"per_page": 100, "affiliation": "owner,collaborator,organization_member", "sort": "updated"},
        headers,
    )
    return [r["full_name"] for r in repos if not r.get("archived")]


def _list_recent_issues(owner: str, repo: str, since_iso: str, headers: dict) -> list[dict]:
    """Issue와 PR을 함께 반환한다 (GitHub API 특성). pull_request 키 유무로 구분 가능."""
    return _paginate(
        f"/repos/{owner}/{repo}/issues",
        {"state": "all", "since": since_iso, "per_page": 100, "sort": "updated"},
        headers,
    )


def _list_comments(owner: str, repo: str, issue_number: int, since_iso: str, headers: dict) -> list[dict]:
    comments = _paginate(
        f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
        {"since": since_iso, "per_page": 100},
        headers,
    )
    return [c for c in comments if (c.get("user") or {}).get("type") != "Bot"]


def _format_entry(author: str, iso_time: str, text: str) -> str:
    ts = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
    return f"**{author}** ({ts.strftime('%Y-%m-%d %H:%M')}): {text}"


def _issue_to_document(owner: str, repo: str, issue: dict, comments: list[dict]) -> dict:
    is_pr = "pull_request" in issue
    author = (issue.get("user") or {}).get("login", "알 수 없음")
    # 생성 시점이 아니라 마지막 활동 시점(updated_at)을 문서 날짜로 써야 "최근" 판정이 맞다 —
    # 오래전에 만든 Issue/PR이라도 최근에 댓글이 달렸으면 여전히 최신 논의로 취급해야 함
    date = (issue.get("updated_at") or issue.get("created_at") or "")[:10] or "1970-01-01"
    kind = "PR" if is_pr else "Issue"
    title = f"{owner}/{repo}#{issue['number']} — {issue.get('title', '제목 없음')}"

    lines = [_format_entry(author, issue["created_at"], issue.get("body") or "(본문 없음)")]
    for c in comments:
        c_author = (c.get("user") or {}).get("login", "알 수 없음")
        lines.append(_format_entry(c_author, c["created_at"], c.get("body") or ""))

    return {
        "id": issue_document_id(owner, repo, issue["number"]),
        "title": title,
        "source": "github",
        "author": author,
        "authorAvatar": author[:2],
        "date": date,
        "content": "\n\n".join(lines),
        "tags": ["github", f"{owner}/{repo}", kind.lower()],
        "freshness": "fresh",
        "relevance": 1.0,
        "sourceUrl": issue.get("html_url", ""),
        "sourceUpdatedAt": issue.get("updated_at") or "",
    }


def issue_document_id(owner: str, repo: str, number: int) -> str:
    """대시로만 이어붙이면 (my-org, web)과 (my, org-web)이 같은 id가 돼 서로 덮어쓴다.
    저장소 이름에 못 들어가는 '/'와 '#'를 구분자로 써서 충돌을 없앤다."""
    return f"github-{owner}/{repo}#{number}"


def repo_document_id(owner: str, repo: str) -> str:
    return f"github-{owner}/{repo}#readme"


def _fetch_repo_readme(owner: str, repo: str, headers: dict) -> str:
    """README 원문(마크다운)을 가져온다. README가 없는 저장소는 흔하므로 404는 빈 문자열로 처리."""
    try:
        resp = _request(
            "GET",
            f"/repos/{owner}/{repo}/readme",
            {**headers, "Accept": "application/vnd.github.raw+json"},
        )
        return resp.text
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return ""
        raise


def _repo_to_document(owner: str, repo: str, meta: dict, headers: dict) -> dict:
    readme = _fetch_repo_readme(owner, repo, headers)
    description = meta.get("description") or ""
    content = "\n\n".join(part for part in (description, readme) if part) or "(설명 및 README 없음)"
    updated_at = meta.get("pushed_at") or meta.get("updated_at") or ""

    return {
        "id": repo_document_id(owner, repo),
        "title": f"{owner}/{repo} — 저장소 개요",
        "source": "github",
        "author": owner,
        "authorAvatar": owner[:2],
        "date": (updated_at or "")[:10] or "1970-01-01",
        "content": content,
        "tags": ["github", f"{owner}/{repo}", "repo"],
        "freshness": "fresh",
        "relevance": 1.0,
        "sourceUrl": meta.get("html_url", f"https://github.com/{owner}/{repo}"),
        "sourceUpdatedAt": updated_at,
    }


def _fetch_repo_documents(
    owner: str, repo: str, since_iso: str, headers: dict, known: Optional[dict[str, str]] = None
) -> tuple[list[dict], set[str]]:
    """(본문을 새로 가져온 문서들, 이 저장소에서 본 전체 문서 id)."""
    known = known or {}
    documents = []
    seen_ids = set()

    # 저장소 자체 문서(설명+README) — 저장소마다 항상 최대 1개. Issue/PR과 무관하게 만들어야
    # Issue/PR이 하나도 없는 저장소도 검색 대상에 들어간다.
    repo_doc_id = repo_document_id(owner, repo)
    seen_ids.add(repo_doc_id)
    repo_meta = _request("GET", f"/repos/{owner}/{repo}", headers).json()
    repo_updated_at = repo_meta.get("pushed_at") or repo_meta.get("updated_at") or ""
    if not (repo_updated_at and known.get(repo_doc_id) == repo_updated_at):
        documents.append(_repo_to_document(owner, repo, repo_meta, headers))

    for issue in _list_recent_issues(owner, repo, since_iso, headers):
        doc_id = issue_document_id(owner, repo, issue["number"])
        seen_ids.add(doc_id)

        updated_at = issue.get("updated_at") or ""
        if updated_at and known.get(doc_id) == updated_at:
            continue  # 마지막 동기화 이후 바뀐 게 없으면 댓글 조회도 건너뛴다

        # 댓글이 0개인 이슈까지 매번 댓글 API를 부르느라 주기당 호출 수의 대부분이 낭비됐다.
        comments = (
            _list_comments(owner, repo, issue["number"], since_iso, headers)
            if issue.get("comments", 0) > 0
            else []
        )
        documents.append(_issue_to_document(owner, repo, issue, comments))

    return documents, seen_ids


def fetch_github_documents() -> list[dict]:
    """GITHUB_REPOS에 지정된 저장소의 최근 Issue/PR을 공통 문서 포맷으로 변환해 반환한다."""
    headers = _headers()
    repos = _get_target_repos()
    since_iso = (datetime.now(tz=timezone.utc) - timedelta(days=GITHUB_LOOKBACK_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    documents = []
    for repo_full in repos:
        owner, _, repo = repo_full.partition("/")
        if not repo:
            print(f"'{repo_full}'는 'owner/repo' 형식이 아니라 건너뜁니다.")
            continue
        repo_docs, _ = _fetch_repo_documents(owner, repo, since_iso, headers)
        documents.extend(repo_docs)
    return documents


def fetch_github_documents_for_user(
    access_token: str, known: Optional[dict[str, str]] = None
) -> tuple[list[dict], set[str]]:
    """계정 연동으로 받은 이 사람 본인의 access token으로, 이 사람이 실제 접근 가능한
    저장소 전체의 최근 Issue/PR을 가져온다. fetch_github_documents()(관리자가 .env에
    미리 정해둔 고정 목록)와 달리 대상 저장소 자체를 매번 새로 나열한다.

    known({id: 지난번 updated_at})을 주면 바뀐 Issue/PR만 본문·댓글을 받아온다."""
    headers = _headers(access_token)
    since_iso = (datetime.now(tz=timezone.utc) - timedelta(days=GITHUB_LOOKBACK_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    known = known or {}
    documents = []
    seen_ids = set()
    for repo_full in _list_user_repos(headers):
        owner, _, repo = repo_full.partition("/")
        if not repo:
            continue
        try:
            repo_docs, repo_seen = _fetch_repo_documents(owner, repo, since_iso, headers, known)
        except Exception as e:
            # 저장소 하나가 404/500이라고 해서 나머지 저장소 수집까지 죽으면 안 된다.
            # 다만 "못 본 것"과 "원본에서 사라진 것"은 구별해야 한다 — 확인에 실패한 저장소의
            # 기존 문서들은 그대로 있는 것으로 쳐서, 일시적 오류 때문에 삭제되지 않게 한다.
            print(f"'{repo_full}' 수집 실패, 이번 주기에는 건너뜁니다: {e}")
            prefix = f"github-{owner}/{repo}#"
            seen_ids |= {doc_id for doc_id in known if doc_id.startswith(prefix)}
            continue
        documents.extend(repo_docs)
        seen_ids |= repo_seen
    return documents, seen_ids


if __name__ == "__main__":
    docs = fetch_github_documents()
    print(f"GitHub에서 문서 {len(docs)}개를 만들었습니다.")
    for d in docs:
        print(f" - [{d['id']}] {d['title']} ({d['author']}, {d['date']})")
