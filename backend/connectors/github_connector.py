"""GitHub 저장소의 Issue/PR(본문+댓글)을 읽어와 Topic Thread AI의 공통
문서 포맷(dict)으로 변환한다. 쓰기 작업은 하지 않는다. README/위키는
Out of scope (PRD.md FR-6 참고).

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
    """token을 명시하면 그 값을 그대로 쓰고(계정 연동 시 저장해둔 사용자 본인 OAuth 토큰),
    안 주면 기존처럼 .env의 관리자 PAT(GITHUB_TOKEN)를 쓴다 — CLI 수집 경로는 그대로 유지."""
    if not token:
        token = os.getenv("GITHUB_TOKEN")
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


def _request(method: str, path: str, token: Optional[str] = None, **kwargs) -> requests.Response:
    """GitHub API 요청 공통 래퍼. rate limit이면 X-RateLimit-Reset까지 기다렸다 재시도."""
    url = f"{GITHUB_API_BASE}{path}" if path.startswith("/") else path
    for attempt in range(3):
        resp = requests.request(method, url, headers=_headers(token), timeout=30, **kwargs)
        if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            reset_at = int(resp.headers.get("X-RateLimit-Reset", time.time() + 5))
            wait = max(reset_at - time.time(), 1)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp


def _paginate(path: str, params: dict, token: Optional[str] = None) -> list[dict]:
    """GitHub의 Link 헤더 기반 페이지네이션을 따라간다."""
    results = []
    url: Optional[str] = f"{GITHUB_API_BASE}{path}"
    query = dict(params)
    while url:
        resp = _request("GET", url, token=token, params=query)
        results.extend(resp.json())
        query = {}  # next 링크에 파라미터가 이미 포함돼 있음
        url = resp.links.get("next", {}).get("url")
    return results


def _list_recent_issues(owner: str, repo: str, since_iso: str, token: Optional[str] = None) -> list[dict]:
    """Issue와 PR을 함께 반환한다 (GitHub API 특성). pull_request 키 유무로 구분 가능."""
    return _paginate(
        f"/repos/{owner}/{repo}/issues",
        {"state": "all", "since": since_iso, "per_page": 100, "sort": "updated"},
        token=token,
    )


def _list_comments(owner: str, repo: str, issue_number: int, since_iso: str, token: Optional[str] = None) -> list[dict]:
    comments = _paginate(
        f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
        {"since": since_iso, "per_page": 100},
        token=token,
    )
    return [c for c in comments if (c.get("user") or {}).get("type") != "Bot"]


def _list_user_repos(token: str) -> list[str]:
    """이 토큰(계정 연동 시 저장해둔 사용자 본인 OAuth 토큰)으로 접근 가능한 저장소 전체를
    자동으로 찾는다 — GITHUB_REPOS 같은 고정 목록을 안 써도 되게 하는 함수. fork/archived는
    노이즈가 많아서 제외한다."""
    repos = _paginate(
        "/user/repos",
        {"per_page": 100, "affiliation": "owner,collaborator,organization_member", "sort": "updated"},
        token=token,
    )
    return [r["full_name"] for r in repos if not r.get("fork") and not r.get("archived")]


def _format_entry(author: str, iso_time: str, text: str) -> str:
    ts = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
    return f"**{author}** ({ts.strftime('%Y-%m-%d %H:%M')}): {text}"


def _issue_to_document(owner: str, repo: str, issue: dict, comments: list[dict]) -> dict:
    is_pr = "pull_request" in issue
    author = (issue.get("user") or {}).get("login", "알 수 없음")
    date = (issue.get("created_at") or "")[:10] or "1970-01-01"
    kind = "PR" if is_pr else "Issue"
    title = f"{owner}/{repo}#{issue['number']} — {issue.get('title', '제목 없음')}"

    lines = [_format_entry(author, issue["created_at"], issue.get("body") or "(본문 없음)")]
    for c in comments:
        c_author = (c.get("user") or {}).get("login", "알 수 없음")
        lines.append(_format_entry(c_author, c["created_at"], c.get("body") or ""))

    return {
        "id": f"github-{owner}-{repo}-{issue['number']}",
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
    }


def _fetch_documents_for_repos(repos: list[str], token: Optional[str] = None) -> list[dict]:
    since_iso = (datetime.now(tz=timezone.utc) - timedelta(days=GITHUB_LOOKBACK_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    documents = []
    for repo_full in repos:
        owner, _, repo = repo_full.partition("/")
        if not repo:
            print(f"'{repo_full}'는 'owner/repo' 형식이 아니라 건너뜁니다.")
            continue
        issues = _list_recent_issues(owner, repo, since_iso, token=token)
        for issue in issues:
            comments = _list_comments(owner, repo, issue["number"], since_iso, token=token)
            documents.append(_issue_to_document(owner, repo, issue, comments))
    return documents


def fetch_github_documents() -> list[dict]:
    """GITHUB_REPOS에 지정된 저장소의 최근 Issue/PR을 공통 문서 포맷으로 변환해 반환한다
    (관리자가 미리 지정한 고정 목록 — .env의 GITHUB_TOKEN을 쓴다)."""
    return _fetch_documents_for_repos(_get_target_repos())


def fetch_github_documents_for_token(token: str) -> list[dict]:
    """계정 연동 시 저장해둔 사용자 본인 OAuth 토큰으로, 그 사람이 접근 가능한 저장소 전체를
    자동으로 찾아 Issue/PR을 수집한다 — GITHUB_REPOS 고정 목록이 필요 없다."""
    repos = _list_user_repos(token)
    return _fetch_documents_for_repos(repos, token=token)


if __name__ == "__main__":
    docs = fetch_github_documents()
    print(f"GitHub에서 문서 {len(docs)}개를 만들었습니다.")
    for d in docs:
        print(f" - [{d['id']}] {d['title']} ({d['author']}, {d['date']})")
