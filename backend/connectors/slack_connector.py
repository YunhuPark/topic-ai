"""Slack 워크스페이스에서 봇이 초대된 채널의 최근 대화를 읽어와
Topic Thread AI의 공통 문서 포맷(dict)으로 변환한다. 쓰기 작업은 하지 않는다.

사전 준비 (사용자가 Slack에서 직접 해야 하는 것):
1. https://api.slack.com/apps 에서 새 앱 생성 (From scratch)
2. OAuth & Permissions > Bot Token Scopes 에 아래 권한 추가:
   channels:history, channels:read, groups:history, groups:read, users:read
3. Install to Workspace 후 발급되는 Bot User OAuth Token(xoxb-...)을
   backend/.env 의 SLACK_BOT_TOKEN 에 입력
4. 읽고 싶은 채널에서 `/invite @앱이름` 으로 봇을 초대 (초대 안 하면 안 보임)

FR-4 스펙 (PRD.md 참고):
- 봇이 멤버인 채널만 대상
- 채널별 최근 SLACK_LOOKBACK_DAYS 일 이내 메시지만
- 스레드는 통째로 한 문서, 스레드 없는 메시지는 같은 날짜끼리 묶어서 한 문서

메시지에 첨부된 파일(files 배열)도 읽는다(2026-09-21 추가) — PDF/DOCX/일반 텍스트류는 실제
본문까지, 그 외(이미지 등)는 파일명만 메시지 본문에 같이 남겨서 최소한 파일명으로는 검색되게
한다(gdrive_connector의 "본문 추출 안 되면 파일명만" 패턴과 동일).
"""

import io
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from docx import Document as DocxDocument
from dotenv import load_dotenv
from pypdf import PdfReader

load_dotenv()

SLACK_API_BASE = "https://slack.com/api"
SLACK_LOOKBACK_DAYS = 90

# Slack이 "@이름" 자동완성 멘션을 실제 메시지 텍스트에 <@U0123ABC>(사용자 ID) 형태로 저장해서,
# 해석 안 하고 그대로 두면 LLM 입장에선 의미 없는 토큰이라 담당자 추론에 전혀 쓸 수 없다.
# 반대로 이 형태는 Slack이 사용자 ID로 못박아준 것이라 동명이인 문제 자체가 없는 가장 확실한
# 담당자 신호이므로, 실제 표시 이름으로 풀어서 넣어준다.
_MENTION_RE = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]+)?>")

_user_name_cache: dict[str, str] = {}


def _headers(token: Optional[str] = None) -> dict:
    """token을 명시하면 그 토큰(계정 연동으로 받은 사용자 본인 access token)을 쓰고,
    없으면 수집용 SLACK_BOT_TOKEN을 쓴다."""
    token = token or os.getenv("SLACK_BOT_TOKEN")
    if not token or token == "your_slack_bot_token_here":
        raise RuntimeError(
            "SLACK_BOT_TOKEN이 설정되지 않았습니다. backend/.env 에 Slack Bot Token을 입력하세요."
        )
    return {"Authorization": f"Bearer {token}"}


def _request(method: str, path: str, headers: dict, **kwargs) -> dict:
    """Slack Web API 요청 공통 래퍼. rate limit(429)이면 Retry-After만큼 기다렸다 재시도.
    Slack은 에러도 200 OK + {"ok": false, "error": "..."} 로 내려주는 경우가 많아 그것도 체크한다.
    """
    url = f"{SLACK_API_BASE}/{path}"
    for attempt in range(3):
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", "1"))
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API 에러 ({path}): {data.get('error')}")
        return data
    raise RuntimeError(f"Slack API 요청 재시도 초과: {path}")


def _list_member_channels(headers: dict) -> list[dict]:
    """이 토큰 소유자(봇 또는 사용자 본인)가 멤버로 들어가 있는 채널 목록만 반환한다."""
    channels = []
    cursor: Optional[str] = None
    while True:
        params = {
            "types": "public_channel,private_channel",
            "exclude_archived": "true",
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor
        data = _request("GET", "conversations.list", headers, params=params)
        for ch in data.get("channels", []):
            if ch.get("is_member"):
                channels.append(ch)
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return channels


def _resolve_user_name(user_id: Optional[str], headers: dict) -> str:
    if not user_id:
        return "알 수 없음"
    if user_id in _user_name_cache:
        return _user_name_cache[user_id]
    try:
        data = _request("GET", "users.info", headers, params={"user": user_id})
        profile = data.get("user", {})
        name = profile.get("real_name") or profile.get("name") or "알 수 없음"
    except (requests.HTTPError, RuntimeError):
        name = "알 수 없음"
    _user_name_cache[user_id] = name
    return name


def _resolve_mentions(text: str, headers: dict) -> str:
    """메시지 본문 안의 <@USERID> 멘션을 실제 표시 이름으로 풀어준다 (예: "<@U0123ABC> 부탁드려요"
    → "@박승현 부탁드려요"). Slack이 사용자 ID로 못박아준 멘션이라 동명이인이어도 정확하다."""
    return _MENTION_RE.sub(lambda m: f"@{_resolve_user_name(m.group(1), headers)}", text)


def _fetch_channel_history(channel_id: str, oldest_ts: str, headers: dict) -> list[dict]:
    """일반 메시지(subtype 없는 것)만, 시간순으로 반환한다."""
    messages = []
    cursor: Optional[str] = None
    while True:
        params = {"channel": channel_id, "oldest": oldest_ts, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = _request("GET", "conversations.history", headers, params=params)
        for msg in data.get("messages", []):
            if msg.get("subtype"):  # bot_message, channel_join 등 시스템 메시지 제외
                continue
            messages.append(msg)
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return sorted(messages, key=lambda m: float(m["ts"]))


def _fetch_thread_replies(channel_id: str, thread_ts: str, headers: dict) -> list[dict]:
    replies = []
    cursor: Optional[str] = None
    while True:
        params = {"channel": channel_id, "ts": thread_ts, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = _request("GET", "conversations.replies", headers, params=params)
        replies.extend(data.get("messages", []))
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    # 첫 메시지(부모)는 history에서 이미 가지고 있으므로 답글만 반환
    return sorted(replies, key=lambda m: float(m["ts"]))[1:]


def _download_slack_file(url: str, headers: dict) -> bytes:
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.content


def _extract_file_text(f: dict, headers: dict) -> str:
    """PDF/DOCX/일반 텍스트 첨부만 실제 본문을 읽는다(이미 gdrive_connector에서 쓰는 것과
    같은 파서 재사용). 그 외(이미지 등)는 미리보기 없이 파일명만 메시지에 남는다 — 그래도
    검색은 파일명으로 된다."""
    filetype = (f.get("filetype") or "").lower()
    name = (f.get("name") or "").lower()
    url = f.get("url_private_download") or f.get("url_private")
    if not url:
        return ""
    try:
        if filetype == "pdf" or name.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(_download_slack_file(url, headers)))
            return "\n\n".join((p.extract_text() or "") for p in reader.pages).strip()
        if filetype == "docx" or name.endswith(".docx"):
            doc = DocxDocument(io.BytesIO(_download_slack_file(url, headers)))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        if name.endswith((".txt", ".md", ".csv", ".log", ".json", ".yaml", ".yml")):
            return _download_slack_file(url, headers).decode("utf-8", errors="replace")
    except Exception:
        return ""  # 다운로드/파싱 실패해도 메시지 자체 수집은 계속 진행
    return ""


def _format_attachments(msg: dict, headers: dict) -> str:
    files = msg.get("files") or []
    if not files:
        return ""
    lines = []
    for f in files:
        name = f.get("name") or f.get("title") or "파일"
        text = _extract_file_text(f, headers)
        lines.append(f"[첨부파일: {name}]\n{text}" if text else f"[첨부파일: {name}] (미리보기 지원 안 함)")
    return "\n".join(lines)


def _format_message_line(msg: dict, headers: dict) -> str:
    author = _resolve_user_name(msg.get("user"), headers)
    ts = datetime.fromtimestamp(float(msg["ts"]), tz=timezone.utc)
    text = _resolve_mentions(msg.get("text", ""), headers)
    attachments = _format_attachments(msg, headers)
    if attachments:
        text = f"{text}\n{attachments}" if text else attachments
    return f"**{author}** ({ts.strftime('%H:%M')}): {text}"


def _get_permalink(channel_id: str, ts: str, headers: dict) -> str:
    try:
        data = _request("GET", "chat.getPermalink", headers, params={"channel": channel_id, "message_ts": ts})
        return data.get("permalink", "")
    except (requests.HTTPError, RuntimeError):
        return ""


def _bundle_to_document(channel: dict, messages: list[dict], headers: dict) -> Optional[dict]:
    if not messages:
        return None
    root = messages[0]
    root_ts = root["ts"]
    author = _resolve_user_name(root.get("user"), headers)
    date = datetime.fromtimestamp(float(root_ts), tz=timezone.utc).strftime("%Y-%m-%d")
    first_text = _resolve_mentions((root.get("text") or "").strip(), headers).replace("\n", " ")
    title_snippet = first_text[:30] + ("..." if len(first_text) > 30 else "")
    title = f"#{channel['name']} — {title_snippet}" if title_snippet else f"#{channel['name']} — 대화"

    content = "\n\n".join(_format_message_line(m, headers) for m in messages)

    return {
        "id": f"slack-{channel['id']}-{root_ts}",
        "title": title,
        "source": "slack",
        "author": author,
        "authorAvatar": author[:2],
        "date": date,
        "content": content,
        "tags": ["slack", channel["name"]],
        "freshness": "fresh",
        "relevance": 1.0,
        "sourceUrl": _get_permalink(channel["id"], root_ts, headers),
        # 이 묶음의 마지막 메시지 시각. Slack은 "스레드/날짜 묶음"이 문서 단위라 증분 경계가
        # 애매해서 수집 자체는 매번 전체로 하고, 재임베딩 여부는 본문 해시로 거른다.
        "sourceUpdatedAt": messages[-1].get("ts", root_ts),
    }


def _bundle_channel_messages(channel: dict, messages: list[dict], headers: dict) -> list[dict]:
    """스레드는 통째로 한 문서, 스레드 없는 메시지는 같은 날짜끼리 한 문서로 묶는다."""
    documents = []
    consumed_ts = set()

    # 1. 스레드(부모 메시지가 reply_count를 가진 것)부터 묶는다
    for msg in messages:
        if msg["ts"] in consumed_ts:
            continue
        if msg.get("reply_count", 0) > 0 and msg.get("thread_ts") == msg["ts"]:
            replies = _fetch_thread_replies(channel["id"], msg["ts"], headers)
            bundle = [msg] + replies
            for m in bundle:
                consumed_ts.add(m["ts"])
            doc = _bundle_to_document(channel, bundle, headers)
            if doc:
                documents.append(doc)

    # 2. 나머지(스레드에 속하지 않은) 메시지는 날짜별로 묶는다
    remaining_by_date: dict[str, list[dict]] = defaultdict(list)
    for msg in messages:
        if msg["ts"] in consumed_ts:
            continue
        date = datetime.fromtimestamp(float(msg["ts"]), tz=timezone.utc).strftime("%Y-%m-%d")
        remaining_by_date[date].append(msg)

    for date_msgs in remaining_by_date.values():
        doc = _bundle_to_document(channel, date_msgs, headers)
        if doc:
            documents.append(doc)

    return documents


def _fetch_documents(
    headers: dict, known: Optional[dict[str, str]] = None
) -> tuple[list[dict], set[str]]:
    known = known or {}
    oldest_dt = datetime.now(tz=timezone.utc) - timedelta(days=SLACK_LOOKBACK_DAYS)
    oldest_ts = str(oldest_dt.timestamp())

    documents = []
    seen_ids = set()
    for channel in _list_member_channels(headers):
        try:
            messages = _fetch_channel_history(channel["id"], oldest_ts, headers)
            channel_docs = _bundle_channel_messages(channel, messages, headers)
        except Exception as e:
            # 채널 하나(예: 권한이 막힌 비공개 채널, 일시적 rate limit)의 실패가 전체 수집을
            # 죽이지 않도록. 확인에 실패한 채널의 기존 문서는 "그대로 있는 것"으로 쳐서
            # 일시적 오류 때문에 삭제되지 않게 한다.
            print(f"Slack 채널 '#{channel.get('name')}' 수집 실패, 이번 주기에는 건너뜁니다: {e}")
            prefix = f"slack-{channel['id']}-"
            seen_ids |= {doc_id for doc_id in known if doc_id.startswith(prefix)}
            continue
        documents.extend(channel_docs)
        seen_ids |= {doc["id"] for doc in channel_docs}
    return documents, seen_ids


def fetch_slack_documents() -> list[dict]:
    """봇이 속한 모든 채널의 최근 대화를 Topic Thread AI 공통 문서 포맷으로 변환해 반환한다."""
    documents, _ = _fetch_documents(_headers())
    return documents


def fetch_slack_documents_for_user(
    user_access_token: str, known: Optional[dict[str, str]] = None
) -> tuple[list[dict], set[str]]:
    """계정 연동으로 받은 이 사람 본인의 access token으로, 이 사람이 실제 멤버로 속한
    채널 전체(봇이 초대되지 않은 비공개 채널 포함)의 최근 대화를 가져온다.

    Slack은 "스레드/날짜 묶음"이 문서 단위라 어디까지가 변경인지 경계가 애매해서 수집 자체는
    매번 전체로 한다 — 대신 내용이 그대로면 rag_pipeline이 본문 해시를 보고 재임베딩을 건너뛴다."""
    return _fetch_documents(_headers(user_access_token), known)


if __name__ == "__main__":
    docs = fetch_slack_documents()
    print(f"Slack에서 문서 {len(docs)}개를 만들었습니다.")
    for d in docs:
        print(f" - [{d['id']}] {d['title']} ({d['author']}, {d['date']})")
