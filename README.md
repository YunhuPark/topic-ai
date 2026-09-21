# Topic Thread AI

사내에 흩어진 지식(Notion, Slack, Google Drive, GitHub, GitLab)을 한 곳에서 검색하고, AI가 핵심 요약·의사결정 흐름(Decision Trail)·액션 아이템을 자동으로 뽑아주는 사내 통합 AI 어시스턴트입니다.

기획 배경과 시장조사는 [PLANNING.md](PLANNING.md), 기능 요구사항·완료 기준은 [PRD.md](PRD.md)를 참고하세요.

## 구조

```
React (Vite) ──fetch──▶ FastAPI (backend/main.py) ──▶ Chroma (로컬 벡터DB)
                              │                              ▲
                              ▼                              │ 오프라인 배치 적재
                     OpenAI (임베딩, GPT-4o 요약)              │
                                                    backend/connectors/
                                                    ├─ notion_connector.py
                                                    ├─ slack_connector.py
                                                    ├─ gdrive_connector.py
                                                    ├─ github_connector.py
                                                    └─ gitlab_connector.py
```

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
| `GET /api/v1/search?q={query}` | 통합 검색 — 관련 문서 top-4 + AI 요약(keyPoints/decisionTrail/actionItems) |
| `GET /api/v1/stats` | 대시보드용 통계 — 총 문서 수, 연동 소스 수, 신선도 분포, 문서 목록 |
| `POST /api/v1/auth/signup` | 회원가입 (이메일+비밀번호) → JWT 토큰 발급 |
| `POST /api/v1/auth/login` | 로그인 → JWT 토큰 발급 |
| `GET /api/v1/auth/me` | 현재 로그인 사용자 정보 (`Authorization: Bearer <token>` 필요) |
| `POST /api/v1/auth/link/google` | Google access token 검증 후 계정에 연결 |
| `GET /api/v1/auth/link/{github\|gitlab\|slack\|notion}/start` / `.../callback` | GitHub/GitLab/Slack/Notion OAuth 연결 시작/콜백 |
| `GET /api/v1/auth/linked` | 이 계정에 연결된 외부 소스 목록 |
| `GET /api/v1/search-history`, `GET /api/v1/action-items` | 계정에 귀속된 검색 기록/액션아이템 조회 |

## 계정 / 권한 인지형 검색

로그인이 필수입니다 (자체 이메일+비밀번호 계정, JWT 세션). 검색 기록·액션아이템은 브라우저가 아니라
로그인한 계정에 귀속됩니다.

권한 인지형 검색은 **Google Drive, GitHub, GitLab, Slack, Notion 5개 소스 전부**에 적용돼 있습니다 —
사이드바에서 각각 계정을 연결하면, 그 사람이 실제로 접근 가능한 문서/저장소/프로젝트/채널/페이지만
검색에 노출됩니다 (연결 안 하면 그 소스는 결과에서 아예 빠집니다 — 기본 거부).

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
