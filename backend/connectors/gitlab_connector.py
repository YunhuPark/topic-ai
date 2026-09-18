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


def _headers() -> dict:
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


def _request(method: str, path: str, **kwargs) -> requests.Response:
    """GitLab API 요청 공통 래퍼. rate limit(429)이면 Retry-After만큼 기다렸다 재시도."""
    url = f"{_api_base()}{path}" if path.startswith("/") else path
    for attempt in range(3):
        resp = requests.request(method, url, headers=_headers(), timeout=30, **kwargs)
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", "1"))
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp


def _paginate(path: str, params: dict) -> list[dict]:
    """GitLab의 X-Next-Page 헤더 기반 페이지네이션을 따라간다."""
    results = []
    page: Optional[str] = "1"
    while page:
        query = dict(params, page=page, per_page=100)
        resp = _request("GET", path, params=query)
        results.extend(resp.json())
        page = resp.headers.get("X-Next-Page") or None
    return results


def _list_recent_issues(project_id: str, since_iso: str) -> list[dict]:
    return _paginate(
        f"/projects/{project_id}/issues",
        {"updated_after": since_iso, "order_by": "updated_at", "scope": "all"},
    )


def _list_recent_merge_requests(project_id: str, since_iso: str) -> list[dict]:
    return _paginate(
        f"/projects/{project_id}/merge_requests",
        {"updated_after": since_iso, "order_by": "updated_at", "scope": "all"},
    )


def _list_notes(project_id: str, kind: str, iid: int, since_iso: str) -> list[dict]:
    """kind는 'issues' 또는 'merge_requests'. 시스템 자동 생성 노트(라벨 변경 등)는 제외."""
    resource = "issues" if kind == "issue" else "merge_requests"
    notes = _paginate(f"/projects/{project_id}/{resource}/{iid}/notes", {})
    return [n for n in notes if not n.get("system") and n.get("created_at", "") >= since_iso]


def _format_entry(author: str, iso_time: str, text: str) -> str:
    ts = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
    return f"**{author}** ({ts.strftime('%Y-%m-%d %H:%M')}): {text}"


def _item_to_document(project_path: str, item: dict, kind: str, notes: list[dict]) -> dict:
    author = (item.get("author") or {}).get("username", "알 수 없음")
    date = (item.get("created_at") or "")[:10] or "1970-01-01"
    title = f"{project_path}!{item['iid']}" if kind == "merge_request" else f"{project_path}#{item['iid']}"
    title = f"{title} — {item.get('title', '제목 없음')}"

    lines = [_format_entry(author, item["created_at"], item.get("description") or "(본문 없음)")]
    for n in notes:
        n_author = (n.get("author") or {}).get("username", "알 수 없음")
        lines.append(_format_entry(n_author, n["created_at"], n.get("body") or ""))

    return {
        "id": f"gitlab-{project_path.replace('/', '-')}-{kind}-{item['iid']}",
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
    }


def fetch_gitlab_documents() -> list[dict]:
    """GITLAB_PROJECTS에 지정된 프로젝트의 최근 Issue/MR을 공통 문서 포맷으로 변환해 반환한다."""
    projects = _get_target_projects()
    since_iso = (datetime.now(tz=timezone.utc) - timedelta(days=GITLAB_LOOKBACK_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    documents = []
    for project_path in projects:
        project_id = urllib.parse.quote(project_path, safe="")

        issues = _list_recent_issues(project_id, since_iso)
        for issue in issues:
            notes = _list_notes(project_id, "issue", issue["iid"], since_iso)
            documents.append(_item_to_document(project_path, issue, "issue", notes))

        merge_requests = _list_recent_merge_requests(project_id, since_iso)
        for mr in merge_requests:
            notes = _list_notes(project_id, "merge_request", mr["iid"], since_iso)
            documents.append(_item_to_document(project_path, mr, "merge_request", notes))

    return documents


if __name__ == "__main__":
    docs = fetch_gitlab_documents()
    print(f"GitLab에서 문서 {len(docs)}개를 만들었습니다.")
    for d in docs:
        print(f" - [{d['id']}] {d['title']} ({d['author']}, {d['date']})")
