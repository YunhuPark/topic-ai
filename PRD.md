# PRD — Topic Thread AI

> 이 문서는 [PLANNING.md](PLANNING.md)(기획서: 왜/시장/차별화)를 전제로, **무엇을 어떻게 만들지**를
> 엔지니어링 관점에서 못 박는 문서다. 기획 방향이 바뀌면 PLANNING.md를 먼저 고치고 여기를 따라 고친다.

## 0. 범위 정의

| Phase | 내용 | 상태 |
|---|---|---|
| Phase 0 | mock 데이터로 통합검색 + AI 요약 파이프라인 검증 | ✅ 완료 |
| Phase 1 | Notion 연동 (읽기 전용) | ✅ 완료 |
| Phase 2 | Slack 연동 (읽기 전용) | ✅ 완료 |
| Phase 3 | Google Drive 연동 (읽기 전용, Google Docs 한정) | ✅ 완료 |
| Phase 4 | GitHub 연동 (Issues/PR, 읽기 전용) | ✅ 완료 |
| Phase 5 | GitLab 연동 (Issues/MR, 읽기 전용) | ✅ 완료 |
| Phase 6a | 자체 계정 시스템 (이메일+비밀번호 회원가입/로그인, JWT 세션, 로그인 필수 전환) | ✅ 완료 |
| Phase 6b | Google 계정 연결 + Google Drive 문서 권한 필터링 | ✅ 완료 |
| Phase 6c | GitHub 계정 연결 + 저장소 권한 필터링 | ✅ 완료 |
| Phase 6d | GitLab 계정 연결 + 프로젝트 권한 필터링 | ✅ 완료 (GitHub와 코드 공유 — `auth.get_oauth_authorize_url`/`complete_oauth_link`) |
| Phase 6e | Slack 계정 연결 + 채널 권한 필터링 | ✅ 완료 |
| Phase 6f | Notion 계정 연결 + 페이지 권한 필터링 | ✅ 완료 |

**참고**: PLANNING.md의 "Jira/ClickUp/Linear"는 시장조사에서의 비교 대상(우리가 액션아이템을 자동 추출한다는
차별화를 설명하기 위한 참고 도구)일 뿐, 실제로 연동하거나 내보내기를 구현할 대상이 아니다. 이 프로젝트는
**어디까지나 "여러 외부 소스(Notion/Slack/Drive/Git 등)의 자료를 한 곳에서 검색"하는 사내 통합 AI
어시스턴트**이며, 액션아이템/디시전 트레일은 그 검색 결과 위에 우리 서비스 안에서 보여주는 기능이다.
외부 태스크 관리 도구로 데이터를 내보내는 기능은 범위에 없다.

**전체 프로젝트 Out of scope (재확인)**: 쓰기 작업(각 소스에 다시 쓰기), 다국어 UI, 실시간 웹훅 동기화 —
전부 폴링/수동 재적재 기반으로 시작한다.

## 1. 유저 스토리

- PM/기획자로서, 특정 주제를 검색하면 Notion/Slack에 흩어진 관련 문서·대화를 **한 화면에서** 보고 싶다.
- PM/기획자로서, 검색 결과를 다 읽지 않아도 **핵심 요약·아직 안 끝난 일**을 바로 파악하고 싶다.
- 신규 합류자로서, 특정 주제의 **의사결정이 언제 어떻게 났는지** 시간순으로 보고 싶다.

(전체 페르소나는 [PLANNING.md §2](PLANNING.md#2-타겟-유저) 참고)

## 2. 시스템 구성

```
React(Vite) ──fetch──▶ FastAPI(main.py) ──▶ Chroma(vector DB, 로컬 디스크)
                              │                     ▲
                              ▼                     │ 오프라인 배치 적재
                     OpenAI (embedding, gpt-4o)      │
                                            connectors/
                                            ├─ notion_connector.py (완료)
                                            └─ slack_connector.py (이번 PRD)
```

- 적재는 **오프라인 스크립트**(`python rag_pipeline.py --source {notion|slack}`)로 하고, 서비스 중인 API 서버와는
  분리되어 있다. ⚠️ **적재 후에는 API 서버를 재시작해야 반영된다** (Chroma가 다른 프로세스의 쓰기를 자동으로
  다시 읽지 않는 것을 Phase 1에서 확인함 — Definition of Done에 포함).

## 3. 데이터 모델

모든 커넥터는 아래 공통 dict 포맷으로 문서를 만들어 `rag_pipeline.ingest_documents()`에 넘긴다
([models.py](backend/models.py) `Document`와 대응):

| 필드 | 타입 | 규칙 |
|---|---|---|
| `id` | str | 소스별 접두사 필수 (`notion-{page_id}`, `slack-{channel_id}-{thread_ts}`) — 소스 다른 문서끼리 id 충돌 방지 |
| `title` | str | 없으면 안 됨 (Phase 1에서 title 누락 시 검색결과가 전부 "문서"로 뜨는 버그를 이미 겪음) |
| `source` | str | `notion` \| `slack` \| `gdrive` |
| `author` | str | 표시용 사람 이름. 못 찾으면 `"알 수 없음"` |
| `date` | str | `YYYY-MM-DD` |
| `content` | str | 임베딩에 쓰일 본문 전체 텍스트 |
| `tags` | list[str] | 소스명 등 최소 1개 |

응답 스키마(`Summary`, `ActionItem`, `DecisionTrailItem`)는 기존 [models.py](backend/models.py) 그대로 유지 — 신규 필드 추가 없음.

## 4. 기능 요구사항

### FR-1. 통합 검색 API (완료)
- `GET /api/v1/search?q={query}` — Chroma 유사도 검색 top-4 반환
- AC: 쿼리와 무관한 문서가 섞이지 않고, 응답에 mock 폴백이 섞이지 않는다 (OPENAI_API_KEY 정상일 때)

### FR-2. AI 요약/디시전 트레일/액션아이템 생성 (완료)
- 검색된 문서들을 컨텍스트로 GPT-4o 호출, `Summary` 스키마로 파싱
- AC: 모든 텍스트 필드가 한국어로 반환된다 (Phase 1에서 영어로 새는 문제 확인 후 프롬프트에 명시함)

### FR-3. Notion 커넥터 (완료)
- 통합에 공유된 페이지 전체를 `/search`로 조회 → 블록 재귀 순회로 본문 추출
- AC: 토큰 미설정 시 트레이스백이 아니라 사람이 읽을 수 있는 에러 메시지로 실패한다

### FR-4. Slack 커넥터 (신규 — 이번 PRD 대상)

**연동 방식**: Slack App(Bot Token, `xoxb-`) 생성 후 원하는 채널에 봇을 초대(`/invite @앱이름`).
Notion과 달리 Slack은 "봇이 초대된 채널"만 읽을 수 있다 — 워크스페이스 전체 자동 스캔은 안 됨(권한 밖).

**가져올 범위 (결정 사항)**
- 봇이 멤버로 초대된 채널만 대상 (`conversations.list` + `is_member` 필터)
- 채널별 최근 **90일** 이내 메시지만 가져온다 (`conversations.history` + `oldest` 파라미터). 90일은 설정 가능한
  상수로 코드에 둔다 (하드코딩 금지, `SLACK_LOOKBACK_DAYS` 같은 상수 하나로)
- 스레드 답글(`conversations.replies`)도 포함한다 — 의사결정이 스레드 안에서 나는 경우가 많음
- 봇/시스템 메시지(`subtype`이 있는 메시지 중 `bot_message`, `channel_join` 등)는 제외

**문서 단위 (결정 사항)**
- 채널 전체를 문서 하나로 뭉치지 않는다 (너무 커서 임베딩 품질/토큰 낭비). **연속된 대화 묶음(스레드 1개,
  또는 스레드가 없는 경우 같은 날짜의 연속 메시지)을 문서 1개**로 만든다 — mock 데이터의
  `#marketing 채널 — 캠페인 킥오프 미팅 논의` 문서 형태를 실제 데이터로 재현하는 것과 동일한 그레인
- `title`은 LLM 없이 규칙 기반으로 생성: `#{channel_name} — {첫 메시지 앞 30자}...`
- `author`는 스레드의 첫 메시지 작성자 (Slack `users.info`로 이름 resolve, 캐싱)

**AC (완료 기준)**
- [x] `backend/connectors/slack_connector.py`가 봇이 속한 채널 목록을 가져온다
- [x] 각 채널에서 최근 90일 메시지 + 스레드 답글을 위 "문서 단위" 규칙대로 묶어 공통 dict 포맷으로 변환한다
- [x] `python rag_pipeline.py --source slack` 실행 시 Vector DB에 정상 적재된다
- [x] 토큰 미설정/봇이 채널에 없음 등 실패 케이스가 트레이스백 없이 명확한 한국어 에러로 안내된다
- [x] 서버 재시작 후 실제 Slack 채널 내용으로 검색·요약이 되는 것을 curl/브라우저로 검증함

### FR-5. Google Drive 커넥터 (신규 — 이번 PRD 대상)

**연동 방식**: Notion/Slack과 달리 Drive는 "앱 토큰 하나로 사용자 권한 위임"이 안 되므로, **서비스 계정
(Service Account)** 방식을 쓴다 — GCP에서 서비스 계정을 만들면 `xxx@xxx.iam.gserviceaccount.com` 같은
이메일이 생기고, 이 이메일에 Drive에서 파일/폴더를 "공유"하면 그 서비스 계정이 API로 읽을 수 있다.
Notion의 "통합에 페이지 공유하기"와 동일한 사용자 경험을 유지하기 위한 선택.

**범위 (결정 사항)**
- **Google Docs만 지원** (mimeType `application/vnd.google-apps.document`). Sheets/Slides/PDF는 텍스트 추출
  방식이 달라 이번 Phase 범위에서 제외 — Out of scope로 명시
- 서비스 계정에 공유된 파일 전체를 `files.list()`로 조회 (별도 폴더 스코프 제한 없음, 공유 자체가 스코프 역할)
- 문서 단위: 파일 하나 = 문서 하나 (Notion과 동일한 그레인)

**AC (완료 기준)**
- [x] `backend/connectors/gdrive_connector.py`가 서비스 계정에 공유된 Google Docs 목록을 가져온다
- [x] 각 문서를 `files.export(mimeType='text/plain')`로 내보내 본문 텍스트로 변환한다 (Google 내보내기가 붙이는
      BOM과 `\r\n`도 정리함)
- [x] `python rag_pipeline.py --source gdrive` 실행 시 Vector DB에 정상 적재된다
- [x] 서비스 계정 키 파일 미설정/파일 공유 안 됨 등 실패 케이스가 트레이스백 없이 명확한 한국어 에러로 안내된다
- [x] 서버 재시작 후 실제 Drive 문서 내용으로 검색·요약이 되는 것을 curl로 검증함 (실제 논문 초안 문서로 확인)

### FR-6. GitHub 커넥터 (신규 — 이번 PRD 대상, Phase 4)

**연동 방식**: GitHub는 Notion처럼 "앱에 페이지 공유"하는 개념이 없어서, **Personal Access Token(PAT, read-only)
+ 명시적 저장소 목록**으로 스코프를 정한다. `.env`의 `GITHUB_REPOS`에 `owner/repo` 콤마 구분 목록을 적어야
그 저장소만 대상이 된다 (Slack의 "봇을 채널에 초대"와 같은 역할 — 명시적으로 지정한 곳만 읽는다).

**범위 (결정 사항)**
- **Issues와 PR을 대상으로 한다** (README/위키는 이번 Phase 범위 밖 — Out of scope로 명시). GitHub REST API의
  `/repos/{owner}/{repo}/issues` 엔드포인트는 PR도 함께 반환하므로 하나의 엔드포인트로 처리
- 최근 **90일** 이내 업데이트된 Issue/PR만 (`since` 파라미터) — Slack과 동일한 `*_LOOKBACK_DAYS` 상수 패턴
- Issue/PR 하나 = 문서 하나. 본문 + 모든 댓글을 시간순으로 이어붙여 하나의 문서로 만든다 (Slack 스레드 묶기와
  동일한 그레인)
- 봇 계정(`user.type == "Bot"`, 예: CI 상태 코멘트)의 댓글은 제외

**AC (완료 기준)**
- [x] `backend/connectors/github_connector.py`가 `GITHUB_REPOS`에 지정된 저장소의 Issue/PR을 가져온다
- [x] 각 Issue/PR의 본문+댓글을 시간순으로 묶어 공통 dict 포맷으로 변환한다
- [x] `python rag_pipeline.py --source github` 실행 시 Vector DB에 정상 적재된다
- [x] 토큰 미설정/저장소 목록 미설정 등 실패 케이스가 트레이스백 없이 명확한 한국어 에러로 안내된다
- [x] 서버 재시작 후 실제 저장소 Issue/PR 내용으로 검색·요약이 되는 것을 curl로 검증함 (실제 테스트 Issue로 확인)

### FR-7. GitLab 커넥터 (신규 — Phase 5, GitHub 커넥터와 동일 패턴)

- GitHub 커넥터(FR-6)와 스코프 결정이 동일: **Issues와 Merge Request만 대상**, README/위키는 범위 밖
- 연동 방식도 동일하게 PAT(read_api 스코프) + 명시적 프로젝트 목록(`GITLAB_PROJECTS`)
- GitHub와의 차이점(구현상 유의): GitLab API는 Issue/MR을 한 엔드포인트로 합쳐주지 않아 두 번 조회, 페이지네이션은
  `X-Next-Page` 헤더 기반, 시스템 자동 생성 노트(라벨 변경 등)는 `system: true` 필드로 제외
- **AC**: [x] 지정된 프로젝트의 Issue/MR을 가져온다 · [x] 본문+댓글을 시간순으로 묶는다 ·
  [x] `python rag_pipeline.py --source gitlab` 정상 적재 · [x] 토큰/프로젝트 미설정 시 명확한 한국어 에러 ·
  [x] 실제 GitLab 프로젝트(이슈+댓글)로 curl·브라우저 검증 완료

### FR-8. 다중 소스 병합 규칙 (Phase 2에서 정리됨, 재확인)
- 같은 주제가 Notion/Slack에 각각 있을 때 **병합하지 않고 별개 문서로 반환**한다 (프론트가 이미 출처별
  뱃지로 나눠 보여주는 구조라, 백엔드에서 억지로 합칠 필요 없음)
- 검색 결과 `relevance` 정렬은 Chroma 유사도 거리 그대로 사용 (소스별 가중치 없음) — 특정 소스를 우대하지 않는다

### FR-9. 자체 계정 시스템 (완료 — Phase 6a)

**배경**: 권한 인지형 검색을 여러 소스에 걸쳐 진짜로 하려면, 우리 사이트 자체 계정 하나에 각 소스별
신원을 "연결"하는 구조가 필요하다 (Google 계정 하나로 Notion/Slack/GitHub/GitLab의 권한까지 알 수는
없음 — 각자 다른 신원 체계). 그래서 자체 로그인을 먼저 만들고, Phase 6b부터 소스별 계정 연결을 붙인다.

**구현**
- `backend/db.py`: SQLite(`app.db`, gitignore 처리됨). `users`(이메일+bcrypt 해시) +
  `linked_accounts`(user_id ↔ provider별 신원, Phase 6b부터 채워짐) 테이블
- `backend/auth.py`: 회원가입/로그인 시 bcrypt로 비밀번호 검증, 세션은 우리가 직접 서명하는 JWT(7일 만료)
- API: `POST /api/v1/auth/signup`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`
- 프론트: `AuthPanel.jsx`(사이드바 하단, 로그인/회원가입 폼), `authStore.js`(localStorage에 토큰 보관,
  이후 모든 API 호출에 `Authorization: Bearer` 자동 첨부). 로그인하면 사이드바의 고정 "박유진" 자리에
  **실제 로그인한 이메일**이 표시됨

**AC**: [x] 회원가입/로그인/중복 이메일 거부/틀린 비밀번호 거부 curl 검증 · [x] JWT의 `sub` 클레임을
문자열로 인코딩(PyJWT 스펙 요구사항, 처음엔 정수로 넣어서 검증 실패하는 버그가 있었음) ·
[x] 브라우저로 회원가입→새로고침 후 세션 유지→로그아웃까지 전체 플로우 검증

### FR-10. Google Drive 권한 필터링 (완료 — Phase 6b)

**설계가 중간에 바뀐 이유**: 처음엔 서비스 계정으로 파일별 `permissions.list()`(전체 권한자 목록)를
가져와 저장해두는 방식(`allowedEmails`)을 계획했는데, 실제로 해보니 서비스 계정이 "뷰어" 권한만 가진
파일은 그 목록 자체를 조회할 수 없다는 걸 발견했다(`403 insufficientFilePermissions`). 그래서 방향을
반대로 뒤집었다 — "누가 이 파일에 접근 가능한가"를 서비스 계정으로 물어보는 대신, "로그인한 이 사람이
실제로 이 파일을 열 수 있는가"를 **그 사람 본인의 Google access token으로 직접** 확인한다.

**구현**
- 프론트: Google Identity Services의 OAuth2 토큰 클라이언트로 `drive.metadata.readonly` 동의를 받아
  access token 확보 (sessionStorage에만 보관 — 짧은 수명이라 세션마다 새로 받아야 함)
- 이 토큰으로 `/api/v1/auth/link/google`에 연결 요청 → 백엔드가 Google userinfo 엔드포인트로 검증 후
  이메일을 `linked_accounts`에 저장 (access token 자체는 서버에 저장하지 않음)
- 검색 요청마다 프론트가 `X-Google-Drive-Token` 헤더로 그 세션의 access token을 함께 보내고,
  백엔드는 gdrive 문서마다 `GET drive/v3/files/{id}`를 그 토큰으로 직접 호출해 200/403 여부로 필터링
- 토큰이 없거나(연결 안 함, 세션 만료) 확인 실패 시 기본 거부(결과에서 제외)

**AC**: [x] 서비스 계정 권한 제약 발견 및 설계 수정 · [x] 실제 Google 계정으로 연결 → 검색 시
Drive 문서 노출 확인 · [x] 연결 안 된 상태에서는 Drive 문서가 제외되는 것 확인 ·
[x] "계정 연결"과 "이번 세션 토큰 보유" 상태가 다를 수 있다는 것을 발견 → UI에 재연결 버튼 추가

### FR-11. GitHub 계정 연결 + 저장소 권한 필터링 (완료 — Phase 6c)

**Google과 다른 점**: GitHub는 클라이언트 전용 OAuth 플로우가 없어서(implicit grant 미지원),
클라이언트 시크릿이 필요한 표준 Authorization Code 플로우를 쓴다 — 우리 백엔드가 콜백을 직접 받아야
한다. 또한 GitHub access token은 기본적으로 만료되지 않으므로, Google과 달리 **서버(`linked_accounts.access_token`)에
저장**해두고 검색 때마다 서버가 바로 쓴다 (프론트가 매번 헤더로 보낼 필요 없음).

**구현**
- `GET /api/v1/auth/link/github/start`(로그인 필요) → `state`를 `oauth_states` 테이블에 저장하고
  GitHub 인가 URL 반환
- 프론트가 팝업으로 그 URL을 염 → 사용자 승인 → GitHub가 우리 백엔드 콜백(`/api/v1/auth/link/github/callback`)으로
  `code`+`state`와 함께 리다이렉트 (콜백은 로그인 헤더가 없는 순수 브라우저 요청이라 `state`로 어느
  계정이 요청했는지 복구)
- 콜백이 code를 access_token으로 교환 → `GET api.github.com/user`로 신원 확인 → `linked_accounts`에
  로그인명+access_token 저장 → 팝업이 `postMessage`로 원래 창에 결과를 알리고 닫힘
- 검색 시 github 문서마다 `GET api.github.com/repos/{owner}/{repo}`를 저장된 토�큰으로 호출해 필터링
  (저장소 이름은 `github_connector.py`가 만드는 tags 순서 `["github", "owner/repo", kind]`에 의존)

**AC**: [x] OAuth start/callback 왕복 실제 GitHub 계정으로 검증 · [x] `linked_accounts`에 access_token
저장 확인 · [x] 연결 후 실제 저장소(`YunhuPark/Medical_Insight_Lab`) 문서가 검색에 노출되는 것 확인

### FR-12. GitLab 계정 연결 + 프로젝트 권한 필터링 (완료 — Phase 6d)

GitHub와 완전히 같은 패턴(둘 다 클라이언트 시크릿이 필요한 표준 OAuth Authorization Code 플로우)이라
`auth.py`의 `get_oauth_authorize_url(provider, ...)` / `complete_oauth_link(provider, ...)`,
`main.py`의 `/api/v1/auth/link/{provider}/start`·`/callback`을 GitHub와 공유한다 (provider별 설정은
`OAUTH_PROVIDERS` dict 하나로 관리). 프론트도 `GithubLinkPanel`을 `PopupLinkPanel`로 일반화해서
GitHub/GitLab이 같은 컴포넌트를 쓴다.

- 검색 시 gitlab 문서마다 `GET {GITLAB_URL}/api/v4/projects/{project_path}`를 저장된 토큰으로 호출해
  필터링 (`gitlab_connector.py`가 만드는 tags 순서 `["gitlab", "namespace/project", kind]`에 의존)
- GitLab access token도 GitHub처럼 서버(`linked_accounts.access_token`)에 저장, 자체 호스팅 GitLab
  대응을 위해 기존 `GITLAB_URL` 환경변수를 OAuth 엔드포인트 베이스로도 재사용

**AC**: [x] OAuth start/callback 왕복 실제 GitLab 계정으로 검증 · [x] `linked_accounts`에 access_token
저장 확인 · [x] 연결 후 실제 프로젝트(`personal-group9005538/personal-project`) 이슈가 검색에
노출되는 것 확인 · [x] GitHub 리팩터링 후에도 기존 GitHub 연동 회귀 없음 확인

### FR-13. Slack 계정 연결 + 채널 권한 필터링 (완료 — Phase 6e)

Slack은 GitHub/GitLab과 토큰 응답 형태가 달라(`authed_user.access_token`처럼 중첩돼 있고, 별도의
`/user` 신원 조회 엔드포인트도 없음) `OAUTH_PROVIDERS` 공용 흐름에 억지로 끼워맞추지 않고
`auth.get_slack_authorize_url`/`complete_slack_link`로 따로 구현했다. 대신 라우트(`/start`/`/callback`)와
프론트 `PopupLinkPanel`은 그대로 재사용— 팝업 + postMessage 패턴 자체는 동일하기 때문이다.

- 수집용 봇(`SLACK_BOT_TOKEN`)과 **같은 Slack 앱**에 User Token Scopes만 추가하면 된다 (새 앱 불필요) —
  Slack은 한 앱이 봇 토큰과 사용자 토큰을 동시에 가질 수 있는 구조라서, GitHub/GitLab처럼 "수집용 앱과
  권한 필터링용 앱을 분리"할 필요가 없었다.
- 인가 시 `user_scope=channels:history,groups:history,channels:read,groups:read`로 요청해
  `authed_user.access_token`(그 사람 본인 권한 토큰)을 받는다. 표시용 이름은 봇 토큰으로 `users.info`를
  한 번 더 불러 해석(실패해도 Slack user ID로 대체 — 연결 자체는 실패하지 않음).
- 검색 시 slack 문서마다 그 사람 토큰으로 `conversations.history(channel, limit=1)`를 호출해 필터링
  (`slack_connector.py`가 만드는 id 형식 `slack-{channelId}-{ts}`에서 channel_id를 파싱 —
  채널 ID는 대시를 쓰지 않고 타임스탬프는 점을 써서 첫 "-"로 안전하게 분리됨). 공개 채널이라도
  멤버가 아니면 `not_in_channel`로 실패하므로, "채널이 존재하는가"가 아니라 "이 토큰으로 실제로 이
  채널 대화를 읽을 수 있는가"를 그대로 확인하는 셈이다.

**AC**: [x] GitHub/GitLab 회귀 없음 확인(같은 `{provider}` 라우트를 공유하지 않도록 Slack 전용
라우트를 앞에 등록, placeholder 자격증명일 때 400 확인) · [x] OAuth start/callback 왕복 실제 Slack
계정(`byunhu35`, 표시명 "윤후")으로 검증 · [x] `linked_accounts`에 사용자 토큰(`xoxp-...`) 저장 확인 ·
[x] 연결 후 실제 `#marketing` 채널 메시지가 검색에 노출되는 것 확인 · [x] Slack 미연결 계정으로는
같은 검색에서 Slack 문서가 제외되는 것(기본 거부) 확인

> 트러블슈팅: Slack의 새 앱 설정 화면은 redirect URL로 `http://localhost:...`를 거부하고
> `http://127.0.0.1:...`만 허용했다 — `SLACK_OAUTH_REDIRECT_URI`를 127.0.0.1로 바꾸면서, 콜백
> 페이지의 postMessage 발신 origin도 `http://127.0.0.1:8000`으로 바뀌어 프론트(`PopupLinkPanel.jsx`)의
> origin 검증이 `http://localhost:8000`과 불일치로 막던 문제가 있었다 — 신뢰 origin 목록에 둘 다
> 추가해서 해결(로컬 개발 환경이라 둘 다 사실상 같은 서버).

### FR-14. Notion 계정 연결 + 페이지 권한 필터링 (완료 — Phase 6f)

기존 수집용 `NOTION_TOKEN`은 Internal Integration(단일 워크스페이스, 관리자가 미리 페이지를 공유해두는
방식)이라 OAuth를 지원하지 않아, 계정 연결용으로 Notion에 **Public 타입(OAuth) 통합**을 새로 만들었다.
이 OAuth 동의 화면에서는 로그인한 사람이 "이 통합에 공유할 페이지"를 직접 고르기 때문에, 그렇게 받은
토큰은 Drive/GitHub/GitLab과 마찬가지로 딱 그 사람이 선택한 페이지에만 접근 가능하다 — 그래서 검색 시
권한 확인도 같은 패턴(본인 토큰으로 페이지를 직접 GET)을 그대로 쓴다. 토큰 교환이 Basic Auth를 쓰고
신원 정보가 `owner.user` 안에 바로 포함돼 있어(별도 `/user` 조회 불필요) Slack처럼 공용
`OAUTH_PROVIDERS` 흐름에 태우지 않고 `auth.get_notion_authorize_url`/`complete_notion_link`로 따로
구현했다.

- 검색 시 notion 문서마다 `GET /v1/pages/{page_id}`를 저장된 사용자 토큰으로 호출해 필터링
  (`notion_connector.py`가 만드는 id 형식 `notion-{page_id}`에서, page_id 자체가 대시 포함 UUID라
  접두사만 잘라내면 그대로 유효한 page_id가 됨)
- OAuth 통합의 "기능" 설정에서 콘텐츠 읽기만 남기고 업데이트/삽입은 껐다 (읽기 전용 원칙 유지)

**AC**: [x] OAuth start/callback 왕복 실제 Notion 계정(표시명 "후 윤")으로 검증 · [x]
`linked_accounts`에 사용자 토큰(`ntn_...`) 저장 확인 · [x] 동의 화면에서 실제로 선택해 공유한 페이지
(`Other Projects | Golden-Time · 마른길`)만 검색에 노출되는 것 확인 · [x] 예전에 수집용
Internal Integration(`NOTION_TOKEN`)으로만 공유돼 있고 이 OAuth 연결에는 공유 안 한 페이지 2개
(`03. Medical Insight Lab`, `박윤후 AI Engineer Portfolio`)가 이 사용자 토큰으로 404 → 검색에서
정확히 제외되는 것 확인 · [x] Notion 미연결 계정으로는 Notion 문서가 전부 제외되는 것(기본 거부) 확인

이로써 5개 연동 소스(Google Drive, GitHub, GitLab, Slack, Notion) 전체에 권한 인지형 검색이 적용됐다.

## 5. 비기능 요구사항

| 항목 | 요구사항 |
|---|---|
| 로깅 | `print()`에 이모지 사용 금지 (Windows cp949 콘솔에서 UnicodeEncodeError로 실제 결과가 mock 폴백에 덮여씌워지는 사고를 Phase 1에서 겪음). 새 커넥터도 동일 규칙 적용 |
| 비용 | 검색 1회당 GPT-4o 호출 1회. Slack 채널 수 늘어나도 검색 시 호출 횟수는 늘지 않음 (임베딩만 늘어남) |
| 보안 | 모든 토큰은 `.env`, git에 커밋되지 않음(`.gitignore` 반영 완료). 커넥터는 읽기 전용 스코프만 요청 |
| 데이터 신선도 | 실시간 아님. 재적재는 수동 스크립트 실행 + 서버 재시작으로 반영 (웹훅 기반 자동 동기화는 Phase 3 이후) |

## 6. 알려진 이슈 / 운영 노트 (Phase 0~1에서 확인됨)

1. Chroma는 다른 프로세스가 쓴 내용을 자동으로 다시 읽지 않는다 → **적재 후 반드시 API 서버 재시작**
2. Windows 콘솔 인코딩(cp949) 때문에 이모지 print가 크래시를 유발할 수 있다 → 로그에 이모지 쓰지 않기
3. 문서 메타데이터에 `title`이 빠지면 검색 결과 제목이 전부 "문서"로 뜬다 → 커넥터는 반드시 `title` 채울 것

## 7. 오픈 이슈 (결정 보류)

- Slack 워크스페이스에 채널이 매우 많아질 경우 `conversations.list` 페이지네이션/레이트리밋 처리 — 기본
  페이지네이션 구현만 하고, 실제 채널 수가 많아지면 그때 배치/큐 방식 검토
- 여러 소스에서 사실상 동일한 결정이 중복 추출될 때 `decisionTrail` 중복 제거 여부 — 일단 중복 허용, 사용자
  피드백 보고 재검토
