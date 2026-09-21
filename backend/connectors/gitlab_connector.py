"""GitLab 프로젝트의 Issue/Merge Request(본문+댓글)를 읽어와 Topic Thread AI의
공통 문서 포맷(dict)으로 변환한다. 쓰기 작업은 하지 않는다. README/위키는
Out of scope (github_connector.py와 동일한 스코프 결정을 따름).

사전 준비 (사용자가 GitLab에서 직접 해야 하는 것):
1. GitLab > 설정(Preferences) > Access Tokens 에서 Personal Access Token 발급
   (scope: read_api 만 있으면 충분)
2. backend/.env 의 GITLAB_TOKEN 에 토큰 입력
3. backend/.env 의 GITLAB_PROJECTS 에 대상 프로젝트를 "namespace/project,namespace/project2" 형태로 입력
   (자체 호스팅 GitLab이면 GITLAB_URL도 함께 설정, 기본값은 https://gitlab.com)
"""

import os
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

GITLAB_LOOKBACK_DAYS = 90


def _api_base() -> str:
    base_url = os.getenv("GITLAB_URL", "https://gitlab.com").rstrip("/")
    return f"{base_url}/api/v4"


def _headers(token: Optional[str] = None, bearer: bool = False) -> dict:
    """token을 명시하면 그 토큰을 쓰고, 없으면 관리자가 .env에 미리 넣어둔 정적
    GITLAB_TOKEN(개인 액세스 토큰)을 쓴다. 계정 연동으로 받은 OAuth access token은
    PRIVATE-TOKEN이 아니라 Authorization: Bearer 로 인증해야 해서 bearer=True로 구분한다."""
    if token:
        return {"Authorization": f"Bearer {token}"} if bearer else {"PRIVATE-TOKEN": token}
    token = os.getenv("GITLAB_TOKEN")
    if not token or token == "your_gitlab_token_here":
        raise RuntimeError(
            "GITLAB_TOKEN이 설정되지 않았습니다. backend/.env 에 GitLab Personal Access Token을 입력하세요."
        )
    return {"PRIVATE-TOKEN": token}


def _get_target_projects() -> list[str]:
    raw = os.getenv("GITLAB_PROJECTS", "")
    projects = [p.strip() for p in raw.split(",") if p.strip()]
    if not projects:
        raise RuntimeError(
            "GITLAB_PROJECTS가 설정되지 않았습니다. backend/.env 에 'namespace/project,namespace/project2' 형태로 대상 프로젝트를 입력하세요."
        )
    return projects


def _request(method: str, path: str, headers: dict, **kwargs) -> requests.Response:
    """GitLab API 요청 공통 래퍼. rate limit(429)이면 Retry-After만큼 기다렸다 재시도."""
    url = f"{_api_base()}{path}" if path.startswith("/") else path
    for attempt in range(3):
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", "1"))
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp


def _paginate(path: str, params: dict, headers: dict) -> list[dict]:
    """GitLab의 X-Next-Page 헤더 기반 페이지네이션을 따라간다."""
    results = []
    page: Optional[str] = "1"
    while page:
        query = dict(params, page=page, per_page=100)
        resp = _request("GET", path, headers, params=query)
        results.extend(resp.json())
        page = resp.headers.get("X-Next-Page") or None
    return results


def _list_user_projects(headers: dict) -> list[str]:
    """이 토큰 소유자 본인이 멤버로 속한 프로젝트 전체를 나열한다. .env의 GITLAB_PROJECTS처럼
    관리자가 미리 정해둔 고정 목록이 아니라, 계정 연동 시점에 그 사람이 실제로 볼 수 있는
    프로젝트를 자동으로 대상으로 삼기 위함."""
    projects = _paginate(
        "/projects",
        {"membership": "true", "archived": "false", "order_by": "last_activity_at"},
        headers,
    )
    return [p["path_with_namespace"] for p in projects]


def _list_recent_issues(project_id: str, since_iso: str, headers: dict) -> list[dict]:
    return _paginate(
        f"/projects/{project_id}/issues",
        {"updated_after": since_iso, "order_by": "updated_at", "scope": "all"},
        headers,
    )


def _list_recent_merge_requests(project_id: str, since_iso: str, headers: dict) -> list[dict]:
    return _paginate(
        f"/projects/{project_id}/merge_requests",
        {"updated_after": since_iso, "order_by": "updated_at", "scope": "all"},
        headers,
    )


def _list_notes(project_id: str, kind: str, iid: int, since_iso: str, headers: dict) -> list[dict]:
    """kind는 'issues' 또는 'merge_requests'. 시스템 자동 생성 노트(라벨 변경 등)는 제외."""
    resource = "issues" if kind == "issue" else "merge_requests"
    notes = _paginate(f"/projects/{project_id}/{resource}/{iid}/notes", {}, headers)
    return [n for n in notes if not n.get("system") and n.get("created_at", "") >= since_iso]


def _format_entry(author: str, iso_time: str, text: str) -> str:
    ts = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
    return f"**{author}** ({ts.strftime('%Y-%m-%d %H:%M')}): {text}"


def _item_to_document(project_path: str, item: dict, kind: str, notes: list[dict]) -> dict:
    author = (item.get("author") or {}).get("username", "알 수 없음")
    # 생성 시점이 아니라 마지막 활동 시점(updated_at)을 문서 날짜로 써야 "최근" 판정이 맞다 —
    # 오래전에 만든 Issue/MR이라도 최근에 댓글이 달렸으면 여전히 최신 논의로 취급해야 함
    date = (item.get("updated_at") or item.get("created_at") or "")[:10] or "1970-01-01"
    title = f"{project_path}!{item['iid']}" if kind == "merge_request" else f"{project_path}#{item['iid']}"
    title = f"{title} — {item.get('title', '제목 없음')}"

    lines = [_format_entry(author, item["created_at"], item.get("description") or "(본문 없음)")]
    for n in notes:
        n_author = (n.get("author") or {}).get("username", "알 수 없음")
        lines.append(_format_entry(n_author, n["created_at"], n.get("body") or ""))

    return {
        "id": item_document_id(project_path, kind, item["iid"]),
        "title": title,
        "source": "gitlab",
        "author": author,
        "authorAvatar": author[:2],
        "date": date,
        "content": "\n\n".join(lines),
        "tags": ["gitlab", project_path, kind],
        "freshness": "fresh",
        "relevance": 1.0,
        "sourceUrl": item.get("web_url", ""),
        "sourceUpdatedAt": item.get("updated_at") or "",
    }


def item_document_id(project_path: str, kind: str, iid: int) -> str:
    """'/'를 '-'로 바꾸면 서로 다른 프로젝트가 같은 id를 갖게 될 수 있어서 경로를 그대로 쓴다."""
    return f"gitlab-{project_path}#{kind}-{iid}"


def _fetch_project_documents(
    project_path: str, since_iso: str, headers: dict, known: Optional[dict[str, str]] = None
) -> tuple[list[dict], set[str]]:
    """(본문을 새로 가져온 문서들, 이 프로젝트에서 본 전체 문서 id)."""
    known = known or {}
    project_id = urllib.parse.quote(project_path, safe="")
    documents = []
    seen_ids = set()

    for kind, items in (
        ("issue", _list_recent_issues(project_id, since_iso, headers)),
        ("merge_request", _list_recent_merge_requests(project_id, since_iso, headers)),
    ):
        for item in items:
            doc_id = item_document_id(project_path, kind, item["iid"])
            seen_ids.add(doc_id)

            updated_at = item.get("updated_at") or ""
            if updated_at and known.get(doc_id) == updated_at:
                continue  # 바뀐 게 없으면 노트(댓글) 조회까지 건너뛴다

            notes = _list_notes(project_id, kind, item["iid"], since_iso, headers)
            documents.append(_item_to_document(project_path, item, kind, notes))

    return documents, seen_ids


def fetch_gitlab_documents() -> list[dict]:
    """GITLAB_PROJECTS에 지정된 프로젝트의 최근 Issue/MR을 공통 문서 포맷으로 변환해 반환한다."""
    headers = _headers()
    projects = _get_target_projects()
    since_iso = (datetime.now(tz=timezone.utc) - timedelta(days=GITLAB_LOOKBACK_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    documents = []
    for project_path in projects:
        project_docs, _ = _fetch_project_documents(project_path, since_iso, headers)
        documents.extend(project_docs)
    return documents


def fetch_gitlab_documents_for_user(
    access_token: str, known: Optional[dict[str, str]] = None
) -> tuple[list[dict], set[str]]:
    """계정 연동으로 받은 이 사람 본인의 access token으로, 이 사람이 실제 멤버로 속한
    프로젝트 전체의 최근 Issue/MR을 가져온다. fetch_gitlab_documents()(관리자가 .env에
    미리 정해둔 고정 목록)와 달리 대상 프로젝트 자체를 매번 새로 나열한다.

    known({id: 지난번 updated_at})을 주면 바뀐 Issue/MR만 본문·댓글을 받아온다."""
    headers = _headers(access_token, bearer=True)
    since_iso = (datetime.now(tz=timezone.utc) - timedelta(days=GITLAB_LOOKBACK_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    known = known or {}
    documents = []
    seen_ids = set()
    for project_path in _list_user_projects(headers):
        try:
            project_docs, project_seen = _fetch_project_documents(
                project_path, since_iso, headers, known
            )
        except Exception as e:
            # 프로젝트 하나의 실패가 나머지 전체 수집을 죽이지 않도록. 확인에 실패한 프로젝트의
            # 기존 문서는 "그대로 있는 것"으로 쳐서 일시적 오류로 삭제되지 않게 한다.
            print(f"'{project_path}' 수집 실패, 이번 주기에는 건너뜁니다: {e}")
            prefix = f"gitlab-{project_path}#"
            seen_ids |= {doc_id for doc_id in known if doc_id.startswith(prefix)}
            continue
        documents.extend(project_docs)
        seen_ids |= project_seen
    return documents, seen_ids


if __name__ == "__main__":
    docs = fetch_gitlab_documents()
    print(f"GitLab에서 문서 {len(docs)}개를 만들었습니다.")
    for d in docs:
        print(f" - [{d['id']}] {d['title']} ({d['author']}, {d['date']})")
