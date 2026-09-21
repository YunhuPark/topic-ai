import sys

# Windows 콘솔(cp949)이 이모지를 못 그려서 로그 print가 예외를 던지고,
# 그 예외가 진짜 처리 결과를 mock 폴백으로 덮어써버리는 문제 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import asyncio
import html
import json
import os
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import requests as http_requests
from fastapi import FastAPI, Query, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from typing import Optional
from models import (
    SearchResponse, StatsResponse,
    SignupRequest, LoginRequest, AuthResponse, MeResponse,
    LinkedAccount, SearchHistoryItem, ActionItemRecord, SearchCountResponse,
    AuthorizeUrlResponse, SyncStatusItem, SyncStatusResponse,
)
import rag_pipeline
import db
import auth

db.init_db()

app = FastAPI(
    title="Topic Thread AI Backend API",
    description="사내 통합 검색 어시스턴트 API",
    version="0.1.0"
)


SEARCH_CANDIDATE_POOL = 20  # 하이브리드 재정렬을 위해 벡터 유사도만으로 넉넉히 뽑아둘 후보 수
SEARCH_MAX_RESULTS = 4

# similarity_search_with_score만으로는 검색어가 색인된 문서 어디에도 안 맞아도 "그나마 덜 먼"
# 후보를 억지로 내놓는다 — 이 기준 미만이면 순위/권한 확인 대상에서 아예 제외해서, 진짜 관련
# 문서가 없을 땐 정직하게 "결과 없음"을 보여준다.
#
# 0.3은 실사용 중 무의미한 검색어("asdfqwer123" 등)도 통과시키는 게 드러나서 0.35로 올림 —
# 다만 이 값 하나로 완벽히 가를 순 없다는 걸 실측으로 확인했다: 무의미한 검색어의 관련도
# (0.22~0.37)와 실제 존재하는 주제어의 관련도(0.32~0.52) 구간이 서로 겹친다(문서 수가
# 370개 정도로 작아서 벡터 거리만으로는 노이즈와 진짜 약한 매칭을 완전히 못 가름). 0.35는
# 실측한 무의미 검색어 대부분(0.22~0.3253)을 걸러내면서 진짜 검색어(0.318 이상)는 대부분
# 살리는 보수적 절충점 — "!@#$%^&*"(0.3738)처럼 극단적 예외가 드물게 남을 수 있다.
MIN_SEARCH_RELEVANCE = 0.35

# 같은 로컬 서버라도 브라우저는 localhost와 127.0.0.1을 다른 origin으로 본다. 하나만 지정해두면
# 사용자가 다른 쪽 주소로 접속했을 때 OAuth 연결에 성공하고도 프론트가 postMessage를 못 받아
# "연결 창이 닫혔습니다" 오류로 보인다 — 그래서 알려진 프론트 origin 전부를 허용/발송 대상으로 쓴다.
FRONTEND_ORIGINS = [
    o.strip() for o in os.getenv(
        "FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if o.strip()
]

# 계정 연동 시점 자동 수집(FR-15)만으로는 그 이후 원본에 새로 쌓인 대화/문서가 반영 안 되므로,
# 서버에 (access 또는 refresh) 토큰을 저장해두는 5개 소스 전부를 주기적으로 백그라운드에서
# 다시 수집한다. Google도 refresh_token 방식으로 전환하면서 이 폴링에 들어왔다.
AUTO_RESYNC_PROVIDERS = ["google", "github", "gitlab", "slack", "notion"]
AUTO_RESYNC_INTERVAL_SECONDS = int(os.getenv("AUTO_RESYNC_INTERVAL_SECONDS", "900"))


async def _auto_resync_loop():
    while True:
        await asyncio.sleep(AUTO_RESYNC_INTERVAL_SECONDS)
        accounts = db.get_all_accounts_with_tokens(AUTO_RESYNC_PROVIDERS)
        for acc in accounts:
            user_id, provider = acc["user_id"], acc["provider"]
            try:
                stored_token = acc["access_token"]
                # google은 linked_accounts에 refresh_token을 저장해두므로, 실제 수집에 쓸
                # 짧은 수명 access_token을 그때그때 새로 발급받아야 한다 (블로킹 HTTP 호출이라
                # 이벤트 루프를 막지 않도록 스레드로 돌린다).
                if provider == "google":
                    stored_token = await asyncio.to_thread(auth.refresh_google_access_token, stored_token)
                try:
                    count = await asyncio.to_thread(
                        rag_pipeline.sync_documents_for_user, provider, stored_token, user_id
                    )
                except Exception as e:
                    # 토큰 만료(401)면 refresh_token으로 한 번 갱신해서 재시도한다 —
                    # GitLab access token은 기본 2시간이면 만료되므로 이게 없으면 연동이 곧 죽는다.
                    if "401" not in str(e):
                        raise
                    refreshed = await asyncio.to_thread(
                        auth.refresh_provider_access_token, user_id, provider
                    )
                    if not refreshed:
                        raise
                    print(f"[자동 재동기화] user_id={user_id} provider={provider} 토큰 갱신 후 재시도")
                    count = await asyncio.to_thread(
                        rag_pipeline.sync_documents_for_user, provider, refreshed, user_id
                    )
                print(f"[자동 재동기화] user_id={user_id} provider={provider} 새 임베딩 {count}개")
            except Exception as e:
                print(f"[자동 재동기화 실패] user_id={user_id} provider={provider}: {e}")


@app.on_event("startup")
async def _start_auto_resync():
    asyncio.create_task(_auto_resync_loop())


def _extract_source_name(source: str, tags_str: str) -> str:
    """github/gitlab/slack는 tags[1]에 저장소·프로젝트·채널 이름이 들어있다(각 커넥터가 만드는
    tags 순서 ["github", "owner/repo", kind] 등에 의존). notion/gdrive는 tags[1]이 "sheet"/"pdf"
    같은 파일 종류일 뿐 이름이 아니라서 여기 포함하지 않는다."""
    if source not in ("github", "gitlab", "slack"):
        return ""
    parts = (tags_str or "").split(",")
    return parts[1] if len(parts) > 1 else ""


def _keyword_boost(query: str, title: str, content: str, source_name: str = "") -> float:
    """벡터 유사도만으로는 "paper"처럼 짧고 뜻이 여러 개인 질의어가 제목에 그 단어가
    그대로 들어간 문서보다 의미상 막연히 가까운 다른 문서를 앞세우는 경우가 있어서
    (실제 검증: 19개 문서 중 제목이 "paper_draft"인 문서가 13위로 밀림), 제목/본문/출처 이름에
    질의어가 그대로 등장하면 가산점을 주는 가벼운 키워드 보정. 0~1 범위.

    출처 이름(저장소/프로젝트/채널명) 일치가 가장 강한 신호로 취급된다 — 실제 검증: "medi" 검색 시
    "Medi-Matrix" 저장소 자체의 PR보다, 그 저장소를 본문에서 언급만 한 다른 저장소("portfolio")의
    문서가 앞서는 문제를 발견함. 특정 프로젝트를 가리키는 것이 명백한 짧은 질의어는 그 프로젝트
    "자체"의 문서를 최우선해야 자연스럽다."""
    tokens = [t for t in re.findall(r"[\w가-힣]+", query.lower()) if len(t) >= 2]
    if not tokens:
        return 0.0
    title_l, content_l, source_l = title.lower(), content.lower(), source_name.lower()
    weight_per_token = 3.0 if source_l else 2.0
    score = 0.0
    for t in tokens:
        if source_l and t in source_l:
            score += 3.0
        elif t in title_l:
            score += 2.0  # 제목 일치가 본문 일치보다 훨씬 강한 신호
        elif t in content_l:
            score += 1.0
    return score / (len(tokens) * weight_per_token)


def compute_freshness(date_str: str) -> str:
    """문서 날짜 기준으로 fresh(30일 이내)/moderate(90일 이내)/stale(그 이후)를 판정합니다."""
    try:
        doc_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return "moderate"
    age_days = (date.today() - doc_date).days
    if age_days <= 30:
        return "fresh"
    if age_days <= 90:
        return "moderate"
    return "stale"

# CORS 설정 (프론트엔드 통신 허용) — OAuth 콜백의 postMessage 대상과 같은 목록을 쓴다
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Welcome to Topic Thread AI API"}


@app.post("/api/v1/auth/signup", response_model=AuthResponse)
def auth_signup(payload: SignupRequest):
    try:
        token, email = auth.signup(payload.email, payload.password)
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AuthResponse(token=token, email=email)


@app.post("/api/v1/auth/login", response_model=AuthResponse)
def auth_login(payload: LoginRequest):
    try:
        token, email = auth.login(payload.email, payload.password)
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return AuthResponse(token=token, email=email)


@app.get("/api/v1/auth/me", response_model=MeResponse)
def auth_me(authorization: Optional[str] = Header(None)):
    user = auth.get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return MeResponse(**user)


@app.get("/api/v1/auth/link/google/start", response_model=AuthorizeUrlResponse)
def link_google_start(authorization: Optional[str] = Header(None)):
    """Google도 이제 GitHub/GitLab과 같은 팝업+콜백 패턴이라, 이 구체적인 경로를 아래의
    `/link/{provider}/start`보다 먼저 등록해 "google"이 그쪽으로 새지 않게 한다."""
    user = auth.get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        url = auth.get_google_authorize_url(user["id"])
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AuthorizeUrlResponse(authorizeUrl=url)


@app.get("/api/v1/auth/link/google/callback", response_class=HTMLResponse)
def link_google_callback(code: str = "", state: str = ""):
    result = auth.complete_google_link(code, state)
    return _oauth_callback_html("google", result)


@app.delete("/api/v1/auth/link/{provider}", response_model=list[LinkedAccount])
def unlink_account(provider: str, authorization: Optional[str] = Header(None)):
    """연동을 해제하고, 그 사용자가 이 소스로 가져왔던 문서도 함께 정리한다."""
    user = _require_user(authorization)
    if provider not in rag_pipeline.PROVIDER_SOURCES:
        raise HTTPException(status_code=404, detail="지원하지 않는 연동입니다.")
    if not db.unlink_account(user["id"], provider):
        raise HTTPException(status_code=404, detail="연결된 계정이 없습니다.")
    try:
        removed = rag_pipeline.remove_user_documents(provider, user["id"])
        print(f"[연동 해제] user_id={user['id']} provider={provider} 문서 {removed}개 정리")
    except Exception as e:
        # 문서 정리가 실패해도 연동 해제 자체는 이미 끝났다 (다음 정리 때 걸린다)
        print(f"[연동 해제] 문서 정리 실패 user_id={user['id']} provider={provider}: {e}")
    return db.get_linked_accounts(user["id"])


@app.get("/api/v1/auth/linked", response_model=list[LinkedAccount])
def get_linked(authorization: Optional[str] = Header(None)):
    user = auth.get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return db.get_linked_accounts(user["id"])


def _oauth_callback_html(provider: str, result: dict) -> str:
    payload = {"provider": provider, **result}
    # </script>가 섞인 값(제공자가 내려준 오류 문구, 표시 이름 등)이 스크립트 태그를 깨고 나오지
    # 않도록 이스케이프한다. 화면에 그대로 찍는 오류 문구도 HTML 이스케이프.
    message_json = json.dumps(payload).replace("<", "\\u003c").replace(">", "\\u003e")
    if result.get("ok"):
        message = html.escape(f"{provider} 연결 완료! 이 창은 자동으로 닫힙니다...")
    else:
        message = "연결에 실패했습니다: " + html.escape(result.get("error", ""))
    origins_json = json.dumps(FRONTEND_ORIGINS)
    return f"""
    <html><body style="background:#0a0b0f;color:#fff;font-family:sans-serif;
    display:flex;align-items:center;justify-content:center;height:100vh;margin:0;">
      <p>{message}</p>
      <script>
        if (window.opener) {{
          for (const origin of {origins_json}) {{
            window.opener.postMessage({message_json}, origin);
          }}
        }}
        setTimeout(() => window.close(), 1200);
      </script>
    </body></html>
    """


@app.get("/api/v1/auth/link/slack/start", response_model=AuthorizeUrlResponse)
def link_slack_start(authorization: Optional[str] = Header(None)):
    """Slack은 응답 형태가 GitHub/GitLab과 달라(authed_user 중첩 구조) 공용 {provider} 라우트에
    태우지 않고 따로 둔다. FastAPI는 라우트를 등록 순서대로 매칭하므로, 이 구체적인 경로를
    아래의 `/link/{provider}/start`보다 먼저 등록해야 "slack"이 그쪽으로 새지 않는다."""
    user = auth.get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        url = auth.get_slack_authorize_url(user["id"])
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AuthorizeUrlResponse(authorizeUrl=url)


@app.get("/api/v1/auth/link/slack/callback", response_class=HTMLResponse)
def link_slack_callback(code: str = "", state: str = ""):
    result = auth.complete_slack_link(code, state)
    return _oauth_callback_html("slack", result)


@app.get("/api/v1/auth/link/notion/start", response_model=AuthorizeUrlResponse)
def link_notion_start(authorization: Optional[str] = Header(None)):
    """Notion도 Slack처럼 응답 형태가 달라(토큰 교환이 Basic Auth, 신원 정보가 owner 안에 중첩)
    공용 {provider} 라우트를 타지 않고 구체적인 경로를 그보다 먼저 등록해둔다."""
    user = auth.get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        url = auth.get_notion_authorize_url(user["id"])
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AuthorizeUrlResponse(authorizeUrl=url)


@app.get("/api/v1/auth/link/notion/callback", response_class=HTMLResponse)
def link_notion_callback(code: str = "", state: str = ""):
    result = auth.complete_notion_link(code, state)
    return _oauth_callback_html("notion", result)


@app.get("/api/v1/auth/link/{provider}/start", response_model=AuthorizeUrlResponse)
def link_oauth_start(provider: str, authorization: Optional[str] = Header(None)):
    if provider not in auth.OAUTH_PROVIDERS:
        raise HTTPException(status_code=404, detail="지원하지 않는 연동입니다.")
    user = auth.get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        url = auth.get_oauth_authorize_url(provider, user["id"])
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AuthorizeUrlResponse(authorizeUrl=url)


@app.get("/api/v1/auth/link/{provider}/callback", response_class=HTMLResponse)
def link_oauth_callback(provider: str, code: str = "", state: str = ""):
    """GitHub/GitLab이 사용자를 여기로 리다이렉트한다 (팝업 창). 우리 로그인 헤더는 없지만
    state로 어느 계정이 시작한 요청인지 복구해서 연결한 뒤, 팝업을 연 원래 창에
    postMessage로 결과를 알리고 창을 닫는다."""
    if provider not in auth.OAUTH_PROVIDERS:
        return HTMLResponse("지원하지 않는 연동입니다.", status_code=404)
    result = auth.complete_oauth_link(provider, code, state)
    return _oauth_callback_html(provider, result)


def _require_user(authorization: Optional[str]) -> dict:
    user = auth.get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


@app.get("/api/v1/search-history", response_model=list[SearchHistoryItem])
def search_history(authorization: Optional[str] = Header(None)):
    user = _require_user(authorization)
    return db.get_search_history(user["id"])


@app.get("/api/v1/search-history/count", response_model=SearchCountResponse)
def search_history_count(days: int = 7, authorization: Optional[str] = Header(None)):
    user = _require_user(authorization)
    since_iso = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
    return SearchCountResponse(count=db.count_searches_since(user["id"], since_iso))


@app.get("/api/v1/action-items", response_model=list[ActionItemRecord])
def action_items(authorization: Optional[str] = Header(None)):
    user = _require_user(authorization)
    return db.get_action_items(user["id"])


@app.patch("/api/v1/action-items/{item_id}", response_model=list[ActionItemRecord])
def toggle_action_item(item_id: int, authorization: Optional[str] = Header(None)):
    user = _require_user(authorization)
    result = db.toggle_action_item_status(user["id"], item_id)
    if not result:
        raise HTTPException(status_code=404, detail="할 일을 찾을 수 없습니다.")
    return db.get_action_items(user["id"])


@app.delete("/api/v1/action-items/{item_id}", response_model=list[ActionItemRecord])
def delete_action_item(item_id: int, authorization: Optional[str] = Header(None)):
    user = _require_user(authorization)
    if not db.delete_action_item(user["id"], item_id):
        raise HTTPException(status_code=404, detail="할 일을 찾을 수 없습니다.")
    return db.get_action_items(user["id"])

STATS_MAX_TOPICS = 50  # 문서가 수천 개로 늘어도 대시보드 응답이 무거워지지 않도록 상한


@app.get("/api/v1/stats", response_model=StatsResponse)
def get_stats(authorization: Optional[str] = Header(None)):
    """대시보드용 통계: 인덱싱된 문서 수, 연동 소스 수, 신선도 분포, 문서(토픽) 목록.

    **본인이 연동해서 가져온 문서(syncedBy에 내 user_id가 있는 것)만** 집계한다 — 모든 사용자가
    Chroma 컬렉션 하나를 공유하기 때문에, 이 제한이 없으면 남의 비공개 Slack 대화·개인 Drive 파일
    제목이 그대로 보인다(검색은 요청마다 권한을 확인하는데 통계만 그 전제를 비켜가던 문제)."""
    user = _require_user(authorization)
    vectorstore = rag_pipeline.get_vectorstore()
    data = vectorstore._collection.get(include=["metadatas"])
    metadatas = data.get("metadatas", [])

    marker = f",{user['id']},"
    source_counts: dict[str, int] = {}
    freshness_counts = {"fresh": 0, "moderate": 0, "stale": 0}
    topics = []
    total = 0

    for m in metadatas:
        if not m or marker not in (m.get("syncedBy") or ""):
            continue
        total += 1
        source = m.get("source", "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1

        doc_date = m.get("date", "")
        freshness = compute_freshness(doc_date)
        freshness_counts[freshness] += 1

        topics.append({
            "id": m.get("id", "unknown"),
            "label": m.get("title", "문서"),
            "source": source,
            "date": doc_date,
        })

    topics.sort(key=lambda t: t["date"], reverse=True)

    return StatsResponse(
        totalDocuments=total,
        connectedSources=len(source_counts),
        sources=[{"source": s, "count": c} for s, c in source_counts.items()],
        freshness=freshness_counts,
        topics=topics[:STATS_MAX_TOPICS],
    )


@app.get("/api/v1/sync-status", response_model=SyncStatusResponse)
def sync_status(authorization: Optional[str] = Header(None)):
    """연동 직후 백그라운드 수집이나 15분 주기 재동기화가 지금 진행 중인 소스가 있는지,
    마지막 결과가 어땠는지 알려준다. 프론트가 연동 직후 이 엔드포인트를 짧은 간격으로 폴링해서
    "동기화 중..." 대신 실제 진행 상태(문서 몇 개 가져왔는지, 실패했는지)를 보여줄 수 있다.
    연동을 아직 안 했거나 이 서버 프로세스가 뜬 뒤로 한 번도 동기화가 안 돈 소스는 목록에 없다
    (휘발성 상태라 서버 재시작하면 비워짐 — DB에 영속할 만큼 중요한 정보는 아님)."""
    user = _require_user(authorization)
    statuses = rag_pipeline.get_sync_status(user["id"])
    items = [SyncStatusItem(provider=provider, **fields) for provider, fields in statuses.items()]
    return SyncStatusResponse(items=items)


# 권한 확인 결과. 예전엔 전부 bool이라 "권한 없음"과 "토큰이 죽었음"과 "일시적 오류"가 똑같이
# False로 뭉개져서, 사용자 입장에선 문서가 아무 설명 없이 사라지는 것처럼 보였다.
ACCESS_ALLOWED = "allowed"
ACCESS_DENIED = "denied"          # 실제로 접근 권한이 없음 (정상적인 제외)
ACCESS_AUTH_FAILED = "auth_failed"  # 토큰 만료/취소 → 재연결 필요
ACCESS_UNAVAILABLE = "unavailable"  # rate limit·서버 오류·타임아웃 등 일시적 실패

# 같은 저장소/채널이 여러 문서에 걸쳐 반복 조회되므로 짧게 캐시한다.
PERMISSION_CACHE_TTL_SECONDS = 300
_permission_cache: dict[tuple, tuple[str, float]] = {}
_permission_cache_lock = threading.Lock()


def _classify_response(resp) -> str:
    if resp.status_code == 200:
        return ACCESS_ALLOWED
    if resp.status_code == 401:
        return ACCESS_AUTH_FAILED
    if resp.status_code == 403:
        # GitHub는 rate limit도 403으로 준다 — 남은 한도가 0이면 권한 문제가 아니라 일시적 실패다.
        if resp.headers.get("X-RateLimit-Remaining") == "0":
            return ACCESS_UNAVAILABLE
        return ACCESS_DENIED
    if resp.status_code == 404:
        return ACCESS_DENIED
    return ACCESS_UNAVAILABLE


def _check_gdrive_access(file_id: str, google_access_token: str) -> str:
    """이 Google 계정(access token 소유자)이 실제로 이 파일에 접근 가능한지 Drive API로 직접 확인한다.
    서비스 계정으로는 파일의 전체 권한자 목록을 볼 수 없어서(403 insufficientFilePermissions),
    반대로 사용자 본인 토큰으로 파일 하나하나를 열어보는 방식으로 확인한다."""
    try:
        resp = http_requests.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={"fields": "id"},
            headers={"Authorization": f"Bearer {google_access_token}"},
            timeout=10,
        )
        return _classify_response(resp)
    except http_requests.RequestException:
        return ACCESS_UNAVAILABLE


def _check_github_access(repo_full_name: str, github_access_token: str) -> str:
    """이 GitHub 계정(access token 소유자)이 실제로 이 저장소에 접근 가능한지 직접 확인한다.
    GitHub는 access token이 오래 유지되므로(Google과 달리) 링크할 때 서버에 저장해두고 여기서 바로 쓴다."""
    try:
        resp = http_requests.get(
            f"https://api.github.com/repos/{repo_full_name}",
            headers={"Authorization": f"Bearer {github_access_token}", "Accept": "application/vnd.github+json"},
            timeout=10,
        )
        return _classify_response(resp)
    except http_requests.RequestException:
        return ACCESS_UNAVAILABLE


def _check_gitlab_access(project_path: str, gitlab_access_token: str) -> str:
    """이 GitLab 계정(access token 소유자)이 실제로 이 프로젝트에 접근 가능한지 직접 확인한다.
    GitHub와 동일한 패턴 — access token은 링크할 때 서버에 저장해두고 여기서 바로 쓴다."""
    try:
        project_id = urllib.parse.quote(project_path, safe="")
        resp = http_requests.get(
            f"{auth.GITLAB_URL}/api/v4/projects/{project_id}",
            headers={"Authorization": f"Bearer {gitlab_access_token}"},
            timeout=10,
        )
        return _classify_response(resp)
    except http_requests.RequestException:
        return ACCESS_UNAVAILABLE


def _check_notion_access(page_id: str, notion_access_token: str) -> str:
    """이 Notion 계정(사용자 토큰 소유자)이 실제로 이 페이지에 접근 가능한지 직접 확인한다.
    Public Integration은 동의 화면에서 그 사람이 고른 페이지에만 토큰이 접근 가능해서,
    Drive/GitHub/GitLab과 동일하게 본인 토큰으로 건별 GET하는 패턴이 그대로 맞는다."""
    try:
        resp = http_requests.get(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers={"Authorization": f"Bearer {notion_access_token}", "Notion-Version": "2022-06-28"},
            timeout=10,
        )
        return _classify_response(resp)
    except http_requests.RequestException:
        return ACCESS_UNAVAILABLE


# Slack은 오류도 200 + {"ok": false, "error": "..."}로 주기 때문에 error 문자열로 구분해야 한다.
_SLACK_AUTH_ERRORS = {"invalid_auth", "not_authed", "token_revoked", "account_inactive"}
_SLACK_TRANSIENT_ERRORS = {"ratelimited", "fatal_error", "service_unavailable", "internal_error"}


def _check_slack_access(channel_id: str, slack_user_token: str) -> str:
    """이 Slack 계정(사용자 토큰 소유자) 본인이 실제로 이 채널의 메시지를 볼 수 있는지 확인한다.
    공개 채널이라도 멤버가 아니면 conversations.history가 not_in_channel로 실패하므로,
    "채널 존재 여부"가 아니라 "내가 이 토큰으로 이 채널 대화를 읽을 수 있는가"를 그대로 확인하는 셈이다."""
    try:
        resp = http_requests.get(
            "https://slack.com/api/conversations.history",
            headers={"Authorization": f"Bearer {slack_user_token}"},
            params={"channel": channel_id, "limit": 1},
            timeout=10,
        )
        if resp.status_code == 429:
            return ACCESS_UNAVAILABLE
        if resp.status_code != 200:
            return _classify_response(resp)
        data = resp.json()
        if data.get("ok"):
            return ACCESS_ALLOWED
        error = data.get("error", "")
        if error in _SLACK_AUTH_ERRORS:
            return ACCESS_AUTH_FAILED
        if error in _SLACK_TRANSIENT_ERRORS:
            return ACCESS_UNAVAILABLE
        return ACCESS_DENIED  # not_in_channel, channel_not_found 등
    except (http_requests.RequestException, ValueError):
        return ACCESS_UNAVAILABLE


def _resource_of(source: str, metadata: dict) -> Optional[str]:
    """문서 메타데이터에서 "권한을 확인할 대상"(저장소/프로젝트/채널/파일/페이지)을 뽑아낸다.
    여러 문서가 같은 저장소·채널을 공유하므로, 이 단위로 묶어야 확인 횟수를 크게 줄일 수 있다."""
    doc_id = metadata.get("id", "") or ""
    tags = (metadata.get("tags", "") or "").split(",")

    if source == "gdrive":
        return doc_id[len("gdrive-"):] if doc_id.startswith("gdrive-") else None
    if source in ("github", "gitlab"):
        # 각 커넥터가 tags를 ["github", "owner/repo", kind] 순서로 만들어두는 것에 의존
        return tags[1] if len(tags) > 1 and tags[1] else None
    if source == "slack":
        # id 형식 "slack-{channelId}-{ts}" — 채널 ID엔 대시가 없고 ts는 점을 쓰므로 첫 "-"로 분리된다
        remainder = doc_id[len("slack-"):] if doc_id.startswith("slack-") else ""
        return remainder.split("-")[0] if remainder else None
    if source == "notion":
        # id 형식 "notion-{page_id}" — page_id 자체가 대시 포함 UUID라 접두사만 잘라내면 된다
        return doc_id[len("notion-"):] if doc_id.startswith("notion-") else None
    return None


def _check_access(source: str, resource: str, tokens: dict) -> str:
    token = tokens.get(source)
    if not token:
        return ACCESS_DENIED  # 연동 안 된 소스는 기본 거부
    if source == "gdrive":
        return _check_gdrive_access(resource, token)
    if source == "github":
        return _check_github_access(resource, token)
    if source == "gitlab":
        return _check_gitlab_access(resource, token)
    if source == "slack":
        return _check_slack_access(resource, token)
    if source == "notion":
        return _check_notion_access(resource, token)
    return ACCESS_DENIED


def _check_access_cached(user_id: int, source: str, resource: str, tokens: dict) -> str:
    key = (user_id, source, resource)
    now = time.time()
    with _permission_cache_lock:
        cached = _permission_cache.get(key)
        if cached and cached[1] > now:
            return cached[0]

    result = _check_access(source, resource, tokens)

    # 일시적 실패는 캐시하지 않는다 — 다음 검색 때 다시 확인해야 복구된 걸 알 수 있다.
    if result != ACCESS_UNAVAILABLE:
        with _permission_cache_lock:
            _permission_cache[key] = (result, now + PERMISSION_CACHE_TTL_SECONDS)
    return result


def _check_all(user_id: int, resources: set[tuple], tokens: dict) -> dict[tuple, str]:
    if not resources:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(resources))) as pool:
        futures = {
            pool.submit(_check_access_cached, user_id, source, resource, tokens): (source, resource)
            for source, resource in resources
        }
        return {futures[f]: f.result() for f in as_completed(futures)}


def _resolve_permissions(user_id: int, resources: set[tuple], tokens: dict) -> dict[tuple, str]:
    """(source, resource) 쌍들의 권한을 병렬로 확인한다. 예전엔 후보 문서마다 순차로 HTTP를
    호출해서 최악의 경우 20회 × 10초가 그대로 검색 지연이 됐다.

    토큰 만료로 실패한 소스는 저장된 refresh_token으로 한 번 갱신해서 다시 확인한다 —
    GitLab access token은 기본 2시간이면 만료되므로 이 재시도가 없으면 연동이 곧 죽는다."""
    results = _check_all(user_id, resources, tokens)

    expired_sources = {s for (s, _), v in results.items() if v == ACCESS_AUTH_FAILED}
    retry_resources = set()
    for source in expired_sources:
        provider = "google" if source == "gdrive" else source
        new_token = auth.refresh_provider_access_token(user_id, provider)
        if not new_token:
            continue
        tokens[source] = new_token
        with _permission_cache_lock:
            for resource in {r for (s, r) in results if s == source}:
                _permission_cache.pop((user_id, source, resource), None)
        retry_resources |= {(s, r) for (s, r) in results if s == source}

    if retry_resources:
        results.update(_check_all(user_id, retry_resources, tokens))
    return results


@app.get("/api/v1/search", response_model=SearchResponse)
def search_documents(
    q: str = Query(..., description="검색 쿼리"),
    authorization: Optional[str] = Header(None),
):
    """
    주어진 쿼리로 통합 검색을 수행하고 결과와 AI 요약을 반환합니다. 로그인이 필수입니다 —
    검색 기록과 액션아이템이 브라우저가 아니라 계정에 귀속되므로, 누구 계정인지 알아야 합니다.

    권한 인지형 검색 (다섯 다 토큰/연결이 없으면 검색 결과에서 제외한다 — 기본 거부):
    - Google Drive: 서버에 저장해둔 refresh_token으로 그때그때 짧은 수명 access token을 새로
      발급받아(auth.refresh_google_access_token) 그 파일을 실제로 열 수 있는지 실시간으로 확인한다
      (예전엔 프론트가 X-Google-Drive-Token 헤더로 매 요청 보내줘야 했지만, GitHub/GitLab처럼
      서버 저장 방식으로 바뀌면서 더 이상 필요 없다).
    - GitHub/GitLab: 계정 연결 시 서버에 저장해둔 access token으로 그
      저장소/프로젝트를 실제로 볼 수 있는지 실시간으로 확인한다.
    - Slack: 계정 연결 시 저장해둔 사용자 본인 토큰으로 그 채널 대화를
      실제로 읽을 수 있는지(conversations.history) 실시간으로 확인한다.
    - Notion: Public Integration 동의 화면에서 그 사람이 직접 고른 페이지에만
      토큰이 접근 가능하므로, Drive/GitHub/GitLab과 같은 패턴으로 본인 토큰으로 페이지를
      직접 GET해 확인한다.

    관련도(MIN_SEARCH_RELEVANCE) 미만인 후보는 권한 확인 전에 걸러진다 — 색인된 문서 어디에도
    안 맞는 검색어를 넣었을 때 "그나마 덜 먼" 문서를 억지로 보여주지 않기 위함.
    """
    user = auth.get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    tokens = {
        "github": db.get_linked_access_token(user["id"], "github"),
        "gitlab": db.get_linked_access_token(user["id"], "gitlab"),
        "slack": db.get_linked_access_token(user["id"], "slack"),
        "notion": db.get_linked_access_token(user["id"], "notion"),
    }
    google_refresh_token = db.get_linked_access_token(user["id"], "google")

    db.record_search(user["id"], q)

    # 1. RAG Vector DB에서 가장 관련성 높은 문서 검색
    try:
        vectorstore = rag_pipeline.get_vectorstore()

        # 아직 DB가 비어있는지 확인 로직은 생략 (데모용)
        # 최종 4개보다 넉넉히(20개) 후보를 뽑아서, 순수 벡터 거리 대신 (벡터 유사도 + 제목/본문
        # 키워드 일치) 하이브리드 점수로 재정렬한 뒤 상위 4개를 고른다 — 벡터 유사도만 쓰면
        # 검색어가 제목에 그대로 있는 문서도 밀려날 수 있다 (_keyword_boost 참고).
        results = vectorstore.similarity_search_with_score(q, k=SEARCH_CANDIDATE_POOL)

        if not results:
            # 아직 아무 문서도 색인되지 않은 상태 — 예전엔 mock 문서를 돌려줬지만, 사용자가
            # 진짜 사내 문서와 구분할 방법이 없어서 없앴다.
            return SearchResponse(documents=[], summary={
                "title": "아직 검색할 문서가 없습니다",
                "keyPoints": [
                    "사이드바의 '연동 관리'에서 Google Drive·GitHub·GitLab·Slack·Notion 중 하나를 연결하면"
                    " 그 계정에서 접근 가능한 문서를 자동으로 가져옵니다.",
                ],
                "decisionTrail": [],
                "actionItems": [],
            })

        scored_results = []
        for d, distance in results:
            # Chroma 기본 거리(0~2 범위)를 0~1 관련도로 정규화
            relevance = max(0.0, min(1.0, 1 - distance / 2))
            source_name = _extract_source_name(d.metadata.get("source", ""), d.metadata.get("tags", ""))
            keyword_score = _keyword_boost(
                q, d.metadata.get("title", ""), d.metadata.get("content", d.page_content), source_name
            )
            combined_score = relevance * 0.65 + keyword_score * 0.35
            scored_results.append((combined_score, relevance, d))
        scored_results.sort(key=lambda item: item[0], reverse=True)

        # 관련도 자체가 너무 낮은 후보는 권한 확인·순위 대상에서 아예 제외한다 — 안 그러면
        # 색인된 문서 어디에도 안 맞는 검색어("xyz123" 등)도 "그나마 덜 먼" 문서 4개를 억지로
        # 보여주게 된다.
        #
        # 순수 벡터 관련도(r[1])가 아니라 max(combined_score, relevance)로 걸러야 한다 — 실제
        # 발견된 문제: "fox"로 검색하면 제목이 "fox-devil"인 문서가 벡터 유사도만으로는 0.29로
        # 임계값(0.3)에 살짝 못 미쳐, 제목에 검색어가 그대로 들어있는데도 _keyword_boost가 적용될
        # 기회조차 없이 걸러졌다. combined_score는 키워드 일치 시에만 relevance보다 높아지므로
        # (키워드 일치가 없으면 relevance*0.65로 오히려 더 낮음) 이 기준을 순수 벡터 매칭
        # 결과에 대해서는 그대로 유지하면서, "검색어가 제목/출처명에 그대로 들어간" 경우만
        # 구제한다.
        relevant_results = [r for r in scored_results if max(r[0], r[1]) >= MIN_SEARCH_RELEVANCE]

        # 후보들이 참조하는 "권한 확인 대상"을 먼저 모아서 중복을 없앤다 — 같은 저장소·채널의
        # 문서가 여러 개 걸리는 게 보통이라, 이것만으로도 실제 확인 횟수가 크게 준다.
        needed_resources = set()
        for _, _, d in relevant_results:
            source = d.metadata.get("source", "notion")
            resource = _resource_of(source, d.metadata)
            if resource:
                needed_resources.add((source, resource))

        # gdrive 문서가 후보에 있을 때만 Google access token을 갱신한다
        if any(source == "gdrive" for source, _ in needed_resources) and google_refresh_token:
            try:
                tokens["gdrive"] = auth.refresh_google_access_token(google_refresh_token)
            except auth.AuthError:
                tokens["gdrive"] = None

        permissions = _resolve_permissions(user["id"], needed_resources, tokens)
        disconnected = sorted({s for (s, _), v in permissions.items() if v == ACCESS_AUTH_FAILED})
        degraded = sorted({s for (s, _), v in permissions.items() if v == ACCESS_UNAVAILABLE})

        # 프론트엔드 포맷(List[dict])에 맞게 변환 (권한 없는 문서는 여기서 제외)
        formatted_docs = []
        visible_docs = []
        for combined_score, relevance, d in relevant_results:
            if len(formatted_docs) >= SEARCH_MAX_RESULTS:
                break
            source = d.metadata.get("source", "notion")
            resource = _resource_of(source, d.metadata)
            if not resource or permissions.get((source, resource)) != ACCESS_ALLOWED:
                continue

            # metadata.content가 임베딩용 접두사("Title: ...\n\nContent:\n") 없는 원본 본문
            content = d.metadata.get("content", d.page_content)
            doc_date = d.metadata.get("date", "2026-09-01")
            tags_str = d.metadata.get("tags", "")
            visible_docs.append(d)
            formatted_docs.append({
                "id": d.metadata.get("id", "unknown"),
                "title": d.metadata.get("title", "문서"),
                "source": source,
                "author": d.metadata.get("author", "알 수 없음"),
                "authorAvatar": d.metadata.get("author", "알")[0:2],
                "date": doc_date,
                "snippet": content[:150] + ("..." if len(content) > 150 else ""),
                "content": content,
                "tags": tags_str.split(",") if tags_str else [],
                "freshness": compute_freshness(doc_date),
                "relevance": round(relevance, 2),
                "sourceUrl": d.metadata.get("sourceUrl", "")
            })

        if not formatted_docs:
            # 빈 결과 사유를 구분해서 안내한다 — mock으로 채우지 않고 정직하게 빈 결과를 반환
            if not relevant_results:
                reason = "검색어와 관련성이 높은 문서를 찾지 못했습니다. 다른 검색어로 다시 시도해보세요."
            elif disconnected:
                reason = (
                    f"{', '.join(disconnected)} 연동이 만료되었거나 해제된 것 같습니다. "
                    "사이드바에서 다시 연결해 주세요."
                )
            elif degraded:
                reason = f"{', '.join(degraded)} 확인에 일시적으로 실패했습니다. 잠시 후 다시 시도해 주세요."
            else:
                reason = "검색된 문서가 있었지만, 현재 계정에 접근 권한이 없어 결과에서 제외됐습니다."
            return SearchResponse(
                documents=[],
                summary={
                    "title": "표시할 수 있는 결과가 없습니다",
                    "keyPoints": [reason],
                    "decisionTrail": [],
                    "actionItems": [],
                },
                disconnectedSources=disconnected,
                degradedSources=degraded,
            )

        # 2. LLM을 통한 요약 및 액션 아이템 추출
        summary_dict = rag_pipeline.generate_ai_summary(q, visible_docs)

        if summary_dict is None:
            # 요약만 실패한 경우 — 찾은 문서는 그대로 보여주되, 가짜 요약으로 채우지 않는다.
            # (할 일 저장도 건너뛴다 — 예전엔 mock 요약의 액션아이템이 진짜처럼 저장됐다.)
            return SearchResponse(
                documents=formatted_docs,
                summary={
                    "title": "AI 요약을 생성하지 못했습니다",
                    "keyPoints": ["검색된 문서는 아래에 그대로 표시했습니다. 잠시 후 다시 시도해 주세요."],
                    "decisionTrail": [],
                    "actionItems": [],
                },
                disconnectedSources=disconnected,
                degradedSources=degraded,
            )

        if summary_dict.get("actionItems"):
            db.upsert_action_items(user["id"], q, summary_dict["actionItems"])

        return SearchResponse(
            documents=formatted_docs,
            summary=summary_dict,
            disconnectedSources=disconnected,
            degradedSources=degraded,
        )

    except HTTPException:
        raise
    except Exception as e:
        # 예전엔 여기서 mock 문서를 반환해서, 백엔드가 고장난 상황이 "가짜 사내 문서"로 보였다.
        # 실패는 실패로 알린다.
        print(f"검색 중 에러: {e}")
        raise HTTPException(status_code=500, detail="검색 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
