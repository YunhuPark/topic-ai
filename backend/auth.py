"""자체 로그인(이메일+비밀번호) 시스템. 세션은 우리가 직접 서명하는 JWT로 유지한다.

Phase 6a: 회원가입/로그인/세션 검증
Phase 6b: 로그인한 계정에 Google 신원을 연결(link_google_account)해서 권한 인지형 검색에 사용
"""

import base64
import os
import re
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
import requests as http_requests
from dotenv import load_dotenv

import db
from db import get_connection

load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    # 예전엔 기본값으로 조용히 넘어갔는데, 그 상태로 배포되면 누구나 아무 user_id로 세션을
    # 위조할 수 있다. 설정이 빠졌으면 기동 자체를 막는다.
    raise RuntimeError(
        "JWT_SECRET이 설정되지 않았습니다. backend/.env에 임의의 긴 문자열을 넣어주세요 "
        '(예: python -c "import secrets; print(secrets.token_hex(32))").'
    )
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_DAYS = 7

# 로그인 무차별 대입 방어 — 같은 이메일에 대해 연속 실패가 쌓이면 잠시 잠근다.
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300
_login_attempts: dict[str, tuple[int, float]] = {}
_login_attempts_lock = threading.Lock()
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

GITLAB_URL = os.getenv("GITLAB_URL", "https://gitlab.com").rstrip("/")

# GitHub/GitLab은 둘 다 "클라이언트 시크릿이 필요한 표준 OAuth Authorization Code" 플로우라
# (Google Identity Services 같은 클라이언트 전용 플로우가 없음) 하나의 일반화된 흐름으로 처리한다.
OAUTH_PROVIDERS = {
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "user_url": "https://api.github.com/user",
        "scope": "repo read:user",
        "client_id": os.getenv("GITHUB_OAUTH_CLIENT_ID"),
        "client_secret": os.getenv("GITHUB_OAUTH_CLIENT_SECRET"),
        "redirect_uri": os.getenv(
            "GITHUB_OAUTH_REDIRECT_URI", "http://localhost:8000/api/v1/auth/link/github/callback"
        ),
        "extra_headers": {"Accept": "application/vnd.github+json"},
        "login_field": "login",
    },
    "gitlab": {
        "authorize_url": f"{GITLAB_URL}/oauth/authorize",
        "token_url": f"{GITLAB_URL}/oauth/token",
        "user_url": f"{GITLAB_URL}/api/v4/user",
        "scope": "read_api",
        "client_id": os.getenv("GITLAB_OAUTH_CLIENT_ID"),
        "client_secret": os.getenv("GITLAB_OAUTH_CLIENT_SECRET"),
        "redirect_uri": os.getenv(
            "GITLAB_OAUTH_REDIRECT_URI", "http://localhost:8000/api/v1/auth/link/gitlab/callback"
        ),
        "extra_headers": {},
        "login_field": "username",
    },
}


SLACK_OAUTH_CLIENT_ID = os.getenv("SLACK_OAUTH_CLIENT_ID")
SLACK_OAUTH_CLIENT_SECRET = os.getenv("SLACK_OAUTH_CLIENT_SECRET")
SLACK_OAUTH_REDIRECT_URI = os.getenv(
    "SLACK_OAUTH_REDIRECT_URI", "http://localhost:8000/api/v1/auth/link/slack/callback"
)
# 채널 접근 권한 확인(conversations.history)과, 계정 연동 시점의 자동 수집(채널 목록/대화 내역/
# 작성자 이름 조회)에 쓸 "사용자 토큰" 스코프. 봇 토큰(SLACK_BOT_TOKEN, 수집용)과 별개로,
# 로그인한 사람 본인 권한을 나타내는 토큰을 받는다.
SLACK_USER_SCOPE = "channels:history,groups:history,channels:read,groups:read,users:read"

NOTION_OAUTH_CLIENT_ID = os.getenv("NOTION_OAUTH_CLIENT_ID")
NOTION_OAUTH_CLIENT_SECRET = os.getenv("NOTION_OAUTH_CLIENT_SECRET")
NOTION_OAUTH_REDIRECT_URI = os.getenv(
    "NOTION_OAUTH_REDIRECT_URI", "http://localhost:8000/api/v1/auth/link/notion/callback"
)


def _oauth_config(provider: str) -> dict:
    config = OAUTH_PROVIDERS[provider]
    placeholder_id = f"your_{provider}_oauth_client_id_here"
    placeholder_secret = f"your_{provider}_oauth_client_secret_here"
    if not config["client_id"] or config["client_id"] == placeholder_id:
        raise AuthError(f"{provider.upper()}_OAUTH_CLIENT_ID가 설정되지 않았습니다. backend/.env를 확인하세요.")
    if not config["client_secret"] or config["client_secret"] == placeholder_secret:
        raise AuthError(f"{provider.upper()}_OAUTH_CLIENT_SECRET이 설정되지 않았습니다. backend/.env를 확인하세요.")
    return config

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    """가입/로그인 실패를 사용자에게 보여줄 메시지와 함께 표현한다."""


def _sync_after_link(provider: str, stored_token: str, user_id: int) -> Optional[int]:
    """계정 연결 직후, 그 사람 본인 토큰으로 접근 가능한 문서 전체를 즉시 수집해 적재한다.
    (계정 연동이 곧 "그 사이트의 내 문서 전부 검색 가능"으로 이어지도록 하는 부분 — 이걸 안 하면
    연동해도 검색 결과는 관리자가 .env로 미리 적재해둔 것만 보이게 된다.)
    수집 실패는 연결 자체를 실패시키지 않는다 — 연결은 됐지만 이번 동기화만 실패한 것으로 취급하고,
    다음 검색 때 이미 적재된 다른 소스 결과는 그대로 보여준다."""
    try:
        # google은 linked_accounts에 refresh_token을 저장해두고(만료 없이 오래 씀), 실제
        # Drive API 호출에 쓸 짧은 수명 access_token은 그때그때 새로 발급받아야 한다.
        access_token = refresh_google_access_token(stored_token) if provider == "google" else stored_token
        import rag_pipeline
        return rag_pipeline.sync_documents_for_user(provider, access_token, user_id=user_id)
    except Exception as e:
        print(f"{provider} 문서 동기화 실패: {e}")
        return None


def _sync_after_link_background(provider: str, stored_token: str, user_id: int) -> None:
    """_sync_after_link를 백그라운드 스레드에서 돌린다 — 문서가 많으면(예: 저장소 100개대
    GitHub 계정, 시트 수십 개짜리 Google Drive에서 분당 요청 한도에 걸려 재시도까지 겹치면)
    전체 수집에 몇 분씩 걸릴 수 있는데, 이걸 계정 연결 응답(OAuth 팝업)에서 동기로 기다리게
    하면 그동안 팝업이 그대로 멈춰 있는 것처럼 보인다. 그래서 연결 자체는 즉시 완료 처리하고,
    수집은 뒤에서 계속 진행해 다음 검색 때 자연스럽게 반영되게 한다."""
    def _run():
        count = _sync_after_link(provider, stored_token, user_id)
        if count is not None:
            print(f"[연동 직후 백그라운드 동기화 완료] user_id={user_id} provider={provider} 문서 {count}개")

    threading.Thread(target=_run, daemon=True).start()


def _signup_allowed_domains() -> set[str]:
    raw = os.getenv("SIGNUP_ALLOWED_DOMAINS", "")
    return {d.strip().lower().lstrip("@") for d in raw.split(",") if d.strip()}


def _check_signup_domain(email: str) -> None:
    """SIGNUP_ALLOWED_DOMAINS(.env, 콤마로 여러 개)가 설정돼 있으면 그 도메인의 이메일만
    가입을 허용한다. 설정 안 하면(기본값) 예전처럼 아무 이메일이나 가입 가능 — 사내 배포
    전에는 꼭 설정할 것을 권장하지만, 로컬 개발/테스트 흐름을 막지 않도록 기본은 무제한이다."""
    allowed = _signup_allowed_domains()
    if not allowed:
        return
    domain = email.rsplit("@", 1)[-1]
    if domain not in allowed:
        raise AuthError(f"{', '.join(sorted(allowed))} 도메인 이메일만 가입할 수 있습니다.")


def signup(email: str, password: str) -> tuple[str, str]:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("올바른 이메일 형식이 아닙니다.")
    if len(password) < 8:
        raise AuthError("비밀번호는 8자 이상이어야 합니다.")
    _check_signup_domain(email)

    conn = get_connection()
    try:
        if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            raise AuthError("이미 가입된 이메일입니다.")
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, password_hash, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        user_id = cur.lastrowid
    finally:
        conn.close()

    return _issue_token(user_id, email), email


# ── Google 로그인(앱 자체 인증) ──────────────────────────────────────────
# 아래 "Google Drive 연결"(link_google_account, GOOGLE_OAUTH_REDIRECT_URI)과는 완전히 별개다 —
# 저건 이미 로그인한 계정에 Drive 읽기 권한을 추가로 붙이는 것이고, 이건 애초에 로그인 자체를
# 이메일+비밀번호 대신 Google 계정으로 하는 것이다. 같은 Google OAuth 클라이언트(ID/시크릿)를
# 재사용하되, 콜백 경로와 스코프(openid email만 — Drive 접근 범위 없음)를 분리해서 "로그인하려고
# 눌렀는데 Drive 접근까지 한꺼번에 동의하라고 뜨는" 과한 동의 요청을 피한다.
GOOGLE_LOGIN_REDIRECT_URI = os.getenv(
    "GOOGLE_LOGIN_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback"
)
GOOGLE_LOGIN_SCOPE = "openid email"


def get_google_login_authorize_url() -> str:
    """로그인 흐름엔 아직 로그인된 계정이 없어 user_id가 없다 — 기존 oauth_states가
    user_id를 요구하므로(FK 제약은 있지만 SQLite가 기본적으로 강제하지 않음) 0을
    "아직 user_id 없음"을 나타내는 sentinel로 쓴다. provider 값도 "google_login"으로 구분해서
    기존 Drive 연결(state.provider == "google")과 섞이지 않게 한다."""
    client_id, _ = _google_oauth_config()
    state = db.create_oauth_state(0, "google_login")
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": GOOGLE_LOGIN_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_LOGIN_SCOPE,
        "state": state,
    })
    return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"


def _get_or_create_google_user(email: str) -> int:
    """이메일이 이미 가입돼 있으면(이메일+비밀번호로 가입했던 계정이라도) 그 계정으로 로그인시킨다
    — 같은 이메일이면 같은 사람으로 취급. 처음 보는 이메일이면 새로 만드는데, password_hash가
    NOT NULL이라 비워둘 수 없어서 어떤 실제 비밀번호로도 절대 못 맞는 랜덤 해시를 채워 넣는다
    (스키마 변경 없이 "비밀번호 로그인 경로를 막는다"는 의도를 표현하는 방법 — bcrypt.checkpw가
    이 해시와는 무슨 비밀번호를 넣어도 항상 False를 반환한다).

    신규 계정을 만들 때만 _check_signup_domain을 거친다(signup()과 동일한 원칙) — 안 그러면
    SIGNUP_ALLOWED_DOMAINS를 설정해도 개인 Gmail로 소셜 로그인해서 그냥 우회해버릴 수 있다.
    이미 만들어진 계정은 나중에 제한이 켜져도 계속 로그인 가능(기존 이메일+비밀번호 로그인과
    동일한 동작 — signup()에서만 체크하고 login()에서는 안 함)."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            return row["id"]
        _check_signup_domain(email)
        unusable_hash = bcrypt.hashpw(os.urandom(32), bcrypt.gensalt()).decode("utf-8")
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, unusable_hash, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def complete_google_login(code: str, state: str) -> dict:
    """콜백에서 code+state를 받아 로그인(또는 최초라면 가입)을 완료하고 우리 JWT를 발급한다.
    실패해도 예외 대신 dict로 반환한다 — 콜백 응답은 항상 postMessage용 HTML을 그려야 해서
    (팝업 창이므로) 성공/실패 어느 쪽이든 화면을 보여줘야 하기 때문."""
    pending = db.consume_oauth_state(state)
    if not pending or pending["provider"] != "google_login":
        return {"ok": False, "error": "유효하지 않거나 만료된 로그인 요청입니다."}

    try:
        client_id, client_secret = _google_oauth_config()
    except AuthError as e:
        return {"ok": False, "error": str(e)}

    token_resp = http_requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": GOOGLE_LOGIN_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    token_data = token_resp.json() if token_resp.ok else {}
    access_token = token_data.get("access_token")
    if not access_token:
        return {"ok": False, "error": token_data.get("error_description", "Google 로그인에 실패했습니다.")}

    resp = http_requests.get(
        GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=10
    )
    if resp.status_code != 200:
        return {"ok": False, "error": "Google 사용자 정보를 가져오지 못했습니다."}
    info = resp.json()
    email = info.get("email")
    if not email:
        return {"ok": False, "error": "Google 계정에서 이메일을 가져오지 못했습니다."}
    # Google이 이메일 미인증 계정에도 email 필드를 내려줄 수 있어서 명시적으로 확인한다 —
    # 여기서 자동 가입되는 계정은 비밀번호 검증이 아예 없는 만큼, 최소한 이메일 소유는
    # Google이 보증한 것이어야 한다.
    if info.get("email_verified") is False:
        return {"ok": False, "error": "Google 계정의 이메일이 아직 인증되지 않았습니다."}
    email = email.strip().lower()

    try:
        user_id = _get_or_create_google_user(email)
    except AuthError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "token": _issue_token(user_id, email), "email": email}


# ── 카카오 로그인(앱 자체 인증) ─────────────────────────────────────────
# Google 로그인과 같은 역할(이메일+비밀번호 대신 소셜 계정으로 로그인)이지만, 카카오는
# 이메일 동의항목이 "비즈 앱 전환" 없이는 막혀 있을 수 있어 이메일을 아예 못 받는 경우가
# 흔하다 — 그래서 이메일이 아니라 카카오 고유 숫자 id를 진짜 식별자로 쓴다. 이메일을 받으면
# 그 이메일로, 못 받으면 "kakao-{id}@no-email.topicthread.local" 형태의 가짜(수신 불가)
# 이메일로 계정을 만든다 — users.email UNIQUE 제약을 그대로 쓰면서도 이메일 동의 여부와
# 무관하게 항상 동작하게 하기 위함(스키마 변경 없음, Google 로그인의 "비밀번호 해시 무효화"
# 트릭과 같은 결의 우회).
KAKAO_CLIENT_ID = os.getenv("KAKAO_CLIENT_ID")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET")
KAKAO_LOGIN_REDIRECT_URI = os.getenv(
    "KAKAO_LOGIN_REDIRECT_URI", "http://localhost:8000/api/v1/auth/kakao/callback"
)


def _kakao_oauth_config() -> tuple[str, str]:
    if not KAKAO_CLIENT_ID or KAKAO_CLIENT_ID == "your_kakao_client_id_here":
        raise AuthError("KAKAO_CLIENT_ID가 설정되지 않았습니다. backend/.env를 확인하세요.")
    # Client Secret은 카카오 콘솔에서 선택 사항(비활성화도 가능)이라 비어 있어도 그냥 넘어간다 —
    # 콘솔에서 활성화해놓고 안 보내면 카카오가 토큰 발급을 거부하므로, 값이 있으면 항상 같이 보낸다.
    return KAKAO_CLIENT_ID, KAKAO_CLIENT_SECRET or ""


def get_kakao_login_authorize_url() -> str:
    client_id, _ = _kakao_oauth_config()
    state = db.create_oauth_state(0, "kakao_login")
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": KAKAO_LOGIN_REDIRECT_URI,
        "response_type": "code",
        "state": state,
    })
    return f"https://kauth.kakao.com/oauth/authorize?{params}"


def _get_or_create_kakao_user(kakao_id: int, email: Optional[str]) -> int:
    """이 카카오 id로 이미 로그인한 적 있으면(placeholder 이메일로 만들어둔 계정 포함) 그
    계정을 그대로 쓴다. 처음이면 새로 만드는데, 이번에 진짜 이메일 동의를 받았고 그 이메일로
    이미 가입된 계정(예: 일반 회원가입)이 있다면 새로 만들지 않고 거기로 합류시킨다 —
    placeholder 이메일은 다른 가입 경로와 절대 겹치지 않으므로 이 분기는 진짜 이메일을 받은
    경우에만 의미가 있다.

    신규 계정 생성 시에만 도메인 제한을 적용한다(Google과 동일한 원칙) — 진짜 이메일이 있으면
    그 도메인을 검사하고, 없으면(placeholder로 갈 상황) 도메인 제한이 켜져 있는 한 아예 거부한다.
    카카오 개인 계정은 회사 소속을 증명할 방법이 구조적으로 없어서, 이메일 동의조차 못 받은
    상태로는 "회사 이메일만 가입 가능"이라는 제약을 지킬 수가 없기 때문이다."""
    placeholder_email = f"kakao-{kakao_id}@no-email.topicthread.local"
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (placeholder_email,)).fetchone()
        if row:
            return row["id"]
        if email:
            row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if row:
                return row["id"]
        if email:
            _check_signup_domain(email)
        elif _signup_allowed_domains():
            raise AuthError(
                "도메인 제한이 설정된 상태라, 카카오 계정의 이메일 동의가 필요합니다. "
                "이메일+비밀번호로 가입하거나 Google로 로그인해 주세요."
            )
        unusable_hash = bcrypt.hashpw(os.urandom(32), bcrypt.gensalt()).decode("utf-8")
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email or placeholder_email, unusable_hash, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def complete_kakao_login(code: str, state: str) -> dict:
    pending = db.consume_oauth_state(state)
    if not pending or pending["provider"] != "kakao_login":
        return {"ok": False, "error": "유효하지 않거나 만료된 로그인 요청입니다."}

    try:
        client_id, client_secret = _kakao_oauth_config()
    except AuthError as e:
        return {"ok": False, "error": str(e)}

    token_req_data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": KAKAO_LOGIN_REDIRECT_URI,
        "code": code,
    }
    if client_secret:
        token_req_data["client_secret"] = client_secret
    token_resp = http_requests.post(
        "https://kauth.kakao.com/oauth/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=token_req_data,
        timeout=10,
    )
    token_data = token_resp.json() if token_resp.ok else {}
    access_token = token_data.get("access_token")
    if not access_token:
        return {"ok": False, "error": token_data.get("error_description", "카카오 로그인에 실패했습니다.")}

    resp = http_requests.get(
        "https://kapi.kakao.com/v2/user/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        return {"ok": False, "error": "카카오 사용자 정보를 가져오지 못했습니다."}
    info = resp.json()
    kakao_id = info.get("id")
    if not kakao_id:
        return {"ok": False, "error": "카카오 계정 식별에 실패했습니다."}

    kakao_account = info.get("kakao_account") or {}
    email = kakao_account.get("email")
    # 이메일 동의는 받았지만 인증되지 않은 이메일(드묾)은 신뢰하지 않는다.
    if email and kakao_account.get("is_email_verified") is False:
        email = None

    try:
        user_id = _get_or_create_kakao_user(kakao_id, email)
    except AuthError as e:
        return {"ok": False, "error": str(e)}
    final_email = email or f"kakao-{kakao_id}@no-email.topicthread.local"
    return {"ok": True, "token": _issue_token(user_id, final_email), "email": final_email}


def _check_login_lockout(email: str) -> None:
    with _login_attempts_lock:
        attempts, locked_until = _login_attempts.get(email, (0, 0.0))
        if locked_until > time.time():
            remaining = int(locked_until - time.time())
            raise AuthError(f"로그인 시도가 너무 많습니다. {remaining}초 후에 다시 시도해 주세요.")


def _record_login_failure(email: str) -> None:
    with _login_attempts_lock:
        attempts, _ = _login_attempts.get(email, (0, 0.0))
        attempts += 1
        locked_until = time.time() + LOGIN_LOCKOUT_SECONDS if attempts >= LOGIN_MAX_ATTEMPTS else 0.0
        _login_attempts[email] = (0 if locked_until else attempts, locked_until)


def _clear_login_failures(email: str) -> None:
    with _login_attempts_lock:
        _login_attempts.pop(email, None)


def login(email: str, password: str) -> tuple[str, str]:
    email = email.strip().lower()
    _check_login_lockout(email)

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()

    if not row or not bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8")):
        _record_login_failure(email)
        raise AuthError("이메일 또는 비밀번호가 올바르지 않습니다.")

    _clear_login_failures(email)
    return _issue_token(row["id"], email), email


def _issue_token(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),  # JWT 스펙상 sub는 문자열이어야 함
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRES_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


def get_current_user(authorization: Optional[str]) -> Optional[dict]:
    """`Authorization: Bearer <token>` 헤더에서 로그인 사용자 정보를 추출한다. 없거나 무효하면 None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = verify_token(authorization[len("Bearer "):])
    if not payload:
        return None
    return {"id": int(payload["sub"]), "email": payload["email"]}


def _google_oauth_config() -> tuple[str, str]:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or client_id == "your_google_oauth_client_id_here":
        raise AuthError("GOOGLE_OAUTH_CLIENT_ID가 설정되지 않았습니다. backend/.env를 확인하세요.")
    if not client_secret or client_secret == "your_google_oauth_client_secret_here":
        raise AuthError("GOOGLE_OAUTH_CLIENT_SECRET이 설정되지 않았습니다. backend/.env를 확인하세요.")
    return client_id, client_secret


GOOGLE_OAUTH_REDIRECT_URI = os.getenv(
    "GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/api/v1/auth/link/google/callback"
)
# drive.readonly만으로 Drive API + Sheets API 문서 읽기가 다 된다 (gdrive_connector.py 참고).
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly openid email"


def get_google_authorize_url(user_id: int) -> str:
    """Google도 GitHub/GitLab처럼 서버 사이드 Authorization Code 플로우로 전환했다 (예전엔
    프론트가 Google Identity Services로 짧은 수명 access token만 받아써서, 세션이 끝나면
    매번 "Drive 접근 다시 허용"을 눌러야 했고 서버 쪽 백그라운드 재동기화도 불가능했다).
    access_type=offline + prompt=consent로 요청해야 refresh_token을 받을 수 있다 — refresh_token은
    (재동의 없이는) 최초 연결 때 한 번만 내려오므로 매번 강제로 동의 화면을 다시 띄운다."""
    client_id, _ = _google_oauth_config()
    state = db.create_oauth_state(user_id, "google")
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_DRIVE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"


def refresh_google_access_token(refresh_token: str) -> str:
    """서버에 저장해둔 refresh_token으로 Drive API 호출에 쓸 짧은 수명의 access_token을 새로 발급받는다.
    검색 시점 권한 확인, 백그라운드 자동 재동기화 둘 다 여기를 거친다."""
    resp = http_requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=10,
    )
    data = resp.json() if resp.ok else {}
    access_token = data.get("access_token")
    if not access_token:
        raise AuthError("Google access token 갱신에 실패했습니다. 다시 연결해 주세요.")
    return access_token


def complete_google_link(code: str, state: str) -> dict:
    """콜백에서 code+state를 받아 계정을 연결한다. refresh_token을 linked_accounts.access_token에
    저장해두고(이름은 access_token이지만 실제로는 갱신용 refresh_token — GitHub/GitLab의 "오래 유지되는
    토큰을 서버에 저장" 패턴과 같은 컬럼을 재사용), 검색/자동 재동기화 때마다 그걸로 진짜 access_token을
    새로 발급받아 쓴다."""
    pending = db.consume_oauth_state(state)
    if not pending or pending["provider"] != "google":
        return {"ok": False, "error": "유효하지 않거나 만료된 연결 요청입니다."}

    try:
        client_id, client_secret = _google_oauth_config()
    except AuthError as e:
        return {"ok": False, "error": str(e)}

    token_resp = http_requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    token_data = token_resp.json() if token_resp.ok else {}
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    if not access_token:
        return {"ok": False, "error": token_data.get("error_description", "Google 토큰 발급에 실패했습니다.")}
    if not refresh_token:
        # 이미 한 번 연결한 적 있는 계정이 재동의 화면에서 다시 "허용"만 누르고 실제로는 새
        # refresh_token을 못 받는 경우가 드물게 있다 (prompt=consent를 강제해도 Google 쪽 캐시로
        # 인해 발생 가능) — 기존에 저장된 refresh_token이 있으면 그걸 계속 쓰고, 없으면 실패 처리.
        existing = db.get_linked_access_token(pending["user_id"], "google")
        if not existing:
            return {
                "ok": False,
                "error": "Google이 refresh token을 내려주지 않았습니다. Google 계정 설정에서 이 앱의 연결을 해제한 뒤 다시 시도해 주세요.",
            }
        refresh_token = existing

    resp = http_requests.get(
        GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=10
    )
    if resp.status_code != 200:
        return {"ok": False, "error": "Google 사용자 정보를 가져오지 못했습니다."}
    info = resp.json()
    email = info.get("email")
    if not email:
        return {"ok": False, "error": "Google 계정에서 이메일을 가져오지 못했습니다."}

    db.link_account(pending["user_id"], "google", email, access_token=refresh_token)
    _sync_after_link_background("google", refresh_token, pending["user_id"])
    return {"ok": True, "login": email, "synced": None}


def get_oauth_authorize_url(provider: str, user_id: int) -> str:
    """GitHub/GitLab은 Google Identity Services 같은 순수 클라이언트 플로우가 없어서(클라이언트
    시크릿이 꼭 필요한 표준 OAuth Authorization Code 방식), 우리 백엔드가 콜백을 직접 받는다.
    state에 이 요청을 시작한 user_id를 연결해뒀다가, 콜백 때(브라우저 리다이렉트라 우리 로그인
    헤더가 없음) 그 state로 어느 계정인지 복구한다."""
    config = _oauth_config(provider)
    state = db.create_oauth_state(user_id, provider)
    params = urllib.parse.urlencode({
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "scope": config["scope"],
        "response_type": "code",
        "state": state,
    })
    return f"{config['authorize_url']}?{params}"


def complete_oauth_link(provider: str, code: str, state: str) -> dict:
    """콜백에서 code+state를 받아 실제로 계정을 연결한다. 성공/실패와 무관하게
    프론트에 알려줄 정보를 dict로 반환한다 (예외 대신 반환값으로 처리 — 콜백 응답은
    항상 postMessage용 HTML이어야 해서 어느 쪽이든 화면을 그려야 하기 때문)."""
    pending = db.consume_oauth_state(state)
    if not pending or pending["provider"] != provider:
        return {"ok": False, "error": "유효하지 않거나 만료된 연결 요청입니다."}

    try:
        config = _oauth_config(provider)
    except AuthError as e:
        return {"ok": False, "error": str(e)}

    token_resp = http_requests.post(
        config["token_url"],
        headers={"Accept": "application/json", **config["extra_headers"]},
        data={
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "code": code,
            "redirect_uri": config["redirect_uri"],
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    token_data = token_resp.json() if token_resp.ok else {}
    access_token = token_data.get("access_token")
    if not access_token:
        return {"ok": False, "error": token_data.get("error_description", f"{provider} 토큰 발급에 실패했습니다.")}

    user_resp = http_requests.get(
        config["user_url"],
        headers={"Authorization": f"Bearer {access_token}", **config["extra_headers"]},
        timeout=10,
    )
    if not user_resp.ok:
        return {"ok": False, "error": f"{provider} 사용자 정보를 가져오지 못했습니다."}

    login = user_resp.json().get(config["login_field"])
    if not login:
        return {"ok": False, "error": f"{provider} 사용자 정보를 가져오지 못했습니다."}

    # GitLab access token은 기본 2시간이면 만료되므로 refresh_token을 반드시 같이 저장해야 한다
    # (예전엔 버려서, 연동 두 시간 뒤부터 그 소스 문서가 조용히 검색에서 사라졌다).
    db.link_account(
        pending["user_id"], provider, login,
        access_token=access_token,
        refresh_token=token_data.get("refresh_token"),
    )
    _sync_after_link_background(provider, access_token, pending["user_id"])
    return {"ok": True, "login": login, "synced": None}


def refresh_provider_access_token(user_id: int, provider: str) -> Optional[str]:
    """저장해둔 refresh_token으로 새 access_token을 받아 DB에 갱신하고 반환한다.
    refresh_token이 없거나(예: 만료 없는 GitHub OAuth App) 갱신에 실패하면 None —
    그 경우 사용자가 직접 다시 연결해야 한다.

    Google은 전용 경로(refresh_google_access_token)를 따로 쓰고, 여기는 OAUTH_PROVIDERS
    (GitHub/GitLab)의 표준 refresh_token 그랜트를 처리한다."""
    if provider not in OAUTH_PROVIDERS:
        return None
    refresh_token = db.get_linked_refresh_token(user_id, provider)
    if not refresh_token:
        return None

    try:
        config = _oauth_config(provider)
    except AuthError:
        return None

    try:
        resp = http_requests.post(
            config["token_url"],
            headers={"Accept": "application/json", **config["extra_headers"]},
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "redirect_uri": config["redirect_uri"],
            },
            timeout=10,
        )
        data = resp.json() if resp.ok else {}
    except (http_requests.RequestException, ValueError) as e:
        print(f"{provider} 토큰 갱신 실패: {e}")
        return None

    access_token = data.get("access_token")
    if not access_token:
        print(f"{provider} 토큰 갱신 실패: {data.get('error_description') or data.get('error') or '응답에 토큰 없음'}")
        return None

    # GitLab은 갱신할 때마다 refresh_token도 새로 준다(1회용) — 같이 저장해야 다음 갱신이 된다.
    db.update_tokens(user_id, provider, access_token, data.get("refresh_token"))
    return access_token


def _slack_oauth_config() -> tuple[str, str]:
    if not SLACK_OAUTH_CLIENT_ID or SLACK_OAUTH_CLIENT_ID == "your_slack_oauth_client_id_here":
        raise AuthError("SLACK_OAUTH_CLIENT_ID가 설정되지 않았습니다. backend/.env를 확인하세요.")
    if not SLACK_OAUTH_CLIENT_SECRET or SLACK_OAUTH_CLIENT_SECRET == "your_slack_oauth_client_secret_here":
        raise AuthError("SLACK_OAUTH_CLIENT_SECRET이 설정되지 않았습니다. backend/.env를 확인하세요.")
    return SLACK_OAUTH_CLIENT_ID, SLACK_OAUTH_CLIENT_SECRET


def get_slack_authorize_url(user_id: int) -> str:
    """Slack은 봇 토큰과 사용자 토큰을 같은 앱에서 함께 발급할 수 있어서(수집용 SLACK_BOT_TOKEN과는
    별개 앱을 새로 만들 필요 없이), 기존 Slack 앱의 OAuth & Permissions에 User Token Scopes만
    추가하면 된다. user_scope로 요청해 `authed_user.access_token`(사용자 본인 권한 토큰)을 받는다."""
    client_id, _ = _slack_oauth_config()
    state = db.create_oauth_state(user_id, "slack")
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": SLACK_OAUTH_REDIRECT_URI,
        "user_scope": SLACK_USER_SCOPE,
        "state": state,
    })
    return f"https://slack.com/oauth/v2/authorize?{params}"


def complete_slack_link(code: str, state: str) -> dict:
    """GitHub/GitLab과 응답 형태가 달라(access_token이 최상위가 아니라 authed_user 아래에 있고,
    별도의 /user 엔드포인트도 없음) 공용 OAUTH_PROVIDERS 흐름에 억지로 맞추지 않고 따로 처리한다."""
    pending = db.consume_oauth_state(state)
    if not pending or pending["provider"] != "slack":
        return {"ok": False, "error": "유효하지 않거나 만료된 연결 요청입니다."}

    try:
        client_id, client_secret = _slack_oauth_config()
    except AuthError as e:
        return {"ok": False, "error": str(e)}

    token_resp = http_requests.post(
        "https://slack.com/api/oauth.v2.access",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": SLACK_OAUTH_REDIRECT_URI,
        },
        timeout=10,
    )
    token_data = token_resp.json() if token_resp.ok else {}
    if not token_data.get("ok"):
        return {"ok": False, "error": token_data.get("error", "Slack 토큰 발급에 실패했습니다.")}

    authed_user = token_data.get("authed_user", {})
    user_access_token = authed_user.get("access_token")
    slack_user_id = authed_user.get("id")
    if not user_access_token or not slack_user_id:
        return {"ok": False, "error": "Slack 사용자 토큰을 받지 못했습니다. User Token Scopes가 설정됐는지 확인하세요."}

    display_name = slack_user_id
    try:
        bot_token = os.getenv("SLACK_BOT_TOKEN")
        if bot_token:
            info_resp = http_requests.get(
                "https://slack.com/api/users.info",
                headers={"Authorization": f"Bearer {bot_token}"},
                params={"user": slack_user_id},
                timeout=10,
            )
            info_data = info_resp.json()
            if info_data.get("ok"):
                profile = info_data.get("user", {})
                display_name = profile.get("real_name") or profile.get("name") or slack_user_id
    except http_requests.RequestException:
        pass

    db.link_account(pending["user_id"], "slack", display_name, access_token=user_access_token)
    _sync_after_link_background("slack", user_access_token, pending["user_id"])
    return {"ok": True, "login": display_name, "synced": None}


def _notion_oauth_config() -> tuple[str, str]:
    if not NOTION_OAUTH_CLIENT_ID or NOTION_OAUTH_CLIENT_ID == "your_notion_oauth_client_id_here":
        raise AuthError("NOTION_OAUTH_CLIENT_ID가 설정되지 않았습니다. backend/.env를 확인하세요.")
    if not NOTION_OAUTH_CLIENT_SECRET or NOTION_OAUTH_CLIENT_SECRET == "your_notion_oauth_client_secret_here":
        raise AuthError("NOTION_OAUTH_CLIENT_SECRET이 설정되지 않았습니다. backend/.env를 확인하세요.")
    return NOTION_OAUTH_CLIENT_ID, NOTION_OAUTH_CLIENT_SECRET


def get_notion_authorize_url(user_id: int) -> str:
    """Notion Public Integration은 동의 화면에서 사용자가 '이 통합에 공유할 페이지'를 직접
    고르기 때문에(내부 통합처럼 관리자가 미리 다 공유해두는 방식과 다름), 이 OAuth로 받는 토큰은
    그 사람이 그 순간 고른 페이지에만 접근할 수 있다 — 검색 시 권한 확인이 Drive/GitHub/GitLab과
    동일한 패턴(본인 토큰으로 건별 GET)이 되는 이유."""
    client_id, _ = _notion_oauth_config()
    state = db.create_oauth_state(user_id, "notion")
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": NOTION_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "owner": "user",
        "state": state,
    })
    return f"https://api.notion.com/v1/oauth/authorize?{params}"


def complete_notion_link(code: str, state: str) -> dict:
    """Notion 토큰 교환은 Basic Auth(client_id:client_secret)를 쓰고 신원 정보가 응답 안에
    바로 포함돼 있어서(별도 /user 엔드포인트 호출 불필요) GitHub/GitLab 공용 흐름과도,
    Slack과도 모양이 또 달라 독립적으로 구현한다."""
    pending = db.consume_oauth_state(state)
    if not pending or pending["provider"] != "notion":
        return {"ok": False, "error": "유효하지 않거나 만료된 연결 요청입니다."}

    try:
        client_id, client_secret = _notion_oauth_config()
    except AuthError as e:
        return {"ok": False, "error": str(e)}

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    token_resp = http_requests.post(
        "https://api.notion.com/v1/oauth/token",
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/json"},
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": NOTION_OAUTH_REDIRECT_URI,
        },
        timeout=10,
    )
    token_data = token_resp.json() if token_resp.ok else {}
    access_token = token_data.get("access_token")
    if not access_token:
        return {"ok": False, "error": token_data.get("message", "Notion 토큰 발급에 실패했습니다.")}

    owner_user = (token_data.get("owner") or {}).get("user") or {}
    display_name = (
        owner_user.get("name")
        or (owner_user.get("person") or {}).get("email")
        or token_data.get("workspace_name")
        or "Notion 사용자"
    )

    db.link_account(pending["user_id"], "notion", display_name, access_token=access_token)
    _sync_after_link_background("notion", access_token, pending["user_id"])
    return {"ok": True, "login": display_name, "synced": None}
