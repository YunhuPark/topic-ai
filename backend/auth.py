"""자체 로그인(이메일+비밀번호) 시스템. 세션은 우리가 직접 서명하는 JWT로 유지한다.

Phase 6a: 회원가입/로그인/세션 검증
Phase 6b: 로그인한 계정에 Google 신원을 연결(link_google_account)해서 권한 인지형 검색에 사용
"""

import base64
import os
import re
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

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_DAYS = 7
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
# 채널 접근 권한 확인(conversations.history)에 쓸 "사용자 토큰" 스코프.
# 봇 토큰(SLACK_BOT_TOKEN, 수집용)과 별개로, 로그인한 사람 본인 권한을 나타내는 토큰을 받는다.
SLACK_USER_SCOPE = "channels:history,groups:history,channels:read,groups:read"

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


def signup(email: str, password: str) -> tuple[str, str]:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("올바른 이메일 형식이 아닙니다.")
    if len(password) < 8:
        raise AuthError("비밀번호는 8자 이상이어야 합니다.")

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


def login(email: str, password: str) -> tuple[str, str]:
    email = email.strip().lower()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()

    if not row or not bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8")):
        raise AuthError("이메일 또는 비밀번호가 올바르지 않습니다.")

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


def link_google_account(user_id: int, google_access_token: str) -> str:
    """프론트에서 Google OAuth(Drive 메타데이터 읽기 스코프 동의)로 받은 access token을
    Google의 userinfo 엔드포인트에 직접 검증해서, 그 안의 실제 이메일을 user_id 계정에 연결한다.
    이 access token 자체는 검색 시점에 Drive 파일별 접근 가능 여부를 실시간으로 확인하는 데도 쓰인다
    (서비스 계정으로는 파일의 전체 권한자 목록을 볼 수 없어서, 사용자 본인 토큰으로 건별 확인하는 방식으로 설계함).
    """
    resp = http_requests.get(
        GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {google_access_token}"}, timeout=10
    )
    if resp.status_code != 200:
        raise AuthError("Google 인증 확인에 실패했습니다. 다시 연결해 주세요.")

    info = resp.json()
    email = info.get("email")
    if not email:
        raise AuthError("Google 계정에서 이메일을 가져오지 못했습니다.")
    if not info.get("email_verified"):
        raise AuthError("이메일이 인증되지 않은 Google 계정입니다.")

    db.link_account(user_id, "google", email)
    return email


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

    db.link_account(pending["user_id"], provider, login, access_token=access_token)
    return {"ok": True, "login": login}


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
    return {"ok": True, "login": display_name}


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
    return {"ok": True, "login": display_name}
