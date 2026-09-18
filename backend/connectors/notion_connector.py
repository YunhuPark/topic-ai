"""Notion 워크스페이스에서 이 통합(Integration)에 공유된 페이지를 읽어와
Topic Thread AI의 공통 문서 포맷(dict)으로 변환한다. 쓰기 작업은 하지 않는다.

사전 준비 (사용자가 Notion에서 직접 해야 하는 것):
1. https://www.notion.so/my-integrations 에서 Internal Integration 생성 후 토큰 발급
2. backend/.env 의 NOTION_TOKEN 에 그 토큰 입력
3. 인덱싱하고 싶은 Notion 페이지/데이터베이스를 열어 우측 상단 '연결 추가'에서
   방금 만든 통합을 공유(Share) — 공유하지 않은 페이지는 API에 보이지 않는다.
"""

import os
import time
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# rich_text를 가진 블록 타입만 텍스트로 뽑는다. 표/이미지/파일 등은 건너뛴다.
_TEXT_BLOCK_TYPES = {
    "paragraph", "heading_1", "heading_2", "heading_3",
    "bulleted_list_item", "numbered_list_item", "to_do",
    "toggle", "quote", "callout", "code",
}

_user_name_cache: dict[str, str] = {}


def _headers() -> dict:
    token = os.getenv("NOTION_TOKEN")
    if not token or token == "your_notion_token_here":
        raise RuntimeError(
            "NOTION_TOKEN이 설정되지 않았습니다. backend/.env 에 Notion Integration 토큰을 입력하세요."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, **kwargs) -> dict:
    """Notion API 요청 공통 래퍼. 429(rate limit)면 Retry-After만큼 기다렸다 재시도."""
    url = f"{NOTION_API_BASE}{path}"
    for attempt in range(3):
        resp = requests.request(method, url, headers=_headers(), timeout=30, **kwargs)
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", "1"))
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    return {}


def _list_shared_pages() -> list[dict]:
    """이 통합에 공유된 모든 페이지를 가져온다 (검색어 없이 search하면 공유된 전체 목록)."""
    pages = []
    start_cursor: Optional[str] = None
    while True:
        body = {
            "filter": {"property": "object", "value": "page"},
            "page_size": 100,
        }
        if start_cursor:
            body["start_cursor"] = start_cursor
        data = _request("POST", "/search", json=body)
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        start_cursor = data.get("next_cursor")
    return pages


def _resolve_user_name(user_id: Optional[str]) -> str:
    if not user_id:
        return "알 수 없음"
    if user_id in _user_name_cache:
        return _user_name_cache[user_id]
    try:
        data = _request("GET", f"/users/{user_id}")
        name = data.get("name") or "알 수 없음"
    except requests.HTTPError:
        name = "알 수 없음"
    _user_name_cache[user_id] = name
    return name


def _extract_page_title(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            title_parts = prop.get("title", [])
            text = "".join(t.get("plain_text", "") for t in title_parts)
            return text.strip() or "제목 없음"
    return "제목 없음"


def _rich_text_to_plain(rich_text: list[dict]) -> str:
    return "".join(t.get("plain_text", "") for t in rich_text)


def _block_to_text(block: dict) -> str:
    block_type = block.get("type")
    if block_type not in _TEXT_BLOCK_TYPES:
        return ""
    payload = block.get(block_type, {})
    text = _rich_text_to_plain(payload.get("rich_text", []))
    if block_type == "to_do":
        checked = "[x]" if payload.get("checked") else "[ ]"
        return f"{checked} {text}"
    if block_type in ("bulleted_list_item", "numbered_list_item"):
        return f"- {text}"
    return text


def _fetch_block_children_text(block_id: str, depth: int = 0, max_depth: int = 6) -> list[str]:
    """블록 하위 자식들을 재귀적으로 순회하며 텍스트 라인 목록을 만든다."""
    if depth > max_depth:
        return []
    lines: list[str] = []
    start_cursor: Optional[str] = None
    while True:
        params = {"page_size": 100}
        if start_cursor:
            params["start_cursor"] = start_cursor
        data = _request("GET", f"/blocks/{block_id}/children", params=params)
        for block in data.get("results", []):
            text = _block_to_text(block)
            if text:
                lines.append(text)
            if block.get("has_children"):
                lines.extend(_fetch_block_children_text(block["id"], depth + 1, max_depth))
        if not data.get("has_more"):
            break
        start_cursor = data.get("next_cursor")
    return lines


def fetch_notion_documents() -> list[dict]:
    """공유된 모든 Notion 페이지를 Topic Thread AI 공통 문서 포맷으로 변환해 반환한다."""
    documents = []
    for page in _list_shared_pages():
        page_id = page["id"]
        title = _extract_page_title(page)
        author = _resolve_user_name((page.get("created_by") or {}).get("id"))
        date = (page.get("created_time") or "")[:10]
        content_lines = _fetch_block_children_text(page_id)
        content = "\n".join(content_lines) if content_lines else "(본문 없음)"

        documents.append({
            "id": f"notion-{page_id}",
            "title": title,
            "source": "notion",
            "author": author,
            "authorAvatar": author[:2],
            "date": date or "1970-01-01",
            "content": content,
            "tags": ["notion"],
            "freshness": "fresh",
            "relevance": 1.0,
            "sourceUrl": page.get("url", ""),
        })
    return documents


if __name__ == "__main__":
    docs = fetch_notion_documents()
    print(f"공유된 Notion 페이지 {len(docs)}개를 가져왔습니다.")
    for d in docs:
        print(f" - [{d['id']}] {d['title']} ({d['author']}, {d['date']})")
