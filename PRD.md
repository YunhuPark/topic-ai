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
| Phase 7 | 계정 연동 시 자동 수집(5개 소스 전체) — "연동 = 관리자 사전 설정 목록 안에서 필터링만"이던 것을 "연동 = 그 사람 접근 가능한 문서 전체를 즉시 수집"으로 전환 | ✅ 구현 완료 (로컬 자격증명 미구성으로 curl 재검증은 아직 — 아래 AC 참고) |

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

### FR-1. 통합 검색 API (완료, Phase 7에서 랭킹 보정 추가)
- `GET /api/v1/search?q={query}` — 벡터 유사도 상위 20개를 후보로 뽑은 뒤, (벡터 유사도 + 제목/본문
  키워드 일치) 하이브리드 점수로 재정렬해 top-4 반환
- AC: 쿼리와 무관한 문서가 섞이지 않고, 응답에 mock 폴백이 섞이지 않는다 (OPENAI_API_KEY 정상일 때)
- **Phase 7 랭킹 보정**: 실제 Google Drive 19개 문서로 테스트하던 중 "paper" 검색 시 제목이
  `paper_draft`인 문서가 (순수 벡터 유사도만으로는) 19개 중 13위로 밀리는 문제를 발견함 — 문서가
  적고 서로 비슷했던 mock 3종 세트에서는 드러나지 않던 문제. 단일 단어·다의어 질의는 임베딩 신호가
  약해서, 제목에 검색어가 그대로 들어간 문서보다 의미상 막연히 가까운 다른 문서가 앞설 수 있음을
  확인. `main.py`의 `_keyword_boost()`로 제목/본문 키워드 일치 가산점을 섞는 하이브리드 재정렬을
  추가해 해결(제목 일치 2배 가중치) — 소스별 가중치를 주는 것은 아니라 FR-8의 "소스를 우대하지
  않는다" 원칙과는 상충하지 않음
- **Phase 7 랭킹 보정 2차(실사용 검증 중 추가 발견)**: 실제 GitHub 196개 문서로 "medi" 검색 시,
  저장소 이름이 정확히 "Medi-Matrix"인 저장소 자체의 PR보다 그 저장소를 본문에서 언급만 한 다른
  저장소("portfolio")의 문서가 앞서는 문제를 발견함 — 제목/본문 키워드 일치만 봐서는 두 경우가
  구분 안 됐던 것. `_extract_source_name()`으로 문서의 출처 이름(저장소/프로젝트/채널명 —
  github/gitlab/slack만 해당, notion/gdrive는 tags[1]이 이름이 아니라 파일 종류라 제외)을 뽑아서,
  거기 검색어가 그대로 있으면 제목 일치보다도 더 강한 가산점(3배)을 주도록 `_keyword_boost()`를
  확장함 — 특정 프로젝트를 가리키는 게 명백한 질의어는 그 프로젝트 "자체"의 문서를 최우선하는 게
  자연스럽다는 판단
- **문서 날짜 기준 수정(GitHub/GitLab)**: 같은 실사용 검증 중 "최신성 판단이 코드/논의가 마지막으로
  갱신된 시점이 아니라 Issue/PR을 맨 처음 만든 시점 기준이라 이상하다"는 문제도 발견함 —
  `github_connector.py`/`gitlab_connector.py` 둘 다 문서의 `date`를 `created_at`이 아니라
  `updated_at`(마지막 활동 시점)으로 바꿔서, 오래전에 열렸어도 최근에 댓글이 달린 논의는 최신으로
  잡히게 함. 기존에 이미 적재된 문서는 다음 재동기화(자동 폴링 또는 재연동) 때 갱신됨

### FR-2. AI 요약/디시전 트레일/액션아이템 생성 (완료, Phase 7에서 담당자 배정 로직 보강)
- 검색된 문서들을 컨텍스트로 GPT-4o 호출, `Summary` 스키마로 파싱
- AC: 모든 텍스트 필드가 한국어로 반환된다 (Phase 1에서 영어로 새는 문제 확인 후 프롬프트에 명시함)
- **비용 관련 결정 (Phase 7)**: 검색 1회당 GPT-4o 호출은 1번, 그것도 상위 4개 문서만 컨텍스트로
  넣는 구조라 연동 도구/문서 수가 늘어도 검색당 비용은 늘지 않음. 이번엔 gpt-4o-mini로 교체하는
  대신 **현재 모델(gpt-4o) 유지를 선택** — 담당자 판단 정확도가 이 서비스의 핵심 차별점이라, 아직
  비용이 부담되는 사용량이 아닌 시점에 품질을 낮추는 트레이드오프를 감수할 이유가 없다고 판단함.
  사용량이 늘어 비용이 실제 이슈가 되면 그때 실제 쿼리로 mini와 A/B 비교 후 재검토
- **담당자(assignee) 배정 로직 (Phase 7)**: "회의 시작할 때 이름을 말해야 한다" 같은 사용자 행동
  강제 없이, 있는 정보만으로 AI가 담당자를 추론하도록 프롬프트를 보강함 — 이전엔 문서 작성자
  정보 자체가 LLM 컨텍스트에 전달되지 않고 있었음(버그). 지금은 문서마다 "문서 작성자"를 함께
  전달하고, ⓐ 대화/문서 안에 담당자가 명시적으로 언급됨(예: "제가 할게요", "@이름님 부탁드려요")
  → 그 사람, ⓑ 명시적 언급 없음 → 그 문서/메시지 작성자를 기본값으로, ⓒ 그래도 특정 불가 →
  "미정"(이름을 지어내지 않음) 순으로 판단하도록 지시
- **동명이인 한계 (Phase 7)**: 순수 텍스트만으로는 "승현님"처럼 성 없이 불린 이름이 이승현/박승현
  중 누구를 가리키는지 확실히 알 수 없다 — 근본적으로 텍스트만으로 항상 풀 수 있는 문제는 아님.
  다만 관련해서 실제 버그를 하나 발견해 고침: Slack의 "@이름" 자동완성 멘션은 원문에
  `<@U0123ABC>`처럼 사용자 ID로 저장되는데, 이를 해석하지 않고 그대로 LLM에 넘기고 있어서
  **가장 확실한 담당자 신호인 실제 멘션이 지금까지 AI에게 전혀 안 보이고 있었음**
  (`slack_connector.py` `_resolve_mentions` 추가로 실제 표시 이름으로 풀어서 전달하도록 수정 —
  이 경로는 Slack이 사용자 ID로 못박아주므로 동명이인이어도 정확함). 반대로 자동완성 없이 그냥
  타이핑한 "승현님" 같은 이름만 있는 경우는 여전히 완전한 이름을 지어내지 않고 원문 표현
  그대로("승현님") 남기도록 프롬프트에 명시 — 잘못 추측해서 엉뚱한 사람에게 할 일이 배정되는
  것을 막기 위함. 워크스페이스 전체 인물 로스터 기반의 완전한 동명이인 해소는 Out of scope
  (오픈 이슈로 남김, §7 참고)

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
- 최초엔 **Google Docs만 지원**하고 Sheets/Slides/PDF는 Out of scope로 뒀으나, Phase 7에서
  "사내 문서가 Notion/Drive 어디에 있는지 찾는 데 시간이 오래 걸린다"는 실사용 피드백을 받아
  범위를 넓힘 — 지금은 아래를 지원:
  - Google 네이티브: Docs, Sheets(시트가 여러 개여도 전부), Slides
  - 업로드된 원본 파일: PDF, MS Word(.docx)/Excel(.xlsx)/PowerPoint(.pptx), 한글 HWPX(.hwpx)
  - **미지원(알려진 한계)**: 스캔 이미지로만 된 PDF(텍스트 레이어 없음, OCR은 범위 밖),
    레거시 바이너리 `.hwp`(2014년 이전 한글 포맷)와 구버전 MS Office(`.doc`/`.xls`/`.ppt`) —
    신뢰할 만한 순수 파이썬 파서가 없어 제외. 최신 포맷으로 다시 저장하거나 PDF로 내보내면
    검색 대상이 됨
  - Google 네이티브 3종 + PDF는 Drive API의 mimeType으로 구분하고, 업로드된 원본 파일은
    mimeType이 앱마다 불확실해서(특히 HWP) 파일명 확장자로 구분한다 (`gdrive_connector.py`
    `_resolve_kind`/`_extract_content`)
- 서비스 계정에 공유된 파일 전체를 `files.list()`로 조회 (별도 폴더 스코프 제한 없음, 공유 자체가 스코프 역할)
- 문서 단위: 파일 하나 = 문서 하나 (Notion과 동일한 그레인)

**AC (완료 기준)**
- [x] `backend/connectors/gdrive_connector.py`가 서비스 계정에 공유된 Google Docs 목록을 가져온다
- [x] 각 문서를 `files.export(mimeType='text/plain')`로 내보내 본문 텍스트로 변환한다 (Google 내보내기가 붙이는
      BOM과 `\r\n`도 정리함)
- [x] `python rag_pipeline.py --source gdrive` 실행 시 Vector DB에 정상 적재된다
- [x] 서비스 계정 키 파일 미설정/파일 공유 안 됨 등 실패 케이스가 트레이스백 없이 명확한 한국어 에러로 안내된다
- [x] 서버 재시작 후 실제 Drive 문서 내용으로 검색·요약이 되는 것을 curl로 검증함 (실제 논문 초안 문서로 확인)
- [x] (Phase 7) Sheets/Slides/PDF/DOCX/XLSX/PPTX/HWPX 파서를 합성 파일(직접 만든 최소 예제)로
      단위 테스트해 각각 정상 추출됨을 확인 — 실제 계정에 각 형식 파일을 올려서 하는 종단 검증은
      아직 안 함(다음 실 사용 때 확인 필요)

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

### FR-10. Google Drive 권한 필터링 (완료 — Phase 6b, Phase 7에서 서버 사이드 refresh_token으로 전환)

**설계가 중간에 바뀐 이유(Phase 6b)**: 처음엔 서비스 계정으로 파일별 `permissions.list()`(전체 권한자
목록)를 가져와 저장해두는 방식(`allowedEmails`)을 계획했는데, 실제로 해보니 서비스 계정이 "뷰어" 권한만
가진 파일은 그 목록 자체를 조회할 수 없다는 걸 발견했다(`403 insufficientFilePermissions`). 그래서
방향을 반대로 뒤집었다 — "누가 이 파일에 접근 가능한가"를 서비스 계정으로 물어보는 대신, "로그인한 이
사람이 실제로 이 파일을 열 수 있는가"를 **그 사람 본인의 Google access token으로 직접** 확인한다.

**Phase 6b 초기 구현(폐기됨)**: 프론트가 Google Identity Services 토큰 클라이언트로 짧은 수명
access token만 받아 sessionStorage에 보관하고, 검색마다 `X-Google-Drive-Token` 헤더로 매번 보내는
방식이었다. 문제는 (1) 세션이 끝나거나 새로고침하면 토큰이 사라져 "계정은 연결돼 있는데 이번 세션엔
Drive가 안 보이는" 혼란스러운 상태가 생기고, (2) refresh_token이 없는 방식이라 서버가 혼자 알아서
재동기화(폴링)를 할 수 없었다는 것.

**Phase 7: GitHub/GitLab과 동일한 패턴으로 통일**: "회사 실사용" 단계로 가면서 이 비일관성을 없앴다 —
Google도 서버 사이드 Authorization Code 플로우(`access_type=offline&prompt=consent`)로 바꿔
**refresh_token을 서버(`linked_accounts.access_token`)에 저장**하고, 검색·자동 재동기화 시점마다
그걸로 짧은 수명 access_token을 새로 발급받아 쓴다(`auth.refresh_google_access_token`). 이제
프론트는 Drive 토큰을 전혀 몰라도 되고(`X-Google-Drive-Token` 헤더/`googleDriveAuth.js`/
`GoogleLinkPanel.jsx` 전부 제거, GitHub 등과 같은 `PopupLinkPanel` 재사용), Google도 FR-15의
백그라운드 자동 재동기화 대상에 들어간다.

> ⚠️ **마이그레이션 노트**: Phase 6b 방식으로 이미 연결했던 계정은 서버에 refresh_token이 없으므로
> (애초에 저장 안 하는 설계였음), Phase 7 배포 후 **한 번은 재연결이 필요**하다 — 그 전까지는 검색 시
> Drive 문서가 조용히 전부 제외된다(기본 거부 원칙이 그대로 적용된 것뿐이라 에러는 안 남).

**구현 (Phase 7 기준)**
- `GET /api/v1/auth/link/google/start`/`callback` — GitHub/GitLab과 같은 팝업+콜백 패턴
  (`auth.get_google_authorize_url`/`complete_google_link`, 공용 `OAUTH_PROVIDERS`엔 응답 형태가 달라
  안 태움 — Slack/Notion과 같은 이유)
- `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET`(신규, 클라이언트 시크릿 포함된 "웹 애플리케이션"
  타입) — 예전 `VITE_GOOGLE_CLIENT_ID`(프론트 전용, 시크릿 없음)는 폐기
- 검색 요청마다 `db.get_linked_access_token(user_id, "google")`로 refresh_token을 가져와 그 요청
  안에서 한 번만 access_token으로 갱신해 재사용 (gdrive 문서가 후보에 없으면 아예 갱신 API를 안 부름)
- 토큰이 없거나(연결 안 함) 갱신 실패 시 기본 거부(결과에서 제외) — 원칙은 Phase 6b와 동일

**AC**: [x] 서비스 계정 권한 제약 발견 및 설계 수정(Phase 6b) · [x] 실제 Google 계정으로 연결 → 검색 시
Drive 문서 노출 확인(Phase 6b, 19개 문서로 재확인) · [x] 연결 안 된 상태에서는 Drive 문서가 제외되는
것 확인 · [x] (Phase 7) 서버 사이드 refresh_token 플로우로 전환, 프론트의 클라이언트 토큰 관리 코드
전부 제거 · [ ] (Phase 7) 새 플로우로 실제 재연결 → 검색 노출까지 curl/브라우저 재검증 — 아직 실 자격
증명(새 OAuth 클라이언트 시크릿) 설정 전이라 미완료

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

### FR-15. 계정 연동 시 자동 수집 (완료 — Phase 7)

**배경**: Phase 6b~6f까지는 "계정 연동"이 검색 결과를 **필터링**만 했다 — 실제로 무엇이 Vector DB에
들어가는지는 여전히 관리자가 `.env`(`GITHUB_REPOS`/`GITLAB_PROJECTS`)에 미리 정해둔 고정 목록이거나,
서비스 계정/Internal Integration에 개별 파일·페이지를 수동으로 공유해야만 했다. 그 결과 사용자가
자기 계정을 연동해도, 관리자가 테스트 삼아 하나 넣어둔 문서만 계속 보이는 문제가 있었다 — 연동과
수집이 분리돼 있었던 것이 근본 원인.

**변경**: 계정을 연동하는 시점에, **그 사람 본인의 access token으로 그 사람이 실제 접근 가능한
문서 전체**를 즉시 가져와 적재한다 (API 서버와 같은 프로세스 안에서 바로 실행되므로, 기존
"오프라인 스크립트 적재 후 서버 재시작 필요" 문제도 함께 해소됨 — §6 known issue #1 참고).

- GitHub/GitLab: `GET /user/repos`(`affiliation=owner,collaborator,organization_member`) /
  `GET /projects?membership=true`로 이 사람이 속한 저장소·프로젝트 전체를 나열한 뒤, 각각의
  Issue/PR·MR을 기존과 동일한 규칙(90일, 봇/시스템 노트 제외)으로 수집한다. 관리자의
  `GITHUB_REPOS`/`GITLAB_PROJECTS` 고정 목록 기반 수집(FR-6, FR-7)은 그대로 남겨뒀다(선택적 관리자
  일괄 적재 용도).
- Slack: 채널 목록 조회(`conversations.list`)·대화 조회를 봇 토큰이 아니라 **연동한 사람 본인의
  사용자 토큰**으로 호출하도록 바꿔서, 봇이 초대되지 않은 채널도 그 사람이 멤버이기만 하면 자동으로
  수집 대상이 된다. 사용자 토큰 스코프에 `users:read`를 추가해 작성자 이름 조회도 봇 토큰 없이 가능.
- Notion: 정적 Internal Integration 토큰(`NOTION_TOKEN`) 대신 **연동한 사람 본인의 OAuth 토큰**으로
  `/v1/search`를 호출 — 동의 화면에서 그 사람이 고른 페이지 전체가 곧바로 수집 대상이 된다.
- Google Drive: 서비스 계정에 파일을 일일이 공유해야 했던 방식과 별개로, **연동한 사람 본인의 Drive
  OAuth 토큰**으로 그 사람 소유이거나 공유받은 Google Docs 전체를 직접 가져온다. 이를 위해 프론트가
  요청하는 동의 스코프를 `drive.metadata.readonly`(메타데이터만) → `drive.readonly`(본문 내보내기
  포함)로 넓혔다.
- 재적재 중복 방지: `rag_pipeline.ingest_documents()`가 문서를 추가만 하고 upsert하지 않던 잠재
  버그를 함께 고쳤다 — 이제 문서 `id`로 먼저 지우고 다시 넣어서, 재연동/재적재를 여러 번 반복해도
  같은 문서가 중복으로 쌓이지 않는다.
- 권한 필터링(FR-10~FR-14)은 그대로 유지 — 검색 시점에 "검색하는 사람 본인" 토큰으로 매번 재확인하는
  구조라, 이 자동 수집으로 Vector DB의 문서 풀이 커져도 다른 사람의 문서가 새어나가지 않는다.
- **주기적 자동 재동기화 (실사용 전환 결정)**: 연동 시점 한 번만 수집하면 그 이후 원본에 새로
  쌓이는 대화/문서는 재연동 전까지 검색에 안 잡히는 문제가 있어(§7에서 오픈 이슈로 뒀던 것),
  "회사에서 바로 실사용 가능한 수준"을 목표로 지금 반영함 — `main.py`에 FastAPI startup에서
  띄우는 백그라운드 asyncio 루프(`_auto_resync_loop`)가 `AUTO_RESYNC_INTERVAL_SECONDS`
  (기본 900초=15분)마다 서버에 access_token이 저장된 연동(GitHub/GitLab/Slack/Notion)을 전부
  순회하며 재수집한다. Google Drive는 FR-10 설계상 토큰을 서버에 저장하지 않아 이 폴링 대상에서
  빠짐 — 그 세션에서 "Drive 접근 다시 허용"을 눌러야 재동기화됨(§7에 Drive용 refresh token
  전환 여부를 오픈 이슈로 남김)

**AC**:
- [x] 5개 커넥터 모두 `fetch_*_documents_for_user(access_token)` 추가, 계정 연동 완료 직후
  (`auth.link_google_account`/`complete_oauth_link`/`complete_slack_link`/`complete_notion_link`)
  자동 호출되도록 연결
- [x] 수집 실패가 연결 자체를 실패시키지 않도록 처리(연결은 성공, 동기화만 로그로 실패 기록)
- [x] 프론트에서 연동 직후 안내 표시(`PopupLinkPanel`, 문서 수를 알 때는 개수, 모를 때는
  "백그라운드에서 가져오는 중" 메시지)
- [x] `ingest_documents()` 중복 적재 버그 수정(id 기반 delete-then-add)
- [x] **실제 자격증명으로 5개 소스 전부 재검증 완료** — Google Drive(81개, 서비스 계정 공유 파일 +
  개인 Drive 전체), GitHub(196개, 실제 여러 저장소), Slack(3개), GitLab(1개), Notion(1개)까지
  실제 계정 연동 → 검색 결과 노출 확인함
- [x] **연동 직후 동기화가 OAuth 팝업을 막던 문제 발견 및 수정**: Google Drive 실사용 검증 중,
  이 계정에 Sheets 파일이 30개 이상 있어서 전체 수집이 몇 분씩 걸렸는데, 이 수집을 계정 연결
  콜백 응답 안에서 동기(synchronous)로 기다리고 있어서 그동안 OAuth 팝업이 멈춘 것처럼 보이는
  문제를 발견함 — `auth._sync_after_link_background()`로 백그라운드 스레드에서 돌리도록 바꿔서
  연결 자체는 즉시 완료되고, 수집은 뒤에서 계속 진행되게 함(완료되면 다음 검색 때 자연스럽게 반영)
- [x] **Google Sheets API 분당 요청 한도(60건/사용자) 초과 문제 발견 및 수정**: 같은 검증 중 Sheets
  문서가 많으면(문서당 최소 2건: 탭 목록 + 탭별 값 조회) 금방 429(rate limit)에 걸려 해당 문서
  내용이 통째로 누락되는 것을 확인함 — `gdrive_connector.py`의 `_sheets_api_call()`이 호출 사이
  최소 간격(1.1초)을 두어 애초에 한도를 안 넘기게 하고, 그래도 429가 나면 지수 백오프로 재시도함
  (합성 429 응답으로 재시도 동작 단위 테스트함)

### FR-16. 실사용 전 전체 코드 감사 및 수정 (Phase 8)

실제 직원 배포를 앞두고 백엔드 API / 데이터 파이프라인 / 프론트엔드를 전수 감사해 30여 개 문제를
찾았다. 이 중 사용자가 바로 부딪히는 것들을 단계별로 수정 중이다(자세한 배경은 감사 당시 기록 참고).

**완료 (Phase 8-1: 신뢰·보안)**
- `/api/v1/stats`에 로그인 검사가 아예 없어 **전 직원의 문서 제목·출처가 무인증으로 노출**되던 문제
  수정. 모든 사용자가 Chroma 컬렉션 하나를 공유하는 구조라, 검색만 권한 확인을 하고 통계는 그
  전제를 통째로 비켜가고 있었다. 이제 로그인 필수 + **본인이 연동해 가져온 문서만** 집계한다
  (문서 메타데이터에 `syncedBy`(가져온 사용자 id 목록)를 기록해 판정).
- **가짜 데이터가 진짜 결과로 나가던 4개 경로 제거**: 빈 DB / 검색 중 예외 / OPENAI_API_KEY 없음 /
  LLM 실패 시 `dummy_data`의 "Q3 마케팅 캠페인" 문서·요약이 반환됐고, 그 **가짜 액션아이템이 사용자
  할 일 리스트에 영구 저장**되기까지 했다. 이제 각각 빈 결과 안내 / HTTP 500 / 요약 실패 안내로
  바뀌었고, 요약 생성에 실패하면 할 일 저장을 건너뛴다.
- OAuth 콜백 페이지의 HTML·스크립트 이스케이프, `FRONTEND_ORIGINS` 환경변수화(localhost와
  127.0.0.1 모두에 postMessage — 한쪽으로만 보내서 연결 성공에도 "연결 창이 닫혔습니다"가 뜨던 문제).
- `JWT_SECRET` 미설정 시 기동 실패(fail-fast), 로그인 5회 실패 시 5분 잠금, `oauth_states` 만료(10분)
  및 정리, SQLite WAL + 30초 타임아웃(백그라운드 동기화와 동시 쓰기 시 "database is locked" 방지).

**완료 (Phase 8-2: 동기화 비용·한도)**
- **증분 동기화 도입**: 15분마다 모든 문서를 다시 받아 다시 임베딩하던 것을, 원본의 수정 시각
  (`sourceUpdatedAt`)과 본문 해시(`contentHash`)로 걸러 **바뀐 것만** 수집·임베딩하도록 바꿨다.
  실측(1인 325문서): 전체 동기화 1회차 약 7분·임베딩 324건 → 2회차 **30초·임베딩 1건**.
  Drive 342.9초→11.2초, GitHub 67.8초→13.4초. 댓글이 0개인 이슈에 대한 댓글 API 호출도 제거.
- **사라진 문서 정리**: 원본에서 삭제되거나 접근 권한을 잃은 문서를 `syncedBy`에서 떼어내고,
  아무도 안 가져오는 문서가 되면 삭제한다. 다만 **부분 실패를 삭제로 오인하지 않도록**, 수집에
  실패한 저장소/프로젝트/채널의 기존 문서는 "그대로 있는 것"으로 간주하고, 수집 결과가 통째로
  비면 그 주기의 정리를 아예 건너뛴다(이 안전장치가 없으면 일시적 500 하나로 멀쩡한 문서가 삭제됨).
- `ingest_documents`의 delete-then-add 제거 — `add_documents(ids=...)`가 이미 upsert라 불필요했고,
  임베딩이 도는 동안 해당 문서들이 검색에서 사라지는 구간만 만들고 있었다.
- 문서 id 충돌 수정: `github-{owner}-{repo}-{n}`은 `(my-org, web)`과 `(my, org-web)`이 같은 id가
  됐다. `github-{owner}/{repo}#{n}`, `gitlab-{path}#{kind}-{iid}`로 변경. 이 변경으로 예전 id의
  문서 197개가 중복으로 남아, 현행 문서에 같은 제목이 전부 존재함을 확인한 뒤 일괄 삭제했다.
- 커넥터 견고성: Drive는 `HttpError`만 잡고 있어 손상된 PDF·잘린 HWPX 하나에 그 주기의 Drive 수집
  81개가 통째로 날아갔다 → 파일 단위 `except Exception`. GitHub/GitLab/Slack/Notion도 저장소·채널·
  페이지 단위 예외 가드 추가. Sheets 탭 이름 A1 표기법 따옴표 처리(공백 있는 탭 이름 때문에 400이
  나면서 스프레드시트 전체가 건너뛰어지던 문제).

**완료 (Phase 8-3: 실행 환경 차단 대응)**
- Windows **Smart App Control이 `tiktoken`의 서명 없는 네이티브 모듈을 차단**해 백엔드가 아예 기동
  못 하는 상황이 발생했다(`langchain_openai`가 import 시점에 tiktoken을 부름). PC 보안 설정을 끄는
  것은 되돌릴 수 없는 변경이라, 대신 **`langchain_openai` 의존성을 제거**하고 `openai` SDK를 직접
  호출하도록 임베딩/요약 경로를 다시 작성했다(`OpenAIDirectEmbeddings`, JSON 모드 chat completion).
  모델·파라미터가 같아 **기존 임베딩은 그대로 유효**하며, 요약 호출에 60초 타임아웃도 함께 붙였다.
  tiktoken이 없으므로 임베딩 입력은 토큰 어림치로 자르고, 상한 초과 시 절반씩 줄여 재시도한다.

**완료 (Phase 8-4: 검색 속도·권한 신호)**
- 권한 확인을 **병렬 + 캐시**로 바꿨다. 예전엔 후보 문서마다 순차로 외부 API를 호출해 최악의 경우
  20회 × 10초가 그대로 검색 지연이 됐다. 이제 확인 대상(저장소/채널/파일)을 먼저 중복 제거하고
  스레드 풀로 동시에 확인하며, 결과를 5분간 캐시한다. 실측: **순차 8.68초 → 병렬 1.25초 →
  캐시 적중 0.004초**.
- 권한 확인 결과를 `allowed/denied/auth_failed/unavailable` 넷으로 구분했다. 예전엔 전부 `False`로
  뭉개져서 **토큰이 죽었을 때도 문서가 아무 설명 없이 사라졌다**. 이제 토큰 만료는 "다시 연결해
  주세요", 일시적 실패는 "일부 문서가 빠졌을 수 있습니다"로 응답에 실려 프론트가 안내한다
  (`SearchResponse.disconnectedSources` / `degradedSources`).

**완료 (Phase 8-5: 프론트엔드)**
- 모든 API 호출을 `utils/apiClient.js`로 통일. **401이면 세션을 정리하고 "세션이 만료되었습니다"를
  띄우며 로그인 화면으로** 보낸다 — 예전엔 JWT가 만료돼도 사이드바엔 이메일이 그대로 보이는데
  연동은 0/5, 검색은 먹통, 할 일은 빈 목록인 "좀비 로그인" 상태가 됐다.
- 검색 실패를 화면에 표시한다. 예전엔 `catch`가 콘솔에만 찍고 초기 화면으로 되돌려서, 서버가 꺼져
  있어도 "검색 버튼이 안 눌린 것"처럼 보였다. 이제 이유를 띄우고 이전 결과는 유지한다.
- **연동 직후 자동 갱신**: 백그라운드 수집이 끝나는 대로 홈 화면 문서 수가 올라간다(연결 후 약
  100초간 통계 폴링). 예전엔 F5를 눌러야만 반영됐다.
- 할 일 리스트: 토글/조회 실패 시 **목록이 통째로 사라지던 문제** 수정(오류만 표시하고 목록 유지),
  **삭제 기능 추가**(지울 방법이 아예 없었음), LLM이 같은 임시 id("a1")에 다른 할 일을 담았을 때
  새 항목이 이미 "완료"로 표시되던 상태 이월 버그 수정(내용이 같을 때만 상태 유지).
- **연동 해제 기능 추가**(`DELETE /api/v1/auth/link/{provider}` + 사이드바 버튼) — 해제 시 그 사람이
  그 소스로 가져왔던 문서도 함께 정리된다(다른 사람도 연동한 문서는 그 사람 몫으로 남음).
- 팝업 연동 안정화: 성공 후 사용자가 팝업을 직접 닫으면 **성공했는데 "연결 창이 닫혔습니다" 오류**가
  뜨던 경쟁 상태 수정, 언마운트 시 인터벌/리스너 정리(사이드바를 접으면 "연결 중..."에 갇히던 문제).

**완료 (Phase 8-6: 만료 토큰 갱신 — 실사용 중 발견)**
- 검증 도중 GitHub·GitLab 토큰이 둘 다 401로 죽어 있는 것을 발견했다. 원인을 보니 **GitLab OAuth
  access token은 기본 2시간이면 만료되는데 `refresh_token`을 Google에만 저장하고 GitHub/GitLab은
  버리고 있었다** — 즉 GitLab 연동은 연결 두 시간 뒤부터 계속 죽어 있었고, 사용자에게는 그냥
  "그 소스 문서가 검색에 안 나오는" 것으로만 보였다.
- `linked_accounts.refresh_token` 컬럼 추가(기존 DB 자동 마이그레이션), 연동 시 저장,
  `auth.refresh_provider_access_token()`으로 갱신. 검색 중 토큰 만료가 감지되면 **자동으로 갱신해
  한 번 재시도**하고, 백그라운드 재동기화도 401이면 갱신 후 재시도한다. GitLab은 갱신할 때마다
  refresh_token도 새로 발급(1회용)하므로 함께 저장한다.
- 단, 이 수정 이전에 연결해둔 GitHub/GitLab은 refresh_token이 저장돼 있지 않으므로 **한 번은
  다시 연결**해야 한다.

**남은 작업(선택)**: 수집 진행률을 보여주는 `/api/v1/sync-status`(현재는 통계 폴링으로 대체),
대용량 문서 청킹(현재는 임베딩 입력을 잘라서 넣음), 배포 구성.

## 5. 비기능 요구사항

| 항목 | 요구사항 |
|---|---|
| 로깅 | `print()`에 이모지 사용 금지 (Windows cp949 콘솔에서 UnicodeEncodeError로 실제 결과가 mock 폴백에 덮여씌워지는 사고를 Phase 1에서 겪음). 새 커넥터도 동일 규칙 적용 |
| 비용 | 검색 1회당 GPT-4o 호출 1회. 재동기화는 증분이라(FR-16) 바뀐 문서만 임베딩한다 — 문서가 안 바뀌면 주기당 임베딩 비용은 0에 수렴 |
| 보안 | 모든 토큰은 `.env`, git에 커밋되지 않음(`.gitignore` 반영 완료). 커넥터는 읽기 전용 스코프만 요청 |
| 데이터 신선도 | 실시간 아님. Phase 7부터 계정 연동 시점에 그 사람 접근 가능 문서 전체를 자동 수집하고, 이후로도 5개 소스 전부 15분 간격 백그라운드 폴링으로 재동기화한다(`AUTO_RESYNC_INTERVAL_SECONDS`) — 즉 최대 15분 지연이 있는 정도지 진짜 실시간(웹훅)은 아님 |

## 6. 알려진 이슈 / 운영 노트 (Phase 0~1에서 확인됨)

1. Chroma는 다른 프로세스가 쓴 내용을 자동으로 다시 읽지 않는다 → **적재 후 반드시 API 서버 재시작**
   (단, Phase 7의 계정 연동 시 자동 수집은 API 서버와 같은 프로세스 안에서 실행되므로 이 제약이 없다 —
   이 재시작 규칙은 `python rag_pipeline.py --source X` 오프라인 스크립트 경로에만 해당)
2. Windows 콘솔 인코딩(cp949) 때문에 이모지 print가 크래시를 유발할 수 있다 → 로그에 이모지 쓰지 않기
3. 문서 메타데이터에 `title`이 빠지면 검색 결과 제목이 전부 "문서"로 뜬다 → 커넥터는 반드시 `title` 채울 것

## 7. 오픈 이슈 (결정 보류)

- Slack 워크스페이스에 채널이 매우 많아질 경우 `conversations.list` 페이지네이션/레이트리밋 처리 — 기본
  페이지네이션 구현만 하고, 실제 채널 수가 많아지면 그때 배치/큐 방식 검토
- 여러 소스에서 사실상 동일한 결정이 중복 추출될 때 `decisionTrail` 중복 제거 여부 — 일단 중복 허용, 사용자
  피드백 보고 재검토
- **가입 제한(회사 이메일 도메인)**: 실사용 논의 중 "지금은 제한 안 함, 나중에" 결정 — 지금은 이메일
  형식만 맞으면 누구나 가입 가능한 상태 그대로 둠. 실제 롤아웃 전에는 `EMAIL_SIGNUP_DOMAIN` 같은
  env var로 도메인 제한을 켤 수 있게 만들 필요 있음
- **비밀번호 재설정/이메일 인증**: 실사용 논의 중 "SMTP 없음, 일단 스킵" 결정 — 지금은 비밀번호를
  잊으면 복구할 방법이 없음(DB에서 직접 고치는 것 외엔). 회사 SMTP나 이메일 발송 서비스가 정해지면
  구현
- **배포 인프라**: 실사용 논의 중 "지금은 사내망/로컬에서만" 결정 — 외부 클라우드/도메인/HTTPS
  세팅은 보류. 실제 여러 사람이 접속할 서버가 정해지면 Docker/리버스 프록시 등 배포 구성 필요
- ~~주기적 자동 재동기화~~ — **해결됨**: "회사 실사용" 전환 결정으로 Google Drive도 FR-10에서
  refresh_token 방식으로 전환해, 5개 소스 전부 FR-15의 15분 간격 백그라운드 폴링 대상이 됐다.
- **동명이인 배정 (Phase 7에서 제기)**: 성 없이 이름만 언급되고 그 이름을 가진 사람이 여럿이면(예: "승현님"
  — 이승현/박승현) 현재는 원문 표현을 그대로 남기고 완전한 이름을 추측하지 않도록만 해뒀다(FR-2 참고).
  워크스페이스 전체 인물 로스터(연동 계정들의 실명 목록)를 프롬프트에 후보로 제공해 LLM이 "이 후보들
  중에 매칭 안 됨/모호함"을 더 명시적으로 판단하게 하는 개선은 아직 안 함
