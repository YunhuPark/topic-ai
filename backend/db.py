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
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
        # linked_accounts가 access_token 컬럼 없이 이미 만들어져 있던 경우를 위한 마이그레이션
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(linked_accounts)")}
        if "access_token" not in existing_columns:
            conn.execute("ALTER TABLE linked_accounts ADD COLUMN access_token TEXT")
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
                "SELECT status, user_modified FROM action_items WHERE user_id = ? AND query = ? AND source_item_id = ?",
                (user_id, query, item["id"]),
            ).fetchone()
            status = existing["status"] if existing and existing["user_modified"] else item.get("status", "pending")
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
                    1 if (existing and existing["user_modified"]) else 0,
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


def link_account(user_id: int, provider: str, provider_email: str, access_token: Optional[str] = None):
    """user_id 계정에 외부 소스 신원(provider_email)을 연결(또는 갱신)한다.
    access_token을 주면 검색 시점에 그 사람 권한으로 실시간 접근 확인을 하는 데 쓴다
    (Google은 토큰 수명이 짧아 세션마다 프론트에서 새로 받고, GitHub/GitLab처럼 토큰이
    오래 유지되는 곳은 여기 저장해뒀다가 서버가 바로 쓴다)."""
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO linked_accounts (user_id, provider, provider_email, access_token, linked_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, provider) DO UPDATE SET
                provider_email = excluded.provider_email,
                access_token = excluded.access_token,
                linked_at = excluded.linked_at
            """,
            (user_id, provider, provider_email, access_token, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
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


def create_oauth_state(user_id: int, provider: str) -> str:
    import secrets
    state = secrets.token_urlsafe(24)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO oauth_states (state, user_id, provider, created_at) VALUES (?, ?, ?, ?)",
            (state, user_id, provider, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return state


def consume_oauth_state(state: str) -> Optional[dict]:
    """state를 한 번만 쓸 수 있게 조회 즉시 삭제한다 (재사용/위조 방지)."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT user_id, provider FROM oauth_states WHERE state = ?", (state,)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            conn.commit()
    finally:
        conn.close()
    return dict(row) if row else None
