"""자체 계정 시스템을 위한 로컬 SQLite 저장소.

users: 이메일+비밀번호로 가입하는 우리 사이트 자체 계정.
linked_accounts: 그 계정에 연결된 외부 소스 신원(Google/Slack/GitHub/GitLab/Notion 등).
   Phase 6b(Google)부터 순서대로 채워진다.
search_history / action_items: 브라우저 localStorage가 아니라 계정(user_id)에 귀속되는
   검색 기록·액션아이템. 로그인 없이는 검색 자체가 안 되므로(로그인 필수 전환), 항상
   실제 계정과 연결된 데이터다.
"""

import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

# Render 등 컨테이너 배포 환경에서는 영구 디스크가 코드와 다른 경로에 마운트되므로,
# DB_PATH 환경변수로 그 경로를 가리킬 수 있게 한다 — 안 주면(로컬 개발) 기존과 동일하게
# backend/ 디렉터리 안에 둔다.
DB_PATH = os.getenv("DB_PATH") or os.path.join(os.path.dirname(__file__), "app.db")


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
        if "kind" not in {row["name"] for row in conn.execute("PRAGMA table_info(search_history)")}:
            # 하루 LLM 호출 한도(검색 + 문서 재요약)를 같은 테이블로 공유하기 위해 추가 —
            # 'search'(실제 검색)와 'resummarize'(문서 클릭 재요약)를 구분해서, "최근 검색"/
            # "이번 주 검색" UI는 'search'만 보고 한도 계산만 둘 다 센다. 기존 행은 전부 NULL인데,
            # 이 컬럼이 생기기 전엔 search_history에 검색만 기록됐으므로 NULL은 'search'와 동일하게
            # 취급한다(아래 쿼리들 참고).
            conn.execute("ALTER TABLE search_history ADD COLUMN kind TEXT")
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                aliases TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, display_name),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(created_by) REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS team_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                joined_at TEXT NOT NULL,
                UNIQUE(team_id, user_id),
                FOREIGN KEY(team_id) REFERENCES teams(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS team_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                code TEXT UNIQUE NOT NULL,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(team_id) REFERENCES teams(id),
                FOREIGN KEY(created_by) REFERENCES users(id)
            )
        """)
        # people/action_items를 팀 단위로도 공유할 수 있게 team_id를 추가한다 — NULL이면
        # 지금처럼 개인 스코프, 값이 있으면 그 팀 전체가 공유. teams 테이블이 방금 막
        # 만들어졌을 수 있어 이 뒤에 와야 한다.
        for table in ("people", "action_items"):
            existing_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if "team_id" not in existing_columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN team_id INTEGER REFERENCES teams(id)")

        # people/action_items의 예전 UNIQUE 제약(user_id, display_name)/(user_id, query,
        # source_item_id)은 team_id를 모른다 — 그래서 같은 사용자가 개인 스코프에 등록해둔
        # 이름/할 일을, 어느 팀 스코프에 또 등록하려 하면(team_id는 다른데 나머지 컬럼이
        # 같음) 그 예전 제약에 그대로 걸려 500 에러가 났다(실사용 중 발견 — "송승현"을 개인
        # 사전에 등록해둔 상태에서 팀 사전에도 등록하려다 발생). SQLite는 ALTER TABLE로
        # 기존 제약을 못 없애므로, 제약 없는 새 테이블을 만들어 데이터를 그대로 옮기고
        # 스코프별 부분(partial) UNIQUE 인덱스로 대체한다 — 개인 스코프(team_id IS NULL)와
        # 팀 스코프(team_id IS NOT NULL)를 서로 다른 인덱스로 나눠서, 같은 이름이 서로 다른
        # 스코프에 있는 건 막지 않고 "같은 스코프 안에서만" 중복을 막는다. 이미 마이그레이션
        #됐으면(새 인덱스가 있으면) 건너뛴다.
        existing_indexes = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        if "people_personal_unique" not in existing_indexes:
            conn.execute("ALTER TABLE people RENAME TO people_old")
            conn.execute("""
                CREATE TABLE people (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    display_name TEXT NOT NULL,
                    aliases TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    team_id INTEGER,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(team_id) REFERENCES teams(id)
                )
            """)
            conn.execute(
                "INSERT INTO people (id, user_id, display_name, aliases, created_at, team_id) "
                "SELECT id, user_id, display_name, aliases, created_at, team_id FROM people_old"
            )
            conn.execute("DROP TABLE people_old")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS people_personal_unique "
                "ON people(user_id, display_name) WHERE team_id IS NULL"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS people_team_unique "
                "ON people(team_id, display_name) WHERE team_id IS NOT NULL"
            )

        if "action_items_personal_unique" not in existing_indexes:
            conn.execute("ALTER TABLE action_items RENAME TO action_items_old")
            conn.execute("""
                CREATE TABLE action_items (
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
                    team_id INTEGER,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(team_id) REFERENCES teams(id)
                )
            """)
            conn.execute(
                "INSERT INTO action_items (id, user_id, query, source_item_id, task, assignee, "
                "due_date, status, source, user_modified, saved_at, team_id) "
                "SELECT id, user_id, query, source_item_id, task, assignee, due_date, status, "
                "source, user_modified, saved_at, team_id FROM action_items_old"
            )
            conn.execute("DROP TABLE action_items_old")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS action_items_personal_unique "
                "ON action_items(user_id, query, source_item_id) WHERE team_id IS NULL"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS action_items_team_unique "
                "ON action_items(team_id, query, source_item_id) WHERE team_id IS NOT NULL"
            )

        # workspace_authors: 동기화 때마다 문서 author 이름을 누적 저장한다.
        # 검색 결과에 안 잡힌 문서의 작성자도 LLM 동명이인 정규화 후보로 쓸 수 있게
        # (PRD §7 "워크스페이스 전체 인물 로스터" 오픈 이슈 구현).
        # source: 이 이름이 처음 확인된 소스(notion/slack/gdrive/github/gitlab 등).
        # team_id: NULL이면 인스턴스 전체(워크스페이스) 공유, 값이 있으면 그 팀 한정.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workspace_authors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL,
                team_id INTEGER,
                FOREIGN KEY(team_id) REFERENCES teams(id)
            )
        """)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS workspace_authors_global_unique "
            "ON workspace_authors(name) WHERE team_id IS NULL"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS workspace_authors_name_team_unique "
            "ON workspace_authors(name, team_id) WHERE team_id IS NOT NULL"
        )

        conn.commit()
    finally:
        conn.close()


def record_search(user_id: int, query: str, kind: str = "search"):
    """kind='search'(기본값, 실제 검색)와 'resummarize'(문서 클릭 재요약)를 구분해서 기록한다 —
    "최근 검색"/"이번 주 검색" UI는 'search'만 보여줘야 하고(안 그러면 재요약 클릭이 검색 기록
    처럼 보여 클릭 시 엉뚱한 재검색이 됨), 하루 LLM 호출 한도는 둘 다 세야 한다(비용은 똑같이
    드는데 재요약만 반복하면 한도를 우회할 수 있으므로)."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO search_history (user_id, query, searched_at, kind) VALUES (?, ?, ?, ?)",
            (user_id, query, datetime.now(timezone.utc).isoformat(), kind),
        )
        conn.commit()
    finally:
        conn.close()


def get_search_history(user_id: int, limit: int = 10) -> list[dict]:
    """쿼리별 가장 최근 검색 시각만 남겨서, 최신순으로 최대 limit개 반환한다.
    kind='resummarize'(문서 재요약) 기록은 제외한다 — 컬럼 생기기 전 기존 행은 전부 NULL인데,
    그 시절엔 search_history에 검색만 기록됐으므로 NULL도 'search'로 취급한다."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT query, MAX(searched_at) AS searched_at
            FROM search_history
            WHERE user_id = ? AND (kind IS NULL OR kind = 'search')
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
    """"이번 주 검색" 같은 통계용 — 실제 검색(kind='search')만 센다."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM search_history "
            "WHERE user_id = ? AND searched_at >= ? AND (kind IS NULL OR kind = 'search')",
            (user_id, since_iso),
        ).fetchone()
    finally:
        conn.close()
    return row["c"] if row else 0


def count_llm_calls_since(user_id: int, since_iso: str) -> int:
    """하루 LLM 호출 한도(검색 + 문서 재요약 — 둘 다 OpenAI 비용이 든다) 체크용. kind 구분 없이
    전부 센다는 점이 count_searches_since와의 유일한 차이."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM search_history WHERE user_id = ? AND searched_at >= ?",
            (user_id, since_iso),
        ).fetchone()
    finally:
        conn.close()
    return row["c"] if row else 0


def upsert_action_items(user_id: int, query: str, items: list[dict], team_id: Optional[int] = None):
    """검색마다 AI가 새로 뽑아낸 액션아이템을 저장한다. 사용자가 이미 로컬에서 상태를
    바꿔둔(user_modified) 항목은 같은 (query, source_item_id) 재검색으로 덮어쓰지 않는다.

    team_id가 있으면 팀 전체가 공유하는 행으로 저장한다 — 기존 UNIQUE(user_id, query,
    source_item_id) 제약은 team_id를 모르므로, 팀 스코프에서는 이 제약에 기댄 upsert 대신
    (team_id, query, source_item_id) 기준으로 직접 존재를 확인한다(같은 항목을 팀원 여러
    명이 각자 저장해도 행이 하나만 생기도록)."""
    conn = get_connection()
    try:
        for item in items:
            if team_id is None:
                existing = conn.execute(
                    "SELECT id, task, status, user_modified FROM action_items "
                    "WHERE user_id = ? AND query = ? AND source_item_id = ? AND team_id IS NULL",
                    (user_id, query, item["id"]),
                ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT id, task, status, user_modified FROM action_items "
                    "WHERE team_id = ? AND query = ? AND source_item_id = ?",
                    (team_id, query, item["id"]),
                ).fetchone()

            # source_item_id는 LLM이 매번 새로 붙이는 임시 id("a1")라, 같은 질의를 다시 검색하면
            # 같은 "a1"에 전혀 다른 할 일이 들어올 수 있다. 그때 이전 상태를 물려주면 새 할 일이
            # 이미 "완료"로 표시되므로, **내용이 그대로일 때만** 사용자가 바꾼 상태를 유지한다.
            same_task = bool(existing) and (existing["task"] or "") == item.get("task", "")
            keep_user_status = bool(existing) and existing["user_modified"] and same_task
            status = existing["status"] if keep_user_status else item.get("status", "pending")
            saved_at = datetime.now(timezone.utc).isoformat()

            if existing:
                conn.execute(
                    """
                    UPDATE action_items SET
                        task = ?, assignee = ?, due_date = ?, status = ?, source = ?, saved_at = ?
                    WHERE id = ?
                    """,
                    (
                        item.get("task", ""), item.get("assignee", ""), item.get("dueDate", ""),
                        status, item.get("source", ""), saved_at, existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO action_items
                        (user_id, query, source_item_id, task, assignee, due_date, status, source,
                         user_modified, saved_at, team_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id, query, item["id"], item.get("task", ""), item.get("assignee", ""),
                        item.get("dueDate", ""), status, item.get("source", ""),
                        1 if keep_user_status else 0, saved_at, team_id,
                    ),
                )
        conn.commit()
    finally:
        conn.close()


def get_action_items(user_id: int, team_id: Optional[int] = None) -> list[dict]:
    conn = get_connection()
    try:
        where = "user_id = ? AND team_id IS NULL" if team_id is None else "team_id = ?"
        param = user_id if team_id is None else team_id
        rows = conn.execute(
            f"""
            SELECT id, query, task, assignee, due_date, status, source, saved_at
            FROM action_items
            WHERE {where}
            ORDER BY
                CASE status WHEN 'pending' THEN 0 WHEN 'in-progress' THEN 1 ELSE 2 END,
                saved_at DESC
            """,
            (param,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def delete_action_item(user_id: int, item_id: int, team_id: Optional[int] = None) -> bool:
    """사용자가 직접 할 일을 지운다. 예전엔 지울 방법이 아예 없어서, 한번 뽑힌 항목이
    (잘못 추출된 것이라도) 영원히 목록에 남았다. team_id가 있으면 팀 멤버 누구나 지울 수
    있다(공유 목록이므로 작성자 본인만으로 제한하지 않음)."""
    conn = get_connection()
    try:
        if team_id is None:
            cur = conn.execute(
                "DELETE FROM action_items WHERE id = ? AND user_id = ? AND team_id IS NULL",
                (item_id, user_id),
            )
        else:
            cur = conn.execute(
                "DELETE FROM action_items WHERE id = ? AND team_id = ?", (item_id, team_id)
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def toggle_action_item_status(user_id: int, item_id: int, team_id: Optional[int] = None) -> Optional[dict]:
    """완료 여부만 토글하는 체크박스형 — 예전엔 대기→진행중→완료로 순환해서 "완료로 바로
    체크"가 안 됐다(세 번 눌러야 완료). in-progress는 여전히 유효한 값이지만(LLM이 문맥상
    이미 진행 중이라고 추론한 경우 등) 사용자가 클릭으로 거쳐가는 중간 단계는 아니다 —
    완료가 아니면 무조건 완료로, 완료면 대기로 되돌린다. team_id가 있으면 팀 멤버 누구나
    토글할 수 있다(공유 목록)."""
    conn = get_connection()
    try:
        if team_id is None:
            row = conn.execute(
                "SELECT status FROM action_items WHERE id = ? AND user_id = ? AND team_id IS NULL",
                (item_id, user_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT status FROM action_items WHERE id = ? AND team_id = ?", (item_id, team_id)
            ).fetchone()
        if not row:
            return None
        next_status = "pending" if row["status"] == "completed" else "completed"
        conn.execute(
            "UPDATE action_items SET status = ?, user_modified = 1 WHERE id = ?",
            (next_status, item_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": item_id, "status": next_status}


def _person_row_to_dict(row) -> dict:
    d = dict(row)
    d["aliases"] = [a for a in (d["aliases"] or "").split(",") if a]
    return d


def create_person(user_id: int, display_name: str, aliases: list[str], team_id: Optional[int] = None) -> dict:
    conn = get_connection()
    try:
        now = datetime.utcnow().isoformat()
        if team_id is None:
            # 개인 스코프 — people_personal_unique(부분 인덱스)를 겨냥한 upsert. 부분
            # 인덱스를 타겟할 땐 ON CONFLICT에도 같은 WHERE를 넣어야 SQLite가 정확히
            # 이 인덱스를 고른다(안 그러면 "해당하는 제약을 못 찾음" 오류가 난다).
            conn.execute(
                """
                INSERT INTO people (user_id, display_name, aliases, created_at, team_id)
                VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(user_id, display_name) WHERE team_id IS NULL DO UPDATE SET
                    aliases = excluded.aliases
                """,
                (user_id, display_name, ",".join(aliases), now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id, display_name, aliases, created_at FROM people "
                "WHERE user_id = ? AND display_name = ? AND team_id IS NULL",
                (user_id, display_name),
            ).fetchone()
        else:
            # 팀 스코프 — team_id는 기존 UNIQUE 제약에 안 들어가 있으므로 upsert 대신
            # 직접 존재 확인 후 갱신/삽입한다(중복 이름은 애플리케이션 레벨에서만 방지).
            existing = conn.execute(
                "SELECT id FROM people WHERE team_id = ? AND display_name = ?",
                (team_id, display_name),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE people SET aliases = ? WHERE id = ?",
                    (",".join(aliases), existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO people (user_id, display_name, aliases, created_at, team_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, display_name, ",".join(aliases), now, team_id),
                )
            conn.commit()
            row = conn.execute(
                "SELECT id, display_name, aliases, created_at FROM people "
                "WHERE team_id = ? AND display_name = ?",
                (team_id, display_name),
            ).fetchone()
    finally:
        conn.close()
    return _person_row_to_dict(row)


def get_people(user_id: int, team_id: Optional[int] = None) -> list[dict]:
    conn = get_connection()
    try:
        if team_id is None:
            rows = conn.execute(
                "SELECT id, display_name, aliases, created_at FROM people "
                "WHERE user_id = ? AND team_id IS NULL ORDER BY created_at",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, display_name, aliases, created_at FROM people "
                "WHERE team_id = ? ORDER BY created_at",
                (team_id,),
            ).fetchall()
    finally:
        conn.close()
    return [_person_row_to_dict(r) for r in rows]


def update_person(
    user_id: int, person_id: int, display_name: str, aliases: list[str], team_id: Optional[int] = None
) -> Optional[dict]:
    conn = get_connection()
    try:
        if team_id is None:
            cur = conn.execute(
                "UPDATE people SET display_name = ?, aliases = ? WHERE id = ? AND user_id = ? AND team_id IS NULL",
                (display_name, ",".join(aliases), person_id, user_id),
            )
        else:
            cur = conn.execute(
                "UPDATE people SET display_name = ?, aliases = ? WHERE id = ? AND team_id = ?",
                (display_name, ",".join(aliases), person_id, team_id),
            )
        if cur.rowcount == 0:
            return None
        conn.commit()
        row = conn.execute(
            "SELECT id, display_name, aliases, created_at FROM people WHERE id = ?",
            (person_id,),
        ).fetchone()
    finally:
        conn.close()
    return _person_row_to_dict(row) if row else None


def delete_person(user_id: int, person_id: int, team_id: Optional[int] = None) -> bool:
    conn = get_connection()
    try:
        if team_id is None:
            cur = conn.execute(
                "DELETE FROM people WHERE id = ? AND user_id = ? AND team_id IS NULL", (person_id, user_id)
            )
        else:
            cur = conn.execute(
                "DELETE FROM people WHERE id = ? AND team_id = ?", (person_id, team_id)
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def create_team(user_id: int, name: str) -> dict:
    """팀을 만들고, 만든 사람을 곧바로 owner로 등록한다(같은 트랜잭션)."""
    conn = get_connection()
    try:
        now = datetime.utcnow().isoformat()
        cur = conn.execute(
            "INSERT INTO teams (name, created_by, created_at) VALUES (?, ?, ?)",
            (name, user_id, now),
        )
        team_id = cur.lastrowid
        conn.execute(
            "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
            (team_id, user_id, now),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": team_id, "name": name, "role": "owner", "createdAt": now}


def get_teams_for_user(user_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT teams.id, teams.name, teams.created_at, team_members.role
            FROM team_members
            JOIN teams ON teams.id = team_members.team_id
            WHERE team_members.user_id = ?
            ORDER BY team_members.joined_at
            """,
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"id": r["id"], "name": r["name"], "role": r["role"], "createdAt": r["created_at"]}
        for r in rows
    ]


def create_team_invite(team_id: int, created_by: int) -> dict:
    conn = get_connection()
    try:
        code = secrets.token_urlsafe(12)
        now = datetime.utcnow().isoformat()
        conn.execute(
            "INSERT INTO team_invites (team_id, code, created_by, created_at) VALUES (?, ?, ?, ?)",
            (team_id, code, created_by, now),
        )
        conn.commit()
    finally:
        conn.close()
    return {"code": code}


def get_team_by_invite_code(code: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT teams.id, teams.name, teams.created_at
            FROM team_invites
            JOIN teams ON teams.id = team_invites.team_id
            WHERE team_invites.code = ?
            """,
            (code,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"id": row["id"], "name": row["name"], "createdAt": row["created_at"]}


def join_team(user_id: int, team_id: int) -> dict:
    """이미 멤버면 그대로 두고(에러 안 냄), 아니면 member로 새로 등록한다."""
    conn = get_connection()
    try:
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO team_members (team_id, user_id, role, joined_at)
            VALUES (?, ?, 'member', ?)
            ON CONFLICT(team_id, user_id) DO NOTHING
            """,
            (team_id, user_id, now),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT teams.id, teams.name, teams.created_at, team_members.role
            FROM team_members
            JOIN teams ON teams.id = team_members.team_id
            WHERE team_members.team_id = ? AND team_members.user_id = ?
            """,
            (team_id, user_id),
        ).fetchone()
    finally:
        conn.close()
    return {"id": row["id"], "name": row["name"], "role": row["role"], "createdAt": row["created_at"]}


def get_team_members(team_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT users.id AS user_id, users.email, team_members.role, team_members.joined_at
            FROM team_members
            JOIN users ON users.id = team_members.user_id
            WHERE team_members.team_id = ?
            ORDER BY team_members.joined_at
            """,
            (team_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"userId": r["user_id"], "email": r["email"], "role": r["role"], "joinedAt": r["joined_at"]}
        for r in rows
    ]


def is_team_member(team_id: int, user_id: int) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM team_members WHERE team_id = ? AND user_id = ?", (team_id, user_id)
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def is_team_owner(team_id: int, user_id: int) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM team_members WHERE team_id = ? AND user_id = ? AND role = 'owner'",
            (team_id, user_id),
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def remove_team_member(team_id: int, user_id: int) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM team_members WHERE team_id = ? AND user_id = ?", (team_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


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


# ---------------------------------------------------------------------------
# workspace_authors — 동기화 시 누적되는 워크스페이스 전체 인물 로스터
# ---------------------------------------------------------------------------

def upsert_workspace_authors(names: list[str], source: str, team_id: Optional[int] = None) -> int:
    """name 목록을 workspace_authors에 없는 것만 INSERT한다(이미 있으면 무시).

    team_id=None이면 인스턴스 전체(워크스페이스) 공유 로스터에 적재하고,
    team_id가 있으면 그 팀 한정 로스터에 적재한다.
    반환값은 실제로 새로 추가된 행 수.
    """
    if not names:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    conn = get_connection()
    try:
        for name in names:
            name = name.strip()
            if not name or name == "알 수 없음":
                continue
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO workspace_authors (name, source, first_seen_at, team_id) "
                    "VALUES (?, ?, ?, ?)",
                    (name, source, now, team_id),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    inserted += 1
            except Exception:
                pass  # 개별 이름 삽입 실패가 전체 수집을 막지 않도록
        conn.commit()
    finally:
        conn.close()
    return inserted


def get_workspace_authors(team_id: Optional[int] = None) -> list[str]:
    """워크스페이스(또는 팀) 전체 인물 로스터에서 이름 목록을 반환한다.

    team_id=None이면 전역(team_id IS NULL) 로스터를 반환하고,
    team_id가 있으면 그 팀 로스터와 전역 로스터를 합쳐서 반환한다
    (팀 멤버가 아닌 소스에서 동기화된 이름도 후보가 되어야 하기 때문).
    이름은 알파벳/가나다 순으로 정렬돼 반환된다.
    """
    conn = get_connection()
    try:
        if team_id is None:
            rows = conn.execute(
                "SELECT DISTINCT name FROM workspace_authors WHERE team_id IS NULL ORDER BY name"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT name FROM workspace_authors "
                "WHERE team_id IS NULL OR team_id = ? ORDER BY name",
                (team_id,),
            ).fetchall()
        return [row["name"] for row in rows]
    finally:
        conn.close()
