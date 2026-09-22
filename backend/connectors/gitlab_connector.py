"""GitLab 프로젝트의 Issue/Merge Request(본문+댓글), 프로젝트 자체(설명+README),
그리고 프로젝트 파일 전체(소스 코드 포함)를 읽어와 Topic Thread AI의 공통 문서
포맷(dict)으로 변환한다. 쓰기 작업은 하지 않는다.
위키는 Out of scope (github_connector.py와 동일한 스코프 결정을 따름).

프로젝트 문서(설명+README)를 따로 만드는 이유는 github_connector.py와 동일 —
Issue/MR이 하나도 없는 프로젝트도 검색 대상에 들어가야 한다. 파일 전체 색인도
github_connector.py와 같은 패턴: 텍스트로 디코드되는 파일은 본문까지, 바이너리는
파일명만.

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
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def project_document_id(project_path: str) -> str:
    return f"gitlab-{project_path}#readme"


# 프로젝트 하나당 색인할 파일 수 상한 — 없으면 대형 프로젝트 하나가 동기화 주기를 다 잡아먹는다.
GITLAB_MAX_FILES_PER_PROJECT = 500
# 본문을 읽기엔 너무 큰 파일(생성된 번들 등) 기준 — 이보다 크면 파일명만 색인한다.
_MAX_FILE_BYTES = 200_000
# 내용은 진짜 코드지만 순수 자동 생성물이라 검색 가치가 없는 잠금 파일 — 파일명만 색인한다.
_LOCK_FILENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "cargo.lock",
    "poetry.lock", "pipfile.lock", "composer.lock", "gemfile.lock",
}


def project_file_document_id(project_path: str, path: str) -> str:
    return f"gitlab-{project_path}::{path}"


# github_connector.py와 동일한 이유 — .gitignore 없이 venv/node_modules 전체가 그대로
# 커밋된 저장소가 실제로 발견됨(GitHub 쪽에서, 5697개 중 5587개). 경로 기반으로 걸러낸다.
_VENDOR_PATH_SEGMENTS = (
    "/venv/", "/.venv/", "/env/", "/site-packages/", "/node_modules/",
    "/__pycache__/", "/vendor/", "/.tox/", "/dist-packages/",
)


def _is_vendored_path(path: str) -> bool:
    p = f"/{path}/"
    return any(seg in p for seg in _VENDOR_PATH_SEGMENTS)


def _list_project_tree(project_id: str, headers: dict) -> list[dict]:
    """기본 브랜치의 전체 파일 트리(파일만, blob 타입)를 가져온다."""
    try:
        items = _paginate(f"/projects/{project_id}/repository/tree", {"recursive": "true"}, headers)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return []  # 커밋이 없는 빈 프로젝트
        raise
    return [
        item for item in items
        if item.get("type") == "blob" and not _is_vendored_path(item.get("path", ""))
    ]


def _fetch_file_text(project_id: str, path: str, ref: str, headers: dict) -> Optional[str]:
    """None이면 본문을 못 읽는(또는 안 읽는) 파일이라는 뜻 — 바이너리거나 너무 큼."""
    encoded_path = urllib.parse.quote(path, safe="")
    try:
        resp = _request(
            "GET", f"/projects/{project_id}/repository/files/{encoded_path}/raw",
            headers, params={"ref": ref},
        )
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        raise
    raw = resp.content
    if len(raw) > _MAX_FILE_BYTES or b"\x00" in raw[:8000]:  # null byte = 거의 확실히 바이너리
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _file_to_document(
    project_path: str, project_id: str, item: dict, ref: str, headers: dict, project_meta: dict
) -> dict:
    path = item["path"]
    name = path.rsplit("/", 1)[-1].lower()
    content = None if name in _LOCK_FILENAMES else _fetch_file_text(project_id, path, ref, headers)
    if content is None:
        content = f"(미리보기를 지원하지 않는 파일이라 본문 내용은 없습니다 — 파일명으로만 검색됩니다: {path})"

    updated_at = project_meta.get("last_activity_at") or ""
    namespace = project_path.split("/")[0]

    return {
        "id": project_file_document_id(project_path, path),
        "title": f"{project_path} — {path}",
        "source": "gitlab",
        "author": namespace,
        "authorAvatar": namespace[:2],
        "date": (updated_at or "")[:10] or "1970-01-01",
        "content": content,
        "tags": ["gitlab", project_path, "file"],
        "freshness": "fresh",
        "relevance": 1.0,
        "sourceUrl": f"{project_meta.get('web_url', '')}/-/blob/{ref}/{path}",
        # blob sha 자체가 내용 해시라 시각보다 더 정확한 변경 감지 기준이 된다.
        "sourceUpdatedAt": item["id"],
    }


def _fetch_project_readme(project_id: str, meta: dict, headers: dict) -> str:
    """README 원문을 가져온다. GitLab에는 GitHub의 '/readme' 같은 전용 엔드포인트가 없어서,
    프로젝트 메타의 readme_url(예: .../-/blob/main/README.md)에서 브랜치·경로를 뽑아
    Repository Files API로 raw 내용을 받는다. README가 없으면 readme_url 자체가 없다."""
    readme_url = meta.get("readme_url") or ""
    default_branch = meta.get("default_branch") or ""
    marker = f"/-/blob/{default_branch}/"
    idx = readme_url.find(marker)
    if not default_branch or idx == -1:
        return ""
    file_path = readme_url[idx + len(marker):]
    encoded_path = urllib.parse.quote(file_path, safe="")
    try:
        resp = _request(
            "GET",
            f"/projects/{project_id}/repository/files/{encoded_path}/raw",
            headers,
            params={"ref": default_branch},
        )
        return resp.text
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return ""
        raise


def _project_to_document(project_path: str, project_id: str, meta: dict, headers: dict) -> dict:
    readme = _fetch_project_readme(project_id, meta, headers)
    description = meta.get("description") or ""
    content = "\n\n".join(part for part in (description, readme) if part) or "(설명 및 README 없음)"
    updated_at = meta.get("last_activity_at") or ""
    namespace = project_path.split("/")[0]

    return {
        "id": project_document_id(project_path),
        "title": f"{project_path} — 프로젝트 개요",
        "source": "gitlab",
        "author": namespace,
        "authorAvatar": namespace[:2],
        "date": (updated_at or "")[:10] or "1970-01-01",
        "content": content,
        "tags": ["gitlab", project_path, "project"],
        "freshness": "fresh",
        "relevance": 1.0,
        "sourceUrl": meta.get("web_url", ""),
        "sourceUpdatedAt": updated_at,
    }


def _fetch_project_documents(
    project_path: str, since_iso: str, headers: dict, known: Optional[dict[str, str]] = None
) -> tuple[list[dict], set[str]]:
    """(본문을 새로 가져온 문서들, 이 프로젝트에서 본 전체 문서 id)."""
    known = known or {}
    project_id = urllib.parse.quote(project_path, safe="")
    documents = []
    seen_ids = set()

    # 프로젝트 자체 문서(설명+README) — 프로젝트마다 항상 최대 1개.
    proj_doc_id = project_document_id(project_path)
    seen_ids.add(proj_doc_id)
    project_meta = _request("GET", f"/projects/{project_id}", headers).json()
    project_updated_at = project_meta.get("last_activity_at") or ""
    if not (project_updated_at and known.get(proj_doc_id) == project_updated_at):
        documents.append(_project_to_document(project_path, project_id, project_meta, headers))

    # 프로젝트 파일 전체 — README뿐 아니라 실제 소스 코드/설정도 검색 대상이 돼야 한다는 요구.
    default_branch = project_meta.get("default_branch", "main")
    tree = _list_project_tree(project_id, headers)
    if len(tree) > GITLAB_MAX_FILES_PER_PROJECT:
        print(f"'{project_path}' 파일이 {len(tree)}개라 상한({GITLAB_MAX_FILES_PER_PROJECT})까지만 색인합니다.")
        tree = tree[:GITLAB_MAX_FILES_PER_PROJECT]

    to_fetch = []
    for item in tree:
        file_doc_id = project_file_document_id(project_path, item["path"])
        seen_ids.add(file_doc_id)
        if known.get(file_doc_id) != item["id"]:  # blob sha가 그대로면 내용도 그대로라 건너뜀
            to_fetch.append(item)

    if to_fetch:
        with ThreadPoolExecutor(max_workers=min(8, len(to_fetch))) as pool:
            futures = {
                pool.submit(
                    _file_to_document, project_path, project_id, item, default_branch, headers, project_meta
                ): item
                for item in to_fetch
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    documents.append(future.result())
                except Exception as e:
                    print(f"'{project_path}' 파일 '{item['path']}' 읽기 실패, 건너뜁니다: {e}")

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
            # Issue/MR/프로젝트개요('#')와 파일('::') 두 id 체계 모두 살아있는 것으로 되돌려야 한다.
            prefixes = (f"gitlab-{project_path}#", f"gitlab-{project_path}::")
            seen_ids |= {doc_id for doc_id in known if doc_id.startswith(prefixes)}
            continue
        documents.extend(project_docs)
        seen_ids |= project_seen
    return documents, seen_ids


if __name__ == "__main__":
    docs = fetch_gitlab_documents()
    print(f"GitLab에서 문서 {len(docs)}개를 만들었습니다.")
    for d in docs:
        print(f" - [{d['id']}] {d['title']} ({d['author']}, {d['date']})")
