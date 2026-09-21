import sys

# Windows 콘솔(cp949)이 이모지를 못 그려서 로그 print가 예외를 던지고,
# 그 예외가 진짜 처리 결과를 mock 폴백으로 덮어써버리는 문제 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import json
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import requests as http_requests
from fastapi import FastAPI, Query, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from typing import Optional
from models import (
    SearchResponse, StatsResponse,
    SignupRequest, LoginRequest, AuthResponse, MeResponse,
    LinkGoogleRequest, LinkedAccount, SearchHistoryItem, ActionItemRecord, SearchCountResponse,
    AuthorizeUrlResponse, SyncResponse,
)
from dummy_data import mock_documents, mock_summary
import rag_pipeline
import db
import auth

db.init_db()

app = FastAPI(
    title="Topic Thread AI Backend API",
    description="사내 통합 검색 어시스턴트 API",
    version="0.1.0"
)

# similarity_search_with_score(k=4)는 실제 관련성과 무관하게 항상 상위 4개를 반환한다 —
# 검색어가 색인된 문서 어디에도 안 맞아도 "그나마 덜 먼" 문서를 억지로 내놓는 문제가 있어서,
# 이 기준 미만이면 아예 결과에서 제외한다(정직하게 "결과 없음"을 보여주기 위함).
MIN_SEARCH_RELEVANCE = 0.3


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

# CORS 설정 (프론트엔드 통신 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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


@app.post("/api/v1/auth/link/google", response_model=LinkedAccount)
def link_google(payload: LinkGoogleRequest, authorization: Optional[str] = Header(None)):
    user = auth.get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        auth.link_google_account(user["id"], payload.accessToken)
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    linked = db.get_linked_accounts(user["id"])
    return next(a for a in linked if a["provider"] == "google")


@app.get("/api/v1/auth/linked", response_model=list[LinkedAccount])
def get_linked(authorization: Optional[str] = Header(None)):
    user = auth.get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return db.get_linked_accounts(user["id"])


FRONTEND_ORIGIN = "http://localhost:5173"


def _oauth_callback_html(provider: str, result: dict) -> str:
    payload = {"provider": provider, **result}
    message_json = json.dumps(payload)
    return f"""
    <html><body style="background:#0a0b0f;color:#fff;font-family:sans-serif;
    display:flex;align-items:center;justify-content:center;height:100vh;margin:0;">
      <p>{f'{provider} 연결 완료! 이 창은 자동으로 닫힙니다...' if result.get('ok') else '연결에 실패했습니다: ' + result.get('error', '')}</p>
      <script>
        if (window.opener) {{
          window.opener.postMessage({message_json}, "{FRONTEND_ORIGIN}");
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


# provider별로 "계정 연동 시 저장해둔 사용자 본인 토큰"을 받아 그 사람이 가진 전체
# 저장소/프로젝트/채널/페이지를 자동 탐색해서 수집하는 함수 매핑 (커넥터 쪽 함수 재사용).
def _sync_github(token: str) -> list[dict]:
    from connectors.github_connector import fetch_github_documents_for_token
    return fetch_github_documents_for_token(token)


def _sync_gitlab(token: str) -> list[dict]:
    from connectors.gitlab_connector import fetch_gitlab_documents_for_token
    return fetch_gitlab_documents_for_token(token)


def _sync_slack(token: str) -> list[dict]:
    from connectors.slack_connector import fetch_slack_documents_for_token
    return fetch_slack_documents_for_token(token)


def _sync_notion(token: str) -> list[dict]:
    from connectors.notion_connector import fetch_notion_documents_for_token
    return fetch_notion_documents_for_token(token)


_SYNC_HANDLERS = {
    "github": _sync_github,
    "gitlab": _sync_gitlab,
    "slack": _sync_slack,
    "notion": _sync_notion,
}


@app.post("/api/v1/sync/{provider}", response_model=SyncResponse)
def sync_account(provider: str, authorization: Optional[str] = Header(None)):
    """계정 연동 직후(또는 재연결 시) 프론트에서 호출한다. 고정 목록(GITHUB_REPOS 등)에
    의존하지 않고, 이 사람이 연동한 계정 본인 토큰으로 실제 볼 수 있는 저장소/프로젝트/채널/
    페이지 전체를 자동으로 찾아 색인한다. API 서버와 같은 프로세스에서 바로 실행되므로,
    오프라인 CLI 수집과 달리 서버 재시작 없이 즉시 검색에 반영된다."""
    user = _require_user(authorization)
    handler = _SYNC_HANDLERS.get(provider)
    if not handler:
        raise HTTPException(status_code=404, detail="지원하지 않는 연동입니다.")

    token = db.get_linked_access_token(user["id"], provider)
    if not token:
        raise HTTPException(status_code=400, detail=f"먼저 {provider} 계정을 연결하세요.")

    try:
        docs = handler(token)
    except Exception as e:
        print(f"{provider} 동기화 중 에러: {e}")
        raise HTTPException(status_code=502, detail=f"{provider} 동기화에 실패했습니다: {e}")

    rag_pipeline.ingest_documents(docs)
    return SyncResponse(provider=provider, count=len(docs))


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
        raise HTTPException(status_code=404, detail="액션 아이템을 찾을 수 없습니다.")
    return db.get_action_items(user["id"])

@app.get("/api/v1/stats", response_model=StatsResponse)
def get_stats():
    """대시보드용 통계: 인덱싱된 문서 수, 연동 소스 수, 신선도 분포, 문서(토픽) 목록."""
    vectorstore = rag_pipeline.get_vectorstore()
    data = vectorstore._collection.get(include=["metadatas"])
    metadatas = data.get("metadatas", [])

    source_counts: dict[str, int] = {}
    freshness_counts = {"fresh": 0, "moderate": 0, "stale": 0}
    topics = []

    for m in metadatas:
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
        totalDocuments=len(metadatas),
        connectedSources=len(source_counts),
        sources=[{"source": s, "count": c} for s, c in source_counts.items()],
        freshness=freshness_counts,
        topics=topics,
    )


def _check_gdrive_access(file_id: str, google_access_token: str) -> bool:
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
        return resp.status_code == 200
    except http_requests.RequestException:
        return False


def _check_github_access(repo_full_name: str, github_access_token: str) -> bool:
    """이 GitHub 계정(access token 소유자)이 실제로 이 저장소에 접근 가능한지 직접 확인한다.
    GitHub는 access token이 오래 유지되므로(Google과 달리) 링크할 때 서버에 저장해두고 여기서 바로 쓴다."""
    try:
        resp = http_requests.get(
            f"https://api.github.com/repos/{repo_full_name}",
            headers={"Authorization": f"Bearer {github_access_token}", "Accept": "application/vnd.github+json"},
            timeout=10,
        )
        return resp.status_code == 200
    except http_requests.RequestException:
        return False


def _check_gitlab_access(project_path: str, gitlab_access_token: str) -> bool:
    """이 GitLab 계정(access token 소유자)이 실제로 이 프로젝트에 접근 가능한지 직접 확인한다.
    GitHub와 동일한 패턴 — access token은 링크할 때 서버에 저장해두고 여기서 바로 쓴다."""
    try:
        project_id = urllib.parse.quote(project_path, safe="")
        resp = http_requests.get(
            f"{auth.GITLAB_URL}/api/v4/projects/{project_id}",
            headers={"Authorization": f"Bearer {gitlab_access_token}"},
            timeout=10,
        )
        return resp.status_code == 200
    except http_requests.RequestException:
        return False


def _check_notion_access(page_id: str, notion_access_token: str) -> bool:
    """이 Notion 계정(사용자 토큰 소유자)이 실제로 이 페이지에 접근 가능한지 직접 확인한다.
    Public Integration은 동의 화면에서 그 사람이 고른 페이지에만 토큰이 접근 가능해서,
    Drive/GitHub/GitLab과 동일하게 본인 토큰으로 건별 GET하는 패턴이 그대로 맞는다."""
    try:
        resp = http_requests.get(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers={"Authorization": f"Bearer {notion_access_token}", "Notion-Version": "2022-06-28"},
            timeout=10,
        )
        return resp.status_code == 200
    except http_requests.RequestException:
        return False


def _check_slack_access(channel_id: str, slack_user_token: str) -> bool:
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
        return resp.status_code == 200 and resp.json().get("ok", False)
    except http_requests.RequestException:
        return False


@app.get("/api/v1/search", response_model=SearchResponse)
def search_documents(
    q: str = Query(..., description="검색 쿼리"),
    authorization: Optional[str] = Header(None),
    x_google_drive_token: Optional[str] = Header(None),
):
    """
    주어진 쿼리로 통합 검색을 수행하고 결과와 AI 요약을 반환합니다. 로그인이 필수입니다 —
    검색 기록과 액션아이템이 브라우저가 아니라 계정에 귀속되므로, 누구 계정인지 알아야 합니다.

    권한 인지형 검색:
    - Google Drive(Phase 6b): 프론트가 함께 보낸 사용자 본인의 Google access token
      (X-Google-Drive-Token)으로 그 파일을 실제로 열 수 있는지 실시간으로 확인한다.
    - GitHub/GitLab(Phase 6c/6d): 계정 연결 시 서버에 저장해둔 access token으로 그
      저장소/프로젝트를 실제로 볼 수 있는지 실시간으로 확인한다.
    - Slack(Phase 6e): 계정 연결 시 저장해둔 사용자 본인 토큰으로 그 채널 대화를
      실제로 읽을 수 있는지(conversations.history) 실시간으로 확인한다.
    - Notion(Phase 6f): Public Integration 동의 화면에서 그 사람이 직접 고른 페이지에만
      토큰이 접근 가능하므로, Drive/GitHub/GitLab과 같은 패턴으로 본인 토큰으로 페이지를
      직접 GET해 확인한다.
    다섯 다 토큰/연결이 없으면 검색 결과에서 제외한다(기본 거부).
    """
    user = auth.get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    github_access_token = db.get_linked_access_token(user["id"], "github")
    gitlab_access_token = db.get_linked_access_token(user["id"], "gitlab")
    slack_access_token = db.get_linked_access_token(user["id"], "slack")
    notion_access_token = db.get_linked_access_token(user["id"], "notion")

    db.record_search(user["id"], q)

    # 1. RAG Vector DB에서 가장 관련성 높은 문서 검색
    try:
        vectorstore = rag_pipeline.get_vectorstore()

        # 아직 DB가 비어있는지 확인 로직은 생략 (데모용)
        # 유사도 기반 상위 4개 추출 (점수 포함 — 거리가 작을수록 유사)
        results = vectorstore.similarity_search_with_score(q, k=4)

        if not results:
            # DB가 비어있으면 Fallback
            return SearchResponse(documents=mock_documents, summary=mock_summary)

        # 프론트엔드 포맷(List[dict])에 맞게 변환 (권한 없는 gdrive 문서는 여기서 제외)
        formatted_docs = []
        visible_docs = []
        relevant_count = 0  # 권한 필터링 전, 관련도 기준을 통과한 문서 수 (빈 결과 사유 구분용)
        for d, distance in results:
            source = d.metadata.get("source", "notion")
            relevance = max(0.0, min(1.0, 1 - distance / 2))
            if relevance < MIN_SEARCH_RELEVANCE:
                continue
            relevant_count += 1
            if source == "gdrive":
                doc_id = d.metadata.get("id", "")
                file_id = doc_id[len("gdrive-"):] if doc_id.startswith("gdrive-") else None
                if not x_google_drive_token or not file_id or not _check_gdrive_access(file_id, x_google_drive_token):
                    continue
            if source == "github":
                # github_connector가 tags를 ["github", "owner/repo", kind] 순서로 만들어두는 것에 의존
                tags_list = (d.metadata.get("tags", "") or "").split(",")
                repo_full_name = tags_list[1] if len(tags_list) > 1 else None
                if not github_access_token or not repo_full_name or not _check_github_access(repo_full_name, github_access_token):
                    continue
            if source == "gitlab":
                # gitlab_connector도 tags를 ["gitlab", "namespace/project", kind] 순서로 만들어둔다
                tags_list = (d.metadata.get("tags", "") or "").split(",")
                project_path = tags_list[1] if len(tags_list) > 1 else None
                if not gitlab_access_token or not project_path or not _check_gitlab_access(project_path, gitlab_access_token):
                    continue
            if source == "slack":
                # slack_connector가 id를 "slack-{channelId}-{ts}" 형태로 만들어두는 것에 의존.
                # 채널 ID는 대시(-)를 포함하지 않고, 타임스탬프는 점(.)을 쓰므로 첫 "-"로 안전하게 분리된다.
                doc_id = d.metadata.get("id", "")
                remainder = doc_id[len("slack-"):] if doc_id.startswith("slack-") else ""
                channel_id = remainder.split("-")[0] if remainder else None
                if not slack_access_token or not channel_id or not _check_slack_access(channel_id, slack_access_token):
                    continue
            if source == "notion":
                # notion_connector가 id를 "notion-{page_id}" 형태로 만들어둔다. page_id 자체가
                # 대시 포함 UUID라, 접두사만 잘라내면 그대로 유효한 page_id가 된다.
                doc_id = d.metadata.get("id", "")
                page_id = doc_id[len("notion-"):] if doc_id.startswith("notion-") else None
                if not notion_access_token or not page_id or not _check_notion_access(page_id, notion_access_token):
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
            if relevant_count == 0:
                point = "검색어와 관련성이 높은 문서를 찾지 못했습니다. 다른 검색어로 다시 시도해보세요."
            else:
                point = "관련 문서가 있었지만, 현재 계정이 접근 권한을 확인할 수 없어 결과에서 제외됐습니다."
            empty_summary = {
                "title": "표시할 수 있는 결과가 없습니다",
                "keyPoints": [point],
                "decisionTrail": [],
                "actionItems": [],
            }
            return SearchResponse(documents=[], summary=empty_summary)

        # 2. LLM을 통한 요약 및 액션 아이템 추출
        summary_dict = rag_pipeline.generate_ai_summary(q, visible_docs)

        if summary_dict.get("actionItems"):
            db.upsert_action_items(user["id"], q, summary_dict["actionItems"])

        return SearchResponse(
            documents=formatted_docs,
            summary=summary_dict
        )

    except Exception as e:
        print(f"검색 중 에러: {e}")
        # 예외 발생 시 Mock 반환
        return SearchResponse(documents=mock_documents, summary=mock_summary)
