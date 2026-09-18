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
"""

import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

SLACK_API_BASE = "https://slack.com/api"
SLACK_LOOKBACK_DAYS = 90

_user_name_cache: dict[str, str] = {}


def _headers() -> dict:
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token or token == "your_slack_bot_token_here":
        raise RuntimeError(
            "SLACK_BOT_TOKEN이 설정되지 않았습니다. backend/.env 에 Slack Bot Token을 입력하세요."
        )
    return {"Authorization": f"Bearer {token}"}


def _request(method: str, path: str, **kwargs) -> dict:
    """Slack Web API 요청 공통 래퍼. rate limit(429)이면 Retry-After만큼 기다렸다 재시도.
    Slack은 에러도 200 OK + {"ok": false, "error": "..."} 로 내려주는 경우가 많아 그것도 체크한다.
    """
    url = f"{SLACK_API_BASE}/{path}"
    for attempt in range(3):
        resp = requests.request(method, url, headers=_headers(), timeout=30, **kwargs)
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


def _list_bot_channels() -> list[dict]:
    """봇이 멤버로 들어가 있는 채널 목록만 반환한다."""
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
        data = _request("GET", "conversations.list", params=params)
        for ch in data.get("channels", []):
            if ch.get("is_member"):
                channels.append(ch)
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return channels


def _resolve_user_name(user_id: Optional[str]) -> str:
    if not user_id:
        return "알 수 없음"
    if user_id in _user_name_cache:
        return _user_name_cache[user_id]
    try:
        data = _request("GET", "users.info", params={"user": user_id})
        profile = data.get("user", {})
        name = profile.get("real_name") or profile.get("name") or "알 수 없음"
    except (requests.HTTPError, RuntimeError):
        name = "알 수 없음"
    _user_name_cache[user_id] = name
    return name


def _fetch_channel_history(channel_id: str, oldest_ts: str) -> list[dict]:
    """일반 메시지(subtype 없는 것)만, 시간순으로 반환한다."""
    messages = []
    cursor: Optional[str] = None
    while True:
        params = {"channel": channel_id, "oldest": oldest_ts, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = _request("GET", "conversations.history", params=params)
        for msg in data.get("messages", []):
            if msg.get("subtype"):  # bot_message, channel_join 등 시스템 메시지 제외
                continue
            messages.append(msg)
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return sorted(messages, key=lambda m: float(m["ts"]))


def _fetch_thread_replies(channel_id: str, thread_ts: str) -> list[dict]:
    replies = []
    cursor: Optional[str] = None
    while True:
        params = {"channel": channel_id, "ts": thread_ts, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = _request("GET", "conversations.replies", params=params)
        replies.extend(data.get("messages", []))
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    # 첫 메시지(부모)는 history에서 이미 가지고 있으므로 답글만 반환
    return sorted(replies, key=lambda m: float(m["ts"]))[1:]


def _format_message_line(msg: dict) -> str:
    author = _resolve_user_name(msg.get("user"))
    ts = datetime.fromtimestamp(float(msg["ts"]), tz=timezone.utc)
    text = msg.get("text", "")
    return f"**{author}** ({ts.strftime('%H:%M')}): {text}"


def _get_permalink(channel_id: str, ts: str) -> str:
    try:
        data = _request("GET", "chat.getPermalink", params={"channel": channel_id, "message_ts": ts})
        return data.get("permalink", "")
    except (requests.HTTPError, RuntimeError):
        return ""


def _bundle_to_document(channel: dict, messages: list[dict]) -> Optional[dict]:
    if not messages:
        return None
    root = messages[0]
    root_ts = root["ts"]
    author = _resolve_user_name(root.get("user"))
    date = datetime.fromtimestamp(float(root_ts), tz=timezone.utc).strftime("%Y-%m-%d")
    first_text = (root.get("text") or "").strip().replace("\n", " ")
    title_snippet = first_text[:30] + ("..." if len(first_text) > 30 else "")
    title = f"#{channel['name']} — {title_snippet}" if title_snippet else f"#{channel['name']} — 대화"

    content = "\n\n".join(_format_message_line(m) for m in messages)

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
        "sourceUrl": _get_permalink(channel["id"], root_ts),
    }


def _bundle_channel_messages(channel: dict, messages: list[dict]) -> list[dict]:
    """스레드는 통째로 한 문서, 스레드 없는 메시지는 같은 날짜끼리 한 문서로 묶는다."""
    documents = []
    consumed_ts = set()

    # 1. 스레드(부모 메시지가 reply_count를 가진 것)부터 묶는다
    for msg in messages:
        if msg["ts"] in consumed_ts:
            continue
        if msg.get("reply_count", 0) > 0 and msg.get("thread_ts") == msg["ts"]:
            replies = _fetch_thread_replies(channel["id"], msg["ts"])
            bundle = [msg] + replies
            for m in bundle:
                consumed_ts.add(m["ts"])
            doc = _bundle_to_document(channel, bundle)
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
        doc = _bundle_to_document(channel, date_msgs)
        if doc:
            documents.append(doc)

    return documents


def fetch_slack_documents() -> list[dict]:
    """봇이 속한 모든 채널의 최근 대화를 Topic Thread AI 공통 문서 포맷으로 변환해 반환한다."""
    oldest_dt = datetime.now(tz=timezone.utc) - timedelta(days=SLACK_LOOKBACK_DAYS)
    oldest_ts = str(oldest_dt.timestamp())

    documents = []
    for channel in _list_bot_channels():
        messages = _fetch_channel_history(channel["id"], oldest_ts)
        documents.extend(_bundle_channel_messages(channel, messages))
    return documents


if __name__ == "__main__":
    docs = fetch_slack_documents()
    print(f"Slack에서 문서 {len(docs)}개를 만들었습니다.")
    for d in docs:
        print(f" - [{d['id']}] {d['title']} ({d['author']}, {d['date']})")
