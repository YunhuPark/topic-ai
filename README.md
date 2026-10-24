# Topic Thread AI

사내에 흩어진 지식(Notion, Slack, Google Drive, GitHub, GitLab)을 한 곳에서 검색하고, AI가 핵심 요약·의사결정 흐름(Decision Trail)·액션 아이템을 자동으로 뽑아주는 사내 통합 AI 어시스턴트입니다.

기획 배경과 시장조사는 [PLANNING.md](PLANNING.md), 기능 요구사항·완료 기준은 [PRD.md](PRD.md)를 참고하세요.

> **다른 노트북에서 이어서 작업한다면 [HANDOFF.md](HANDOFF.md)를 먼저 읽으세요** —
> `.env`/`app.db`/`chroma_db`는 git에 없어서 그대로 clone만 하면 앱이 안 돕니다.

## 구조

```
React (Vite) ──fetch──▶ FastAPI (backend/main.py) ──▶ Chroma (로컬 벡터DB)
                              │                              ▲
                              ▼                              │ 오프라인 배치 적재
                   backend/llm_backend.py (임베딩, 요약)       │
                   ├─ openai (기본값, gpt-4o-mini)             │
                   └─ ollama (회사 내부망/로컬 자체 호스팅)     │
                                                    backend/connectors/
                                                    ├─ notion_connector.py
                                                    ├─ slack_connector.py
                                                    ├─ gdrive_connector.py
                                                    ├─ github_connector.py
                                                    └─ gitlab_connector.py
```

LLM 백엔드는 `LLM_BACKEND` 환경변수(기본값 `openai`)로 전환합니다 — 기업 보안 정책상 외부
LLM API를 못 쓰는 환경이면 `ollama`로 바꾸고 회사 내부망에 띄운 Ollama 서버를 가리키면 됩니다
(문서 내용이 외부로 전혀 안 나감). 자세한 내용은 `backend/llm_backend.py` 상단 docstring과
`backend/.env.example` 참고.

- 프론트엔드: `src/` — React + Vite
- 백엔드: `backend/` — FastAPI + LangChain + Chroma
- 문서 적재는 오프라인 스크립트(`rag_pipeline.py`)로 하고, API 서버와 프로세스가 분리되어 있습니다.

## 시작하기

### 1. 프론트엔드

```bash
npm install
npm run dev   # http://localhost:5173
```

### 2. 백엔드

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

`backend/.env` 파일을 만들고 최소한 OpenAI 키와 JWT 서명 키를 채웁니다 (둘 다 필수):

```bash
OPENAI_API_KEY=sk-...
JWT_SECRET=아무 랜덤 문자열   # python -c "import secrets; print(secrets.token_hex(32))"
```

서버 실행:

```bash
uvicorn main:app --reload --port 8000   # http://localhost:8000
```

### 3. 문서 적재

mock 데이터로 먼저 흐름을 확인하려면:

```bash
python rag_pipeline.py --source mock
```

실제 소스를 연동하려면 아래 "커넥터 설정"을 먼저 하고:

```bash
python rag_pipeline.py --source notion
python rag_pipeline.py --source slack
python rag_pipeline.py --source gdrive
python rag_pipeline.py --source github
python rag_pipeline.py --source gitlab
```

> ⚠️ **적재 후에는 반드시 API 서버(uvicorn)를 재시작하세요.** Chroma는 다른 프로세스가 쓴 내용을
> 자동으로 다시 읽지 않습니다.

## 커넥터 설정

모든 커넥터는 읽기 전용이며, 실제 데이터를 명시적으로 공유/초대한 범위만 가져옵니다.

### Notion
1. [notion.so/my-integrations](https://www.notion.so/my-integrations)에서 Internal Integration 생성 (권한: Read content만)
2. 발급된 토큰을 `.env`의 `NOTION_TOKEN`에 입력
3. 검색되길 원하는 Notion 페이지를 열어 `···` → 연결 추가에서 방금 만든 통합 공유

> **주의 — 이건 Notion API 자체의 제약이라 이 앱이 우회할 방법이 없습니다.** Google
> Drive/GitHub/GitLab/Slack은 연동 한 번만 해두면 그 뒤로 만든 새 문서도 자동으로 계속
> 검색에 잡히지만, Notion은 그렇지 않습니다 — 페이지/데이터베이스를 새로 만들 때마다
> 위 3번 과정("···" → 연결 추가)을 그 문서에도 또 해줘야만 검색에 나옵니다("워크스페이스
> 전체 접근" 같은 옵션이 Notion API엔 아예 없음).
>
> 다행히 **공유는 하위 페이지로 상속됩니다** — 팀 문서용 최상위 페이지를 하나 정해서
> 거기에만 위 3번을 한 번 해두면, 그 페이지 "아래에" 만드는 하위 페이지는 따로 공유 안
> 해도 자동으로 같이 공유돼 검색에 잡힙니다. 팀에는 "새 문서는 반드시 이 페이지 아래에
> 만들어주세요"라고 안내하는 걸 권장합니다 — 그러면 최초 설정 한 번으로 끝나고, 그 뒤로는
> 다른 소스들과 똑같이 자동으로 동작합니다.

### Slack
1. [api.slack.com/apps](https://api.slack.com/apps) → Create New App → Blank app
2. OAuth & Permissions → Bot Token Scopes에 추가: `channels:history`, `channels:read`, `groups:history`, `groups:read`, `users:read`
3. Install to Workspace → Bot User OAuth Token(`xoxb-...`)을 `.env`의 `SLACK_BOT_TOKEN`에 입력
4. 검색되길 원하는 채널에서 `/invite @앱이름`으로 봇 초대
5. 최근 90일 이내 메시지만 대상 (`connectors/slack_connector.py`의 `SLACK_LOOKBACK_DAYS`로 조정 가능)

### Google Drive (Docs/Sheets/Slides/PDF/DOCX/XLSX/PPTX/HWPX 지원)
1. [console.cloud.google.com](https://console.cloud.google.com)에서 프로젝트 생성 → "Google Drive API"와
   "Google Sheets API" 둘 다 활성화 (Sheets 문서를 읽으려면 Sheets API도 켜야 함)
2. IAM 및 관리자 → 서비스 계정 → 서비스 계정 만들기 (역할 부여 단계는 건너뛰기)
3. 만든 서비스 계정 → 키 → 새 키 만들기 → JSON → 다운로드
4. 다운받은 파일을 `backend/gdrive_service_account.json`으로 저장
5. 서비스 계정 이메일(`...@...iam.gserviceaccount.com`)을 검색되길 원하는 파일에 뷰어로 공유

> 레거시 바이너리 `.hwp`(2014년 이전 한글 포맷)와 구버전 MS Office(`.doc`/`.xls`/`.ppt`), 스캔
> 이미지로만 된 PDF는 지원하지 않습니다 — 최신 포맷(HWPX 등)으로 다시 저장하거나 PDF로 내보내면 됩니다.

### GitHub (Issues/PR만 지원)
1. [github.com/settings/tokens](https://github.com/settings/tokens)에서 Personal Access Token 발급
2. 토큰을 `.env`의 `GITHUB_TOKEN`에 입력
3. `.env`의 `GITHUB_REPOS`에 대상 저장소를 `owner/repo,owner/repo2` 형태로 입력

### GitLab (Issues/MR만 지원)
1. GitLab 설정 → Access Tokens에서 Personal Access Token 발급 (scope: `read_api`)
2. 토큰을 `.env`의 `GITLAB_TOKEN`에 입력
3. `.env`의 `GITLAB_PROJECTS`에 대상 프로젝트를 `namespace/project,namespace/project2` 형태로 입력
4. 자체 호스팅 GitLab이면 `.env`의 `GITLAB_URL`도 설정 (기본값 `https://gitlab.com`)

## API

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/v1/search?q={query}&team_id={id}` | 통합 검색 — 관련 문서 top-4 + AI 요약(keyPoints/decisionTrail/actionItems) + 응답 단계별 소요 시간(`timing`). `team_id` 생략 시 개인 스코프. 계정당 하루 호출 한도(`DAILY_SEARCH_LIMIT`) 적용 |
| `POST /api/v1/summarize-document` | 검색 결과에서 문서 하나를 클릭했을 때 그 문서만 다시 요약. 같은 하루 호출 한도 공유 |
| `GET /api/v1/stats?team_id={id}` | 대시보드용 통계 — `team_id` 없으면 개인이 연동해서 가져온 문서만, 있으면 그 팀 멤버 전체가 가져온 문서를 합쳐서 집계 |
| `GET /api/v1/sync-status` | 연동 직후/주기적 재동기화가 지금 진행 중인 소스가 있는지, 마지막 결과(문서 수·실패 여부) |
| `POST /api/v1/auth/signup` | 회원가입 (이메일+비밀번호) → JWT 토큰 발급. `SIGNUP_ALLOWED_DOMAINS` 설정 시 그 도메인만 허용 |
| `POST /api/v1/auth/login` | 로그인 → JWT 토큰 발급 |
| `GET /api/v1/auth/me` | 현재 로그인 사용자 정보 (`Authorization: Bearer <token>` 필요) |
| `GET /api/v1/auth/google/start` / `.../callback`, `GET /api/v1/auth/kakao/start` / `.../callback` | 이메일+비밀번호 대신 Google/카카오 계정으로 로그인·가입. 아래 "소셜 로그인" 절 참고 |
| `GET /api/v1/auth/link/{google\|github\|gitlab\|slack\|notion}/start` / `.../callback` | 5개 소스 전부 같은 OAuth 팝업+콜백 패턴 — 연결 성공 시 그 계정 문서 전체를 백그라운드에서 자동 수집 |
| `DELETE /api/v1/auth/link/{provider}` | 연동 해제 — 그 사람이 이 소스로 가져왔던 문서도 함께 정리 |
| `GET /api/v1/auth/linked` | 이 계정에 연결된 외부 소스 목록 |
| `GET/POST/PATCH/DELETE /api/v1/people` | 동명이인 별칭 사전(정식 이름+별칭 등록) — `team_id` 주면 팀 전체 공유, 없으면 개인 전용 |
| `GET/POST /api/v1/teams`, `POST /api/v1/teams/{id}/invites`, `POST /api/v1/teams/join`, `GET/DELETE /api/v1/teams/{id}/members` | 팀 생성/초대 코드 발급/참여/멤버 조회·제거 — 초대 코드 방식(SMTP 불필요) |
| `GET /api/v1/search-history`, `GET /api/v1/action-items` | 계정(또는 팀)에 귀속된 검색 기록/할 일 조회 |
| `DELETE /api/v1/action-items/{id}` | 할 일 삭제 |

## 계정 / 권한 인지형 검색

로그인이 필수입니다 (자체 이메일+비밀번호 계정, 또는 아래 소셜 로그인, JWT 세션). 검색 기록·
액션아이템은 브라우저가 아니라 로그인한 계정에 귀속됩니다.

권한 인지형 검색은 **Google Drive, GitHub, GitLab, Slack, Notion 5개 소스 전부**에 적용돼 있습니다 —
사이드바에서 각각 계정을 연결하면, 그 사람이 실제로 접근 가능한 문서/저장소/프로젝트/채널/페이지만
검색에 노출됩니다 (연결 안 하면 그 소스는 결과에서 아예 빠집니다 — 기본 거부).

### 소셜 로그인 (Google / 카카오)

이메일 인증·비밀번호 재설정 절차가 없는 상태에서 이메일+비밀번호 가입만 제공하면, 가입 때 적은
이메일이 진짜 본인 것인지 검증할 방법이 없고 비밀번호를 잊어도 복구할 방법이 없습니다. Google/
카카오 로그인을 추가해 이 문제를 우회합니다 — 두 플랫폼이 이미 검증한 이메일/신원을 그대로
신뢰합니다.

- **계정 연결(Drive 접근 등)과는 완전히 별개**입니다 — 로그인용 Google OAuth는 `openid email`
  스코프만 요청해서, 로그인하려고 눌렀는데 Drive 접근까지 한꺼번에 동의하라고 뜨는 과한 동의
  요청을 피합니다. 같은 Google OAuth 클라이언트(ID/시크릿)를 재사용하되 콜백 경로만 다릅니다
  (`GOOGLE_LOGIN_REDIRECT_URI`를 Google Cloud Console에 "승인된 리디렉션 URI"로 추가 등록 필요).
- **카카오는 이메일을 아예 못 받을 수 있습니다** — "카카오계정(이메일)" 동의항목이 비즈 앱
  전환 없이는 막혀 있는 경우가 흔합니다. 그래서 카카오 로그인은 이메일이 아니라 카카오 고유
  숫자 id를 진짜 식별자로 씁니다. 이메일을 받으면 그 이메일로, 못 받으면
  `kakao-{id}@no-email.topicthread.local` 형태의 가짜(수신 불가) 이메일로 계정을 만듭니다 —
  로그인 자체는 이메일 동의 여부와 무관하게 항상 됩니다.
- 신규 계정으로는 로그인 전용 비밀번호가 없습니다(DB에는 어떤 실제 비밀번호와도 안 맞는 랜덤
  해시가 들어갑니다) — 이메일+비밀번호 로그인은 자동으로 막히고, 다음에도 같은 소셜 계정으로
  로그인해야 합니다.
- **`SIGNUP_ALLOWED_DOMAINS`(도메인 제한)는 소셜 로그인의 신규 계정 생성에도 똑같이 적용됩니다**
  — Google은 받은 이메일 도메인을 검사하고, 카카오는 이메일 동의를 못 받은 상태(placeholder로
  갈 상황)라면 도메인 제한이 켜진 한 아예 신규 가입을 거부합니다(회사 소속을 증명할 방법이
  없으므로). 이미 만들어진 계정은 제한이 나중에 켜져도 계속 로그인 가능합니다(이메일+비밀번호
  `signup()`/`login()`의 기존 비대칭과 동일한 원칙).
- placeholder 이메일로 가입했던 카카오 계정이 나중에(동의항목을 켜는 등) 진짜 이메일을
  보내주면, 다음 로그인 때 자동으로 그 진짜 이메일로 승격됩니다 — 화면에 계속
  `kakao-{id}@no-email...` 같은 가짜 주소가 보이지 않습니다. 그 이메일을 이미 다른 계정이
  쓰고 있으면(드문 충돌) 승격하지 않고 기존 계정을 그대로 유지합니다.

카카오 앱 설정: developers.kakao.com → 앱 생성 → 카카오 로그인 활성화 → **플랫폼 키 → REST API
키** 상세 화면에서 Redirect URI 등록(이메일+비밀번호 가입 폼이 아니라 "카카오 로그인" 메뉴가
아니라는 점 주의 — 콘솔 버전에 따라 위치가 바뀐 적 있음) → REST API 키(`KAKAO_CLIENT_ID`)와
선택적으로 생성한 Client Secret(`KAKAO_CLIENT_SECRET`)을 `.env`에 입력.

### 팀 공유

사이드바 "내 팀"에서 팀을 만들고 초대 코드(SMTP 없이, Discord/Slack 스타일)로 멤버를 초대할 수
있습니다. 팀을 선택하면 별칭 사전·할 일 리스트·대시보드 통계가 팀 전체와 공유되지만, **검색
결과(문서 열람) 범위는 공유되지 않습니다** — 팀원이 가져온 문서라도, 보는 사람이 그 소스에
직접 연동돼 있지 않으면 여전히 안 보입니다. 원본 소스(Notion/Drive/GitHub 등)의 실제 접근
권한을 이 앱이 우회하지 않는다는 원칙을 유지하기 위함입니다.

- **Google Drive**: "Google Drive 연결" — GitHub/GitLab과 같은 표준 OAuth Authorization Code
  플로우입니다(`GOOGLE_OAUTH_CLIENT_ID`/`SECRET` 필요). refresh_token이 서버에 저장되므로 한 번
  연결하면 계속 유지되고, 자동 재동기화 대상에도 포함됩니다.
- **GitHub / GitLab**: "GitHub 연결" / "GitLab 연결" — 둘 다 표준 OAuth Authorization Code 플로우라
  별도로 `GITHUB_OAUTH_CLIENT_ID`/`SECRET`, `GITLAB_OAUTH_CLIENT_ID`/`SECRET`이 `.env`에 필요합니다
  (아래 커넥터용 `GITHUB_TOKEN`/`GITLAB_TOKEN`과는 다른 앱). access token은 서버에 저장되어 한 번
  연결하면 계속 유지됩니다.
- **Slack**: "Slack 연결" — 수집용 봇(`SLACK_BOT_TOKEN`)과 같은 Slack 앱에 "User Token Scopes"만
  추가하면 됩니다(새 앱 필요 없음). 연결 시 발급되는 건 봇 토큰이 아니라 그 사람 본인 권한을
  나타내는 사용자 토큰이며, 검색 시 `conversations.history`로 그 채널을 실제로 읽을 수 있는지
  확인합니다 (공개 채널이라도 멤버가 아니면 제외).
- **Notion**: "Notion 연결" — 수집용 `NOTION_TOKEN`(Internal Integration)과는 별개로 **OAuth 타입
  통합**을 새로 만들어야 합니다. 동의 화면에서 그 사람이 직접 "이 통합에 공유할 페이지"를 고르고,
  그렇게 고른 페이지에만 접근 가능한 토큰을 받습니다 — 그래서 수집용 통합으로 이미 공유해둔
  페이지라도 이 OAuth 연결에서 다시 선택하지 않으면 검색에 노출되지 않습니다.

(PRD.md Phase 6 참고)

### 계정 연결용 OAuth 앱 설정 (커넥터 설정과 별개)

**Google (Drive 권한 필터링 + 자동 재동기화용)**
1. [console.cloud.google.com](https://console.cloud.google.com) → 프로젝트 → "Google Drive API"와
   "Google Sheets API" 활성화 → API 및 서비스 → **OAuth 동의 화면** 설정 (외부, 테스트 모드면 테스트
   사용자에 본인 계정 추가 — 검증 안 받은 앱은 테스트 사용자만 로그인 가능)
2. API 및 서비스 → **사용자 인증 정보 → OAuth 클라이언트 ID → 웹 애플리케이션**, 승인된 리디렉션
   URI에 `http://localhost:8000/api/v1/auth/link/google/callback` 추가 (GitHub/GitLab과 같은 서버
   사이드 플로우라, 클라이언트 시크릿이 있는 이 타입이어야 함 — 예전 버전이 쓰던 프론트 전용
   클라이언트 ID/`VITE_GOOGLE_CLIENT_ID`와는 다름)
3. 발급된 Client ID/Secret을 `backend/.env`의 `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET`에 입력

**GitHub (저장소 권한 필터링용)**
1. [github.com/settings/developers](https://github.com/settings/developers) → OAuth Apps → **New OAuth App**
2. Authorization callback URL: `http://localhost:8000/api/v1/auth/link/github/callback`
3. 발급된 Client ID/Secret을 `backend/.env`의 `GITHUB_OAUTH_CLIENT_ID`/`GITHUB_OAUTH_CLIENT_SECRET`에 입력

**GitLab (프로젝트 권한 필터링용)**
1. GitLab → 프로필 → **Applications → Add new application**
2. Redirect URI: `http://localhost:8000/api/v1/auth/link/gitlab/callback`, Scope: `read_api`만 체크
3. 발급된 Application ID/Secret을 `backend/.env`의 `GITLAB_OAUTH_CLIENT_ID`/`GITLAB_OAUTH_CLIENT_SECRET`에 입력

**Slack (채널 권한 필터링용, 커넥터 설정에서 만든 앱 재사용)**
1. [api.slack.com/apps](https://api.slack.com/apps) → 커넥터 설정 때 만든 앱 선택
2. **OAuth & Permissions** → *User Token Scopes*에 추가: `channels:history`, `groups:history`, `channels:read`, `groups:read`
3. 같은 페이지 **Redirect URLs**에 `http://127.0.0.1:8000/api/v1/auth/link/slack/callback` 추가 후 저장
   (Slack이 `localhost` 호스트를 유효하지 않은 redirect URL로 거부하는 경우가 있어 `127.0.0.1`을 씀 —
   이 경우 `backend/.env`의 `SLACK_OAUTH_REDIRECT_URI`도 같은 값으로 맞춰야 함)
4. **Basic Information** 페이지의 App Credentials에서 Client ID/Secret을 `backend/.env`의
   `SLACK_OAUTH_CLIENT_ID`/`SLACK_OAUTH_CLIENT_SECRET`에 입력

**Notion (페이지 권한 필터링용, 수집용 Internal Integration과는 별개로 새로 생성)**
1. [notion.so/my-integrations](https://www.notion.so/my-integrations) (또는 Notion 개발자 도구 →
   연결) → **신규 연결**, 인증 방법은 반드시 **OAuth** 선택 (액세스 토큰이 아님 — 그건 수집용 방식)
2. 연결을 만들면 뜨는 설정 화면의 **리디렉션 URI**에 `http://localhost:8000/api/v1/auth/link/notion/callback` 입력
3. **기능** 섹션에서 "콘텐츠 읽기"만 남기고 "콘텐츠 업데이트"/"콘텐츠 삽입"은 꺼서 읽기 전용으로 제한
   (사용자 기능은 "이메일 주소를 포함한 사용자 정보 읽기" 추천 — 연결된 계정 표시 이름에 쓰임)
4. 클라이언트 ID/시크릿(시크릿은 눈 아이콘으로 표시)을 `backend/.env`의
   `NOTION_OAUTH_CLIENT_ID`/`NOTION_OAUTH_CLIENT_SECRET`에 입력

## 자동 재동기화

계정 연동 시점에 그 사람이 접근 가능한 문서 전체를 수집하고, 그 이후로도 **5개 소스 전부**를
`AUTO_RESYNC_INTERVAL_SECONDS`(기본 900초=15분)마다 백그라운드에서 다시 확인합니다
(`backend/.env`에서 조정 가능).

재동기화는 **증분**입니다 — 목록 조회는 매번 하지만(원본에서 삭제된 문서를 알아내야 하므로),
본문을 다시 받아 임베딩하는 건 원본의 수정 시각이나 내용이 실제로 바뀐 문서뿐입니다. 그래서
문서가 그대로면 주기당 임베딩 비용이 0에 수렴합니다. 원본에서 삭제되거나 접근 권한을 잃은
문서는 자동으로 정리되고, 사이드바에서 **연동을 해제하면** 그 소스로 가져왔던 문서도 함께
정리됩니다.

## 배포

지금까지는 로컬/사내망에서 `localhost`로만 써왔지만, 실제 서버에 올릴 때 필요한 설정은 대부분
환경변수로 이미 빠져 있습니다 — 소스를 고칠 필요는 없고 아래만 맞추면 됩니다. 어떤 값들이
있는지는 `backend/.env.example`과 레포 루트의 `.env.example`을 참고(각각 `backend/.env`,
`.env`로 복사해서 채우면 됨).

### Render로 배포하기

레포 루트의 `render.yaml`(Blueprint)이 백엔드+프론트엔드 정적 사이트를 한 번에 정의해둔다.
Render 대시보드 → New → **Blueprint** → 이 GitHub 저장소 연결하면 자동으로 두 서비스가
만들어진다. 주의할 점:

- **지금은 포트폴리오/데모 단계라 Free 플랜 기준으로 작성해뒀다** — 영구 디스크가 없어서
  15분 비활동 후 슬립했다 깨어날 때마다 컨테이너가 새로 생성되며 `app.db`/`chroma_db`가
  초기화된다. 회원가입→연동→검색 자체는 매번 되지만, 미리 쌓아둔 데모 데이터는 유지되지
  않는다. 실사용(데이터가 계속 유지돼야 함)으로 전환할 때는 `render.yaml` 상단 주석에
  적어둔 3단계(Starter 플랜 전환 + disk 블록 주석 해제 + `DB_PATH`/`CHROMA_PERSIST_DIR`
  환경변수 추가)만 하면 된다 — 코드 수정은 이미 끝나 있다.
- `render.yaml`에 `sync: false`로 표시된 환경변수(API 키·시크릿 등)는 값을 안 적어뒀다 —
  Blueprint 적용 후 Render 대시보드에서 각 서비스의 Environment 탭에 직접 입력해야 한다.
- 서비스 이름(`topic-thread-backend`/`topic-thread-frontend`)이 이미 다른 사람이 쓰고
  있으면 Render가 임의 접미사를 붙인 다른 URL을 배정한다 — 그러면 `render.yaml`에 미리
  적어둔 `FRONTEND_ORIGINS`/`VITE_API_BASE`/각 `*_OAUTH_REDIRECT_URI` 값을 실제 배정된
  URL로 맞춰서 대시보드에서 수정해야 한다.
- OAuth 앱(Google/GitHub/GitLab/Slack/Notion) 콘솔에도 각각 실제 배정된 백엔드 URL로
  Redirect URI를 등록해야 한다 (아래 "커넥터 설정" 절 참고).

### 직접 VM에 배포하기 (Oracle Cloud 등)

#### 백엔드
1. **`FRONTEND_ORIGINS`**(`backend/.env`) — 배포한 프론트엔드 주소로 설정. 콤마로 여러 개 가능
   (예: `https://topic-thread.example.com`). OAuth 콜백이 `postMessage`를 보낼 origin과 CORS
   허용 origin이 둘 다 이 값을 쓴다.
2. **각 소스의 `*_OAUTH_REDIRECT_URI`** — GitHub/GitLab/Slack/Notion/Google 콘솔에 등록해둔
   Redirect URI를 `http://localhost:8000/...`에서 실제 배포 도메인으로 바꾸고, `.env`의 대응
   환경변수(`SLACK_OAUTH_REDIRECT_URI` 등, 나머지는 도메인만 바뀌면 코드가 자동으로 맞춤)도
   같이 바꾼다. **다섯 소스 전부** 각자 콘솔에서 다시 등록해야 한다 (OAuth 앱 설정 절 참고).
3. **단일 워커로만 실행할 것** — 권한 확인 캐시(`_permission_cache`)와 동기화 진행 상태
   (`rag_pipeline._sync_status`)가 프로세스 메모리에만 있다. `--workers 2` 이상으로 띄우면
   요청이 어느 워커로 가느냐에 따라 캐시가 안 맞거나 `/api/v1/sync-status`가 다른 워커의
   진행 상황을 못 보는 문제가 생긴다. 여러 워커가 꼭 필요해지면 이 상태를 Redis 등 공유
   저장소로 옮겨야 한다.
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000   # --reload 빼고, --workers 지정하지 않음(기본 1)
   ```
4. **`backend/app.db`(SQLite)와 `backend/chroma_db/`는 영속 디스크에 있어야** 한다 — 컨테이너
   재배포 때 날아가면 계정·연동·색인 문서가 전부 사라진다. 코드와 다른 경로에 디스크를
   마운트하는 환경(컨테이너 등)이면 `DB_PATH`/`CHROMA_PERSIST_DIR`(`backend/.env`)로 그
   경로를 가리키면 된다 — 둘 다 안 주면 기존처럼 `backend/` 디렉터리 안을 그대로 쓴다.
5. `SIGNUP_ALLOWED_DOMAINS`(`backend/.env`, 콤마로 여러 도메인)를 설정하면 그 도메인 이메일만
   회원가입할 수 있다. 사내 배포라면 설정을 권장 — 비워두면(기본값) 아무나 가입 가능하다.
6. `DAILY_SEARCH_LIMIT`(`backend/.env`, 기본값 50) — 계정당 하루 검색+문서 재요약 합산 한도.
   도메인 제한 없이 공개 배포(포트폴리오/데모 등)할 때, 낯선 방문자가 검색을 반복해서
   OpenAI 크레딧을 소진시키는 걸 막기 위한 안전장치. 넘으면 429와 함께 한도 메시지를 반환한다.

#### 프론트엔드
`VITE_API_BASE`를 배포한 백엔드 주소로 설정하고 빌드한다 (안 주면 `http://localhost:8000` 기본값):
```bash
VITE_API_BASE=https://api.example.com npm run build
```

### 아직 안 된 것
- 비밀번호 재설정(SMTP 발신 필요) — 이메일+비밀번호 계정은 여전히 없음, 계정 잠기면 관리자가
  DB에서 직접 처리해야 함. Google/카카오 로그인은 애초에 비밀번호가 없어서 이 문제 자체가
  없음 — 사실상 "비밀번호 잊어버림" 문제의 실질적 해법은 소셜 로그인 쪽으로 유도하는 것
- Render **Starter 플랜 + 영구 디스크 전환** — 지금은 포트폴리오/데모 단계라 Free 플랜으로
  두고 있음(데이터가 슬립할 때마다 초기화됨). 실사용 전환 시 `render.yaml` 상단 주석의
  3단계만 따라가면 됨(코드 변경은 불필요).

## 향후 연동 계획

지금은 Notion·Slack·Google Drive·GitHub·GitLab 5개 소스만 지원합니다. 경쟁 제품(Glean 등)은
40개 이상의 커넥터를 지원하지만, 이 프로젝트는 "소스를 무한정 늘리기"보다 "권한 인지형 검색·
팀 공유·AI 요약을 소수 소스에 깊게 통합"하는 쪽을 차별점으로 삼고 있습니다 — 그래서 아래는
확정된 로드맵이 아니라, 실제 수요를 보며 우선순위를 정할 **후보**입니다.

- **Jira + Confluence (Atlassian)** — 가장 자연스러운 다음 후보. 지금 GitHub/GitLab(코드)은
  있는데 이슈 트래킹·위키가 없어서, 개발팀이 실제로 쓰는 도구 세트와 맞추면 Confluence를 쓰는
  회사(Notion 대신)도 그대로 흡수할 수 있다.
- **Microsoft 365 (Outlook / SharePoint / Teams)** — 지금 Google Drive·Slack만 있어서 MS 365
  중심 회사는 애초에 못 쓴다. 시장을 넓히는 효과가 크다.
- **Figma** — 개발팀 대상이면 디자인 문서도 검색 대상이 된다. 비교적 가벼운 추가.
- **잔디(JANDI) / Dooray!** — 한국 로컬 협업툴. 해외 경쟁 제품들이 안 가진 한국 시장 특화
  차별점이 될 수 있다.

Dropbox/Box, Zoom 녹취록 등은 기존 기능(Drive, Slack)과 역할이 겹쳐 우선순위를 낮게 뒀다.

## 알려진 운영 이슈

- Chroma는 다른 프로세스가 쓴 내용을 자동으로 다시 읽지 않으므로, 적재 스크립트 실행 후 API 서버를 재시작해야 합니다.
- Windows 콘솔(cp949)은 이모지를 못 그려서, 로그에 이모지를 쓰면 print 자체가 예외를 던질 수 있습니다 (`main.py`/`rag_pipeline.py` 상단에서 UTF-8로 재설정해 처리 중).
- Google Drive 커넥터는 Docs/Sheets/Slides/PDF/DOCX/XLSX/PPTX/HWPX를 지원합니다. 스캔 이미지로만 된 PDF, 레거시 `.hwp`, 구버전 MS Office(`.doc`/`.xls`/`.ppt`)는 범위 밖입니다.

## 프론트엔드 상세

React + Vite. Oxlint로 린팅합니다.

```bash
npm run lint     # oxlint
npm run build    # 프로덕션 빌드
```

## 회고

핵심 설계 원칙은 **"검색은 공유해도, 권한은 공유하지 않는다"**입니다 — 팀원이 가져온 문서라도,
보는 사람이 그 소스에 직접 연동돼 있지 않으면 여전히 안 보입니다. 색인을 공유 저장소처럼
만들면 구현은 쉽지만, 원본 소스(Notion·Drive 등)에서 실제로는 권한이 없는 사람에게도 내용이
새어 나갑니다. 그래서 모든 문서 열람을 "보는 사람 본인의 실시간 OAuth 토큰으로 매 요청마다
재확인"하는 쪽을 택했습니다. 이 프로젝트를 혼자 설계부터 배포까지 끌고 가며 부딪힌 문제들 중
기억에 남는 다섯 가지를 정리합니다.

**1. 프로덕션에서 터진 UNIQUE 제약.** 팀 공유 기능을 추가하며 별칭 테이블에 `team_id`를
붙였는데, 기존 `UNIQUE(user_id, display_name)` 제약은 스코프를 모른 채 이름 중복만 봤습니다.
실사용 중인 계정이 개인 스코프에 등록해둔 이름을 팀 스코프에도 등록하려다 500 에러가 났습니다.
SQLite는 `ALTER TABLE`로 제약을 못 바꿔서 테이블을 재생성하고, 스코프별 파셜 유니크 인덱스
(`WHERE team_id IS NULL` / `WHERE team_id IS NOT NULL`)로 바꿨습니다. 실제 DB에 적용하기 전
백업과 스크래치 사본에서 먼저 재현·검증하는 걸 원칙으로 삼았습니다 — 스코프가 늘어나는 컬럼을
추가할 땐 제약 조건도 같이 다시 설계해야 한다는 걸 운영 중 사고로 배웠습니다.

**2. LLM 비용 — "더 좋은 모델"이 아니라 "지속 가능한 구조".** 테스트 중 OpenAI 크레딧이
소진되어 검색이 전부 막혔습니다. 무료 플랫폼(Gemini·Ollama)으로 당장 갈아타는 대신, 실제
회사에서 여러 명이 동시에 쓰기 시작하면 무료 티어는 요청 제한에 걸려 업무시간에 장애가 날 수
있다고 판단했습니다. `gpt-4o` → `gpt-4o-mini` 전환으로 비용을 약 1/15로 줄이고, 여기서 더
나아가 외부 LLM API 자체를 못 쓰는 보안 정책을 가진 회사도 대응할 수 있도록 `LLM_BACKEND`
환경변수로 OpenAI와 사내망 자체 호스팅(Ollama)을 전환 가능한 추상화 계층을 추가했습니다.
비용 문제의 답은 항상 "더 싼 것"이 아니라 "사용량이 늘어도 무너지지 않는 것"이었습니다.

**3. Oracle Cloud와 사흘, 그리고 손절.** 무료 서버 호스팅으로 Oracle Cloud Always Free
Tier를 선택했는데, 카드 인증은 성공했지만 계정 생성 자체가 모호한 에러로 반복 실패했습니다.
고객지원도 "처리할 수 없다"는 답변만 돌아왔습니다. 더 매달리는 대신 플랫폼 자체를
재검토했습니다 — Vercel(서버리스라 SQLite 영구 디스크·백그라운드 재동기화 스레드와 안 맞음)과
Render(상시 구동 컨테이너)의 구조적 차이를 비교해 Render로 전환하고, 지금 단계(포트폴리오)에
맞춰 Free 플랜으로 배포했습니다. 막힌 길에서 "조금만 더"보다, 대안의 구조적 트레이드오프를
먼저 분석하고 빠르게 전환하는 판단이 더 나을 때가 있습니다.

**4. 내가 만든 기능의 보안 구멍을 내가 찾다.** 이메일 인증이 없어 비밀번호 재설정도
불가능한 문제를 Google·카카오 로그인으로 우회 해결한 뒤, 사내 전용 도메인 제한
(`SIGNUP_ALLOWED_DOMAINS`)을 소셜 로그인에도 걸었는지 다시 점검했습니다. 이메일+비밀번호
가입에만 도메인 검사가 걸려 있고, 새로 만든 두 로그인 경로는 전혀 검사하지 않고 있었습니다 —
도메인 제한을 켜도 개인 Gmail·카카오 계정으로 그냥 우회되는 구멍이었습니다. 신규 계정을 만들
때만(기존 계정 로그인은 유지) 도메인을 검사하도록 통일했고, 카카오처럼 동의항목 제약으로
이메일조차 못 받는 경우는 도메인 제한이 켜진 한 가입 자체를 거부하도록 설계해 6개 시나리오로
격리 테스트했습니다. 같은 보안 규칙이라도 인증 경로가 늘어날 때마다 모든 경로에 일관되게
적용되는지 점검해야 한다는 걸 배웠습니다 — 하나만 빠뜨려도 나머지는 전부 무력화됩니다.

**5. 팀 기능, 뭘 공유하고 뭘 공유하지 않을지.** 여러 명이 같이 쓰는 팀 기능을 설계하며,
팀원이 연동한 문서를 다른 팀원도 검색 결과에서 볼 수 있게 할지 고민했습니다. 그렇게 하면
구현은 쉽지만, 원본 소스에서 실제 권한이 없는 문서까지 앱이 우회해서 보여주는 셈이 됩니다.
"앱이 원본 권한을 절대 우회하지 않는다"는 원칙을 지키기 위해, 할 일 리스트·별칭 사전·통계
같은 앱 내부 메타데이터만 팀 단위로 공유하고, 문서 열람은 각자의 실시간 OAuth 권한 그대로
유지했습니다.

기능 하나하나는 어렵지 않았습니다. 어려웠던 건 "이 결정이 나중에 어떤 제약을 만드는가"를
매번 다시 묻는 것이었습니다 — 스키마에 컬럼 하나를 더할 때, 더 싼 모델로 바꿀 때, 로그인
방법을 하나 더 추가할 때마다 기존에 세워둔 원칙(권한 우회 금지, 도메인 제한, 비용 지속
가능성)이 여전히 지켜지고 있는지 되짚어야 했습니다. 특히 4번처럼, 제가 직접 짠 기능의 허점을
나중에 스스로 발견하고 고친 경험이 남았습니다 — 기능을 추가하는 속도만큼, 추가된 기능이
기존 원칙을 깨지 않았는지 확인하는 습관이 중요하다는 걸 이번 프로젝트에서 체감했습니다.
