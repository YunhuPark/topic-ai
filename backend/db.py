"""자체 계정 시스템을 위한 로컬 SQLite 저장소.

users: 이메일+비밀번호로 가입하는 우리 사이트 자체 계정.
linked_accounts: 그 계정에 연결된 외부 소스 신원(Google/Slack/GitHub/GitLab/Notion 등).
   Phase 6b(Google)부터 순서대로 채워진다.
search_history / action_items: 브라우저 localStorage가 아니라 계정(user_id)에 귀속되는
   검색 기록·액션아이템. 로그인 없이는 검색 자체가 안 되므로(로그인 필수 전환), 항상
   실제 계정과 연결된 데이터다.
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")


def get_connection() -> sqlite3.Connection:
    # 백그라운드 동기화 스레드와 요청 처리 스레드가 동시에 쓰기 때문에, 기본 5초 대기로는
    # "database is locked"가 검색 500으로 튀어나올 수 있다. WAL + 넉넉한 timeout으로 완화.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS linked_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                provider_email TEXT,
                access_token TEXT,
                linked_at TEXT NOT NULL,
                UNIQUE(user_id, provider),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        # 예전 스키마로 만들어져 있던 경우를 위한 마이그레이션
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(linked_accounts)")}
        if "access_token" not in existing_columns:
            conn.execute("ALTER TABLE linked_accounts ADD COLUMN access_token TEXT")
        if "refresh_token" not in existing_columns:
            # GitLab OAuth access token은 기본 2시간이면 만료된다 — refresh_token을 저장하지
            # 않으면 연동 두 시간 뒤부터 그 소스 문서가 통째로 검색에서 사라진다.
            conn.execute("ALTER TABLE linked_accounts ADD COLUMN refresh_token TEXT")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                query TEXT NOT NULL,
                searched_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS action_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                query TEXT NOT NULL,
                source_item_id TEXT NOT NULL,
                task TEXT NOT NULL,
                assignee TEXT,
                due_date TEXT,
                status TEXT NOT NULL,
                source TEXT,
                user_modified INTEGER NOT NULL DEFAULT 0,
                saved_at TEXT NOT NULL,
                UNIQUE(user_id, query, source_item_id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        conn.commit()
    finally:
        conn.close()


def record_search(user_id: int, query: str):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO search_history (user_id, query, searched_at) VALUES (?, ?, ?)",
            (user_id, query, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def get_search_history(user_id: int, limit: int = 10) -> list[dict]:
    """쿼리별 가장 최근 검색 시각만 남겨서, 최신순으로 최대 limit개 반환한다."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT query, MAX(searched_at) AS searched_at
            FROM search_history
            WHERE user_id = ?
            GROUP BY query
            ORDER BY searched_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def count_searches_since(user_id: int, since_iso: str) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM search_history WHERE user_id = ? AND searched_at >= ?",
            (user_id, since_iso),
        ).fetchone()
    finally:
        conn.close()
    return row["c"] if row else 0


def upsert_action_items(user_id: int, query: str, items: list[dict]):
    """검색마다 AI가 새로 뽑아낸 액션아이템을 저장한다. 사용자가 이미 로컬에서 상태를
    바꿔둔(user_modified) 항목은 같은 (query, source_item_id) 재검색으로 덮어쓰지 않는다."""
    conn = get_connection()
    try:
        for item in items:
            existing = conn.execute(
                "SELECT task, status, user_modified FROM action_items WHERE user_id = ? AND query = ? AND source_item_id = ?",
                (user_id, query, item["id"]),
            ).fetchone()
            # source_item_id는 LLM이 매번 새로 붙이는 임시 id("a1")라, 같은 질의를 다시 검색하면
            # 같은 "a1"에 전혀 다른 할 일이 들어올 수 있다. 그때 이전 상태를 물려주면 새 할 일이
            # 이미 "완료"로 표시되므로, **내용이 그대로일 때만** 사용자가 바꾼 상태를 유지한다.
            same_task = bool(existing) and (existing["task"] or "") == item.get("task", "")
            keep_user_status = bool(existing) and existing["user_modified"] and same_task
            status = existing["status"] if keep_user_status else item.get("status", "pending")
            conn.execute(
                """
                INSERT INTO action_items
                    (user_id, query, source_item_id, task, assignee, due_date, status, source, user_modified, saved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, query, source_item_id) DO UPDATE SET
                    task = excluded.task,
                    assignee = excluded.assignee,
                    due_date = excluded.due_date,
                    status = excluded.status,
                    source = excluded.source,
                    saved_at = excluded.saved_at
                """,
                (
                    user_id, query, item["id"], item.get("task", ""), item.get("assignee", ""),
                    item.get("dueDate", ""), status, item.get("source", ""),
                    1 if keep_user_status else 0,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_action_items(user_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, query, task, assignee, due_date, status, source, saved_at
            FROM action_items
            WHERE user_id = ?
            ORDER BY
                CASE status WHEN 'pending' THEN 0 WHEN 'in-progress' THEN 1 ELSE 2 END,
                saved_at DESC
            """,
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def delete_action_item(user_id: int, item_id: int) -> bool:
    """사용자가 직접 할 일을 지운다. 예전엔 지울 방법이 아예 없어서, 한번 뽑힌 항목이
    (잘못 추출된 것이라도) 영원히 목록에 남았다."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM action_items WHERE id = ? AND user_id = ?", (item_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def toggle_action_item_status(user_id: int, item_id: int) -> Optional[dict]:
    STATUS_CYCLE = ["pending", "in-progress", "completed"]
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT status FROM action_items WHERE id = ? AND user_id = ?", (item_id, user_id)
        ).fetchone()
        if not row:
            return None
        # 과거에 저장된 값이 영문 3종(pending/in-progress/completed)이 아닐 수도 있으니
        # (예: 정규화 이전에 저장된 한국어 status) 못 찾으면 처음(pending)부터 순환 시작
        current_index = STATUS_CYCLE.index(row["status"]) if row["status"] in STATUS_CYCLE else -1
        next_status = STATUS_CYCLE[(current_index + 1) % len(STATUS_CYCLE)]
        conn.execute(
            "UPDATE action_items SET status = ?, user_modified = 1 WHERE id = ? AND user_id = ?",
            (next_status, item_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": item_id, "status": next_status}


def link_account(
    user_id: int,
    provider: str,
    provider_email: str,
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
):
    """user_id 계정에 외부 소스 신원(provider_email)을 연결(또는 갱신)한다.
    access_token은 검색 시점에 그 사람 권한으로 실시간 접근 확인을 하는 데 쓴다.
    refresh_token은 access_token이 만료되는 소스(GitLab은 기본 2시간, Google은 1시간)에서
    새 access_token을 받아오는 데 쓴다 — 이게 없으면 연동이 조용히 죽는다."""
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO linked_accounts
                (user_id, provider, provider_email, access_token, refresh_token, linked_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, provider) DO UPDATE SET
                provider_email = excluded.provider_email,
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                linked_at = excluded.linked_at
            """,
            (
                user_id, provider, provider_email, access_token, refresh_token,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_linked_refresh_token(user_id: int, provider: str) -> Optional[str]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT refresh_token FROM linked_accounts WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        ).fetchone()
    finally:
        conn.close()
    return row["refresh_token"] if row else None


def update_tokens(user_id: int, provider: str, access_token: str, refresh_token: Optional[str] = None):
    """토큰을 갱신했을 때 저장한다 (다음 요청에서 또 갱신하지 않도록)."""
    conn = get_connection()
    try:
        if refresh_token:
            conn.execute(
                "UPDATE linked_accounts SET access_token = ?, refresh_token = ? WHERE user_id = ? AND provider = ?",
                (access_token, refresh_token, user_id, provider),
            )
        else:
            conn.execute(
                "UPDATE linked_accounts SET access_token = ? WHERE user_id = ? AND provider = ?",
                (access_token, user_id, provider),
            )
        conn.commit()
    finally:
        conn.close()


def unlink_account(user_id: int, provider: str) -> bool:
    """연동을 해제한다. 예전엔 해제 수단이 아예 없어서 잘못 연결한 계정을 되돌릴 수 없었고,
    저장된 토큰이 남아 백그라운드 재동기화가 계속 그 사람 문서를 끌어왔다."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM linked_accounts WHERE user_id = ? AND provider = ?", (user_id, provider)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_linked_email(user_id: int, provider: str) -> Optional[str]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT provider_email FROM linked_accounts WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        ).fetchone()
    finally:
        conn.close()
    return row["provider_email"] if row else None


def get_linked_access_token(user_id: int, provider: str) -> Optional[str]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT access_token FROM linked_accounts WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        ).fetchone()
    finally:
        conn.close()
    return row["access_token"] if row else None


def get_all_accounts_with_tokens(providers: list[str]) -> list[dict]:
    """모든 사용자를 통틀어, 주어진 provider들 중 access_token이 서버에 저장돼 있는 연동을
    전부 반환한다. 백그라운드 주기 재동기화(polling)가 순회할 대상 목록을 만드는 데 쓴다 —
    Google처럼 토큰을 서버에 저장하지 않는 provider는 애초에 access_token이 없어서 여기 안 잡힌다."""
    if not providers:
        return []
    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in providers)
        rows = conn.execute(
            f"""
            SELECT user_id, provider, access_token FROM linked_accounts
            WHERE provider IN ({placeholders}) AND access_token IS NOT NULL
            """,
            providers,
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_linked_accounts(user_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT provider, provider_email, linked_at FROM linked_accounts WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


OAUTH_STATE_TTL_SECONDS = 600  # 연동 팝업은 몇 분 안에 끝나므로 10분이면 충분하다


def create_oauth_state(user_id: int, provider: str) -> str:
    import secrets
    state = secrets.token_urlsafe(24)
    conn = get_connection()
    try:
        # 사용자가 팝업을 그냥 닫으면 state 행이 그대로 남으므로, 만들 때마다 만료분을 같이 치운다
        expired_before = (
            datetime.now(timezone.utc) - timedelta(seconds=OAUTH_STATE_TTL_SECONDS)
        ).isoformat()
        conn.execute("DELETE FROM oauth_states WHERE created_at < ?", (expired_before,))
        conn.execute(
            "INSERT INTO oauth_states (state, user_id, provider, created_at) VALUES (?, ?, ?, ?)",
            (state, user_id, provider, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return state


def consume_oauth_state(state: str) -> Optional[dict]:
    """state를 한 번만 쓸 수 있게 조회 즉시 삭제한다 (재사용/위조 방지).
    만료된 state는 유효하지 않은 것으로 취급한다."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT user_id, provider, created_at FROM oauth_states WHERE state = ?", (state,)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            conn.commit()
    finally:
        conn.close()

    if not row:
        return None
    try:
        created_at = datetime.fromisoformat(row["created_at"])
    except (TypeError, ValueError):
        return None
    if (datetime.now(timezone.utc) - created_at).total_seconds() > OAUTH_STATE_TTL_SECONDS:
        return None
    return {"user_id": row["user_id"], "provider": row["provider"]}
