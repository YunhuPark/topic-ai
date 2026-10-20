# 인수인계 — 다른 환경에서 이어서 작업하기

> 이 문서는 "새 노트북에서 이 저장소를 받아 이어서 개발한다"를 위한 것이다.
> 기능 명세는 [PRD.md](PRD.md), 설치·연동 설정은 [README.md](README.md)를 본다.
> 마지막 갱신: 2026-09-22

---

## 0. 가장 먼저 알아야 할 것

**git에 없는 것이 세 개 있고, 이게 없으면 앱이 안 돈다.** 전부 `.gitignore` 대상이다.

| 파일 | 내용 | 새 노트북에서 |
|---|---|---|
| `backend/.env` | API 키·OAuth 시크릿 전부 | **직접 옮겨야 함** (아래 1-3) |
| `backend/app.db` | 계정, 연동 정보, 검색 기록, 할 일 | 안 옮겨도 됨 — 새로 가입 |
| `backend/chroma_db/` | 수집된 문서 + 임베딩 | 안 옮겨도 됨 — 연동하면 자동 재수집 |

즉 새 노트북에서는 **회원가입 → 5개 소스 연동**을 다시 하면 문서가 자동으로 다시 채워진다.
(수집은 증분이라 두 번째부터는 30초 안에 끝난다.)

---

## 1. 새 노트북 세팅

### 1-1. 저장소 + 프론트엔드

```bash
git clone https://github.com/YunhuPark/topic-ai.git
cd topic-ai
npm install
npm run dev          # http://localhost:5173
```

### 1-2. 백엔드

```bash
cd backend
python -m venv venv
venv\Scripts\activate           # Windows
# source venv/bin/activate      # macOS/Linux
pip install -r requirements.txt
```

### 1-3. `backend/.env` 만들기

기존 노트북의 `backend/.env`를 그대로 복사하는 게 가장 빠르다(USB·비밀번호 관리자 등).
새로 만든다면 아래 키가 필요하다 — **값은 각 서비스 콘솔에서 다시 발급**해야 하고,
발급 절차는 README.md의 "커넥터 설정" / "계정 연결용 OAuth 앱 설정" 절에 있다.

```bash
# 필수
OPENAI_API_KEY=
JWT_SECRET=                      # python -c "import secrets; print(secrets.token_hex(32))"

# 계정 연결용 OAuth 앱 (연동하려는 소스만 채우면 됨)
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GITHUB_OAUTH_CLIENT_ID=
GITHUB_OAUTH_CLIENT_SECRET=
GITLAB_OAUTH_CLIENT_ID=
GITLAB_OAUTH_CLIENT_SECRET=
SLACK_OAUTH_CLIENT_ID=
SLACK_OAUTH_CLIENT_SECRET=
SLACK_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/api/v1/auth/link/slack/callback
NOTION_OAUTH_CLIENT_ID=
NOTION_OAUTH_CLIENT_SECRET=

# 선택 — 관리자 일괄 수집(CLI)용. 계정 연동만 쓸 거면 없어도 된다
NOTION_TOKEN=
SLACK_BOT_TOKEN=
GITHUB_TOKEN=
GITHUB_REPOS=
GITLAB_TOKEN=
GITLAB_PROJECTS=

# 선택 — 자동 재동기화 주기(기본 900초)
# AUTO_RESYNC_INTERVAL_SECONDS=900

# 선택 — 회원가입 허용 도메인 제한(콤마로 여러 개). 비워두면 아무 이메일이나 가입 가능
# SIGNUP_ALLOWED_DOMAINS=

# 선택 — 배포 시 프론트엔드 실제 주소(콤마로 여러 개). 기본값은 localhost:5173/127.0.0.1:5173
# FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

> OAuth 리디렉션 URI는 전부 `localhost:8000` 기준이라 노트북이 바뀌어도 그대로 쓸 수 있다.
> 단 Slack만 `127.0.0.1`을 쓴다(Slack이 localhost를 거부해서).

### 1-4. 실행

```bash
cd backend
venv\Scripts\activate
uvicorn main:app --reload --port 8000
```

브라우저에서 http://localhost:5173 → 회원가입 → 사이드바 "연동 관리"에서 소스 연결.

---

## 2. 지금 어디까지 돼 있나

`main` 브랜치 최신 커밋(`f5a63a7`)까지 아래가 전부 반영돼 있다.

**동작하는 것**
- 5개 소스(Google Drive/GitHub/GitLab/Slack/Notion) 계정 연동 → 그 사람이 접근 가능한 문서 전체 자동 수집
  (GitHub/GitLab은 Issue/PR·MR뿐 아니라 저장소·프로젝트당 "설명+README" 문서도 1개씩 만든다 —
  Issue/PR이 하나도 없는 저장소도 검색에 잡히게 하기 위함, 2026-09-21 추가)
  **Google Drive는 지원 형식(Docs/Sheets/Slides/PDF/docx/xlsx/pptx/hwpx)이 아니어도 폴더만 빼고
  전부 목록에 올린다**(2026-09-21 추가) — 본문 추출이 안 되면 파일명만 색인. 단 코드/빌드
  산출물(.py/.pyc/.class/.lock 등)과 .git·pip .dist-info 내부 파일(RECORD/METADATA/LICENSE,
  git 객체 해시명 등)은 이름·확장자로 걸러서 애초에 목록에도 안 올린다 — 실사용 중 사용자
  Drive에 venv/.git이 통째로 들어있어서 필터 없이 색인했다가 4900여 개(대부분 쓸모없는 빌드
  산출물)가 실제 임베딩 비용을 태우며 쌓인 사고가 있었다(`gdrive_connector._JUNK_EXTENSIONS`/
  `_looks_like_git_internal` 참고). 이 블록리스트는 이번에 발견된 패턴 기준이라 완전하지 않을
  수 있다 — 비슷한 노이즈가 또 보이면 같은 방식으로 추가할 것.
  **Slack은 메시지에 첨부된 파일(files 배열)도 색인한다**(2026-09-21 추가) — PDF/DOCX/일반
  텍스트류는 gdrive_connector와 같은 파서로 본문까지, 그 외(이미지 등)는 파일명만.
  **GitHub/GitLab도 README뿐 아니라 저장소·프로젝트의 파일 트리 전체(실제 소스 코드 포함)를
  색인한다**(2026-09-22 추가) — 저장소당 500개 상한, 8개 스레드로 병렬 fetch, 텍스트로
  디코드되는 파일은 본문까지 그 외는 파일명만(§4 알려진 함정 8·9 참고: GitHub 보조 rate
  limit과 커밋된 venv 노이즈).
  **Notion도 페이지 안의 표(table)·이미지 캡션, 데이터베이스 컨테이너 자체(이름/설명/컬럼
  구성)를 색인한다**(2026-09-22 추가, 2026-09-23 실데이터 검증 완료) — 예전엔 표 내용이
  통째로 안 읽히고, 데이터베이스 이름으로 검색해도 안 걸렸다. 이미지 본문(OCR)·임베드/
  북마크/파일 블록은 여전히 범위 밖.
  실제 Notion 데이터베이스 3개(사용자가 새로 공유)로 검증하면서 **진짜 버그를 하나
  발견·수정함**: `_resource_of()`(main.py)가 데이터베이스 컨테이너 문서의 id
  (`notion-db-{database_id}` 형식)에서 "notion-" 접두사만 벗겨내는 바람에, 권한 확인
  대상 리소스 id에 "db-"가 그대로 섞여 들어가(`db-d86bfec5-...`) Notion API 호출이 항상
  실패했다 — 그 결과 데이터베이스 컨테이너 문서는 검색 결과·요약(`/api/v1/summarize-
  document`)에서 조용히 제외되거나 403을 냈다(제목이 검색어와 정확히 일치해서 구제
  후보로 잡혀도 권한 확인 단계에서 탈락). `_resource_of`가 `notion-db-` 접두사를 먼저
  검사해서 `"db:{database_id}"` 형태로 반환하도록 고치고, `_check_notion_access()`가
  그 "db:" 표시를 보고 `GET /v1/pages/{id}`(페이지용) 대신 `GET /v1/databases/{id}`
  (데이터베이스용, Notion API에서 별개 엔드포인트)를 호출하도록 분기 추가. 이 버그는
  이전 세션에서 합성 데이터로만 검증했을 때는 권한 확인 로직 전체가 얽힌 실제 검색
  흐름을 안 거쳐서 못 잡았던 것 — 실데이터 검증이 아니면 드러나지 않는 종류의 버그였다.
  수정 후 실제 데이터베이스가 검색 1위(관련도 0.59)로 나오고, AI 요약도 속성(태그/날짜/
  이름)을 정확히 반영하는 것까지 확인함.
  **동명이인 별칭 사전(2026-09-22 추가)** — 사이드바 "팀원 관리"에서 정식 이름 + 별칭
  목록(콤마 구분)을 등록해두면(`people` 테이블, `GET/POST/PATCH/DELETE /api/v1/people`),
  검색·문서별 AI 요약을 생성할 때마다(`search_documents`/`summarize_document` 양쪽 다)
  그 목록을 프롬프트의 `[알려진 사람 목록]` 섹션에 넣어준다. "승현님"처럼 성 없이 이름만
  **동명이인 별칭 사전(2026-09-22 추가)** — 사이드바 "팀원 관리"에서 정식 이름 + 별칭
  목록(콤마 구분)을 등록해두면(`people` 테이블, `GET/POST/PATCH/DELETE /api/v1/people`),
  검색·문서별 AI 요약을 생성할 때마다(`search_documents`/`summarize_document` 양쪽 다)
  그 목록을 프롬프트의 `[알려진 사람 목록]` 섹션에 넣어준다. "승현님"처럼 성 없이 이름만
  나온 담당자를 LLM이 이 목록에서 정확히 한 명과만 매칭되면 정식 이름으로 정규화하고,
  목록이 비었거나 일치하는 사람이 없거나 같은 별칭이 두 명 이상과 겹치면(동명이인 케이스)
  기존처럼 대화에 나온 표현 그대로("승현님") 남긴다 — 오추측으로 엉뚱한 사람에게 할 일이
  배정되는 게 더 나쁘다는 원칙은 그대로 유지. 합성 데이터로 세 경우(일치/불일치/애매) 전부
  검증함. 첫 프롬프트 문구는 애매한 경우에도 목록에 먼저 나온 사람을 임의로 골라버리는
  문제가 있었고(목록 순서에 편향), "목록 순서는 누가 더 맞는지와 아무 상관 없다"는 문장을
  명시적으로 추가하고 나서야 안정적으로 원문 그대로 남기는 쪽으로 바뀌었다 — GPT-4o가
  이런 종류의 규칙은 예시를 명시적으로 주지 않으면 잘 안 지키는 경향이 있다는 걸 보여준
  사례. 자동 별칭 제안(기존 색인 문서의 author 값 스캔)이나 소급 갱신(과거 저장된 할 일
  갱신)은 v1 범위 밖.
- **문서 청킹(2026-09-22 추가)** — 예전엔 문서 하나당 Chroma 벡터 행이 1개뿐이라, 임베딩
  API 호출 직전(`_EMBED_TOKEN_BUDGET=7500` 토큰)에서 넘치는 텍스트는 뒷부분을 그냥 잘라
  버렸다(어림치 문자 비율 절단) — 벡터가 항상 문서 앞부분만 대표해서, 긴 문서(GitHub 저장소
  파일 전체 색인·대용량 Drive/Notion 문서 등)의 뒷부분 내용은 검색해도 못 찾는 사각지대가
  있었다. 이제 `rag_pipeline._chunk_text()`가 문서가 실제로 클 때만(`_CHUNK_TARGET_TOKENS
  =1200`, 문단 경계 우선 존중, `_CHUNK_OVERLAP_TOKENS=150` 겹침) 여러 청크로 쪼개 여러 벡터
  행으로 저장한다. 대다수 문서(대부분의 Slack 메시지·짧은 문서)는 그대로 청크 1개 —
  기존 id·동작과 완전히 동일. 쪼개진 문서는 chunk 0만 기존 id를 유지하고 chunk 1부터
  `{base_id}::chunk-{i}` 접미사가 붙으며, 모든 청크 행엔 `baseId`(원래 논리 문서 id)·
  `chunkIndex`·`chunkCount` 메타데이터가 붙는다. `content` 메타데이터는 항상 전체 원본
  텍스트를 모든 형제 청크 행에 중복 저장해서(임베딩 입력인 `page_content`만 청크 슬라이스),
  검색 결과 표시·AI 요약·`/api/v1/summarize-document`·통계는 청크 중 아무거나 하나를
  대표로 삼아도 항상 문서 전체를 본다 — 그래서 이 엔드포인트들은 거의 수정 없이 그대로
  동작. 대신 새로 손댄 곳: `search_documents()`의 채점 정렬 직후 `baseId` 기준 1등만 남기는
  중복 제거(같은 문서의 여러 청크가 검색 결과 4자리 중 여러 개를 차지하는 것 방지),
  `generate_ai_summary`에 넘기는 문서를 이긴 청크 조각이 아니라 항상 전체 원문으로
  재구성(안 하면 AI 요약이 문서 전체가 아니라 매칭된 청크 한 조각만 보는 회귀), `_resource_of`
  의 권한 리소스 키를 `baseId` 우선으로(gdrive/notion은 id 접두사만 잘라 리소스 키를 만들어서
  청크 접미사가 남으면 오염됨), `_title_match_candidates`/`get_stats`도 `baseId` 중복 제거,
  그리고 증분 동기화의 `_known_documents`/`_prune_missing_documents`를 `baseId` 기준으로
  재작성(안 하면 커넥터가 돌려주는 base id와 절대 안 겹쳐서 청크로 쪼개진 문서가 매 동기화마다
  "원본에서 사라진 문서"로 오인되어 지워지는 정합성 버그가 있었음 — 스크래치 Chroma로
  재현·수정 확인함). 검증은 스크래치 Chroma 디렉터리(`./chroma_db`는 안 건드림)에 합성 문서로
  청크 분할·검색 재현율·증분 동기화 2연속 호출(형제 청크 안 지워짐 확인)·재청크로 청크 수
  줄어들 때 고아 청크 정리·`syncedBy`-only 갱신이 모든 형제 청크에 반영되는지·통계 중복
  제거를 전부 확인했고, 실제 운영 DB(4327문서, 전부 아직 청킹 전 상태)로도 검색·요약·
  summarize-document 엔드포인트가 기존과 동일하게 동작하는지 확인함(기존 문서는 `baseId`
  메타데이터가 없어 `id`로 자동 폴백 — 다음 증분 동기화 때 자연히 재평가되며, 굳이 지금
  전체 재동기화를 강제할 필요는 없음).
- 15분 간격 백그라운드 **증분** 재동기화 (바뀐 문서만 다시 임베딩)
- 권한 인지형 검색 — 검색하는 사람 본인 토큰으로 문서마다 실시간 확인(기본 거부)
- GPT-4o 요약 + 의사결정 흐름 + 할 일 리스트 후보(담당자 자동 추론)
- 대시보드 통계는 **본인이 연동한 문서만** 집계
- 연동 해제
- **할 일 리스트는 검색할 때마다 자동 저장되지 않는다**(2026-09-21 변경) — 검색 결과의
  "할 일 리스트" 탭에 후보로만 뜨고, 사용자가 "+ 추가"를 눌러야 `POST /api/v1/action-items`로
  저장된다(예전엔 테스트 검색까지 전부 자동 저장돼서 목록이 무의미하게 쌓였다). 저장된 항목은
  체크박스 한 번에 완료/미완료만 토글(예전 대기→진행중→완료 3단계 순환 폐지), 진행중/완료/전체
  필터 탭 제공.

**실측 성능**
| 항목 | 값 |
|---|---|
| 첫 동기화(325문서) | 약 7분 / 임베딩 324건 |
| 이후 증분 동기화 | 30초 / 임베딩 0~1건 |
| 검색 권한 확인 | 1.25초 (캐시 적중 0.004초) |

**남은 선택 과제**
- 수집 진행률 표시용 `/api/v1/sync-status` (지금은 연동 직후 통계 폴링으로 대체)
- 비밀번호 재설정(SMTP 필요) — 실사용 논의 중 "나중에"로 보류. **팀 기능을 실사용으로
  확장하면(여러 명이 회원가입) 사실상 필수**가 됨 — 그때 같이 진행 권장.
- **팀 기능 — 1단계(데이터 모델+가입/초대 API, 2026-09-23) + 2단계(할 일/별칭 사전/통계
  공유 + 프론트 UI, 2026-09-23) 완료.** `teams`/`team_members`/`team_invites` 테이블,
  `POST/GET /api/v1/teams`, `POST /api/v1/teams/{id}/invites`(owner 전용), `POST
  /api/v1/teams/join`(초대 코드로 가입), `GET/DELETE /api/v1/teams/{id}/members`. 이메일
  발송(SMTP)이 없어서 Slack/Discord처럼 **초대 코드/링크 방식**(`secrets.token_urlsafe(12)`,
  만료 없음). `people`/`action_items` 테이블에 nullable `team_id` 컬럼 추가(마이그레이션
  가드 패턴, 기존 행은 전부 `NULL`=개인 스코프 그대로) — 모든 관련 엔드포인트가 선택적
  `team_id` 쿼리/바디 파라미터를 받아, 있으면 그 팀 멤버십을 확인(`_require_team_access`)한
  뒤 팀 전체가 공유하는 행을 읽고 쓴다. `get_stats`도 `team_id`가 있으면 팀 멤버 전원의
  `syncedBy`를 합쳐서 집계(팀이 연동한 총 문서 수). **검색 결과(search_documents) 자체는
  일부러 안 건드림** — 팀원이 문서를 가져왔어도 보는 사람 본인의 실시간 OAuth 토큰으로
  그 소스 접근 권한을 여전히 확인하며, 원본 소스의 진짜 권한을 우회하지 않는다(사용자가
  명시적으로 선택한 방향 — 보안 트레이드오프 질문에 "본인이 직접 접근 가능한 것만" 선택).
  프론트: `src/utils/teamStore.js`(localStorage에 "현재 팀" id 저장, authStore.js와 같은
  패턴), `App.jsx`의 `currentTeamId` state를 `user`처럼 props로 내려줌(이 코드베이스에
  Context/전역 스토어가 없어서 기존 관례 그대로 유지), 사이드바에 "**내 팀**" 아코디언
  신규 추가(`TeamManager.jsx`) — 기존 "팀원 관리"(별칭 사전, `PeopleManager.jsx`)와 이름이
  겹치므로 의도적으로 다르게 명명함. "내 팀"에서 팀 생성/전환 드롭다운/초대 코드 생성+복사/
  참여/멤버 목록/내보내기/나가기까지 가능. curl로 팀 간 공유 격리(팀 스코프로 만든 건
  다른 팀원에게 보이고, 개인 스코프는 그대로 안 섞임, 비멤버는 403)까지 검증 완료 — 단
  프론트엔드 실제 브라우저 클릭 테스트는 아직 안 함(빌드만 확인), 사용자가 직접 확인 필요.
  **실사용 중 발견·수정한 중요 버그(2026-09-23)**: `people`/`action_items`의 예전 UNIQUE
  제약(`user_id`+`display_name` / `user_id`+`query`+`source_item_id`)이 `team_id`를 몰라서,
  같은 사용자가 **개인 사전에 이미 등록해둔 이름을 팀 사전에도 등록하려 하면**(또는 그
  반대, 혹은 서로 다른 두 팀에) `team_id`만 다르고 나머지 컬럼이 같다는 이유로 그대로
  충돌해 500 에러가 났다(프론트에선 "서버에 연결할 수 없습니다"로 보여서 마치 백엔드가
  죽은 것처럼 오인됐지만, 실제로는 서버는 살아있고 그 요청 하나만 실패한 것이었음). SQLite는
  `ALTER TABLE`로 기존 제약을 못 지우므로, 두 테이블을 제약 없는 새 테이블로 재생성해
  데이터를 그대로 옮기고 **스코프별 부분(partial) UNIQUE 인덱스**(`people_personal_unique`
  `WHERE team_id IS NULL`, `people_team_unique` `WHERE team_id IS NOT NULL`, `action_items`도
  동일 패턴)로 교체했다 — 개인 스코프와 팀 스코프가 서로 다른 인덱스라 이름이 겹쳐도 더 이상
  충돌하지 않는다. 실 서비스 DB(`app.db`)에 직접 적용하기 전에 스크래치 사본으로 먼저
  마이그레이션·재현 테스트를 돌려 확인했고, 적용 전 `app.db.bak-<timestamp>`로 백업도
  남겨뒀다. 적용 후 실제 계정으로 같은 요청을 다시 보내 500이 사라지고 개인/팀 데이터가
  둘 다 온전한 것까지 확인함.
  **코드 리뷰로 추가 발견·수정한 프론트 버그 3개**: (1) "이 팀 나가기"가 `currentUserId`
  없이 "목록에서 첫 번째 non-owner 멤버"를 지우는 로직이라 본인이 아니라 엉뚱한 멤버가
  쫓겨날 수 있었음 — `user.id`를 App→Sidebar→TeamManager로 내려서 본인만 정확히 지우도록
  수정. (2) 로그인/회원가입 API는 `{token, email}`만 주고 `id`는 안 줘서, 로그인 직후(새로고침
  전)엔 `user.id`가 `undefined`라 (1)의 수정도 무력화됐음 — 로그인 성공 직후 `/api/v1/auth/me`
  를 한 번 더 호출해 `id`까지 채우도록 수정. (3) 나간 뒤에도 "현재 팀" 선택이 안 풀려서
  이후 모든 요청이 403 나던 문제 — 본인이 나가면 자동으로 개인 스코프로 되돌리도록 수정.
  **UI 단순화(2026-09-23, 사용자 피드백 반영)**: "새 팀 만들기"/"초대 코드로 참여" 폼을
  항상 펼쳐두던 걸 텍스트 링크로 접어서, 누른 것 하나만 펼쳐지게 바꿈(`TeamManager.jsx`
  `openForm` state). 초대 코드 "복사" 버튼이 `people-manager__delete`(원래 × 아이콘용,
  글자 큼) 클래스를 재사용해서 글자가 과하게 컸던 것도 전용 클래스(`team-manager__copy-
  button`)로 분리.
- **배포는 실제 서버(도메인/IP)로 지금 당장 띄우는 것 자체는 아직 안 함** — "코드만 배포
  가능하게 정리"까지만 이번에 완료(2026-09-22). 조사해보니 `FRONTEND_ORIGINS`·5개
  `*_OAUTH_REDIRECT_URI`·`VITE_API_BASE`·`SIGNUP_ALLOWED_DOMAINS`는 이미 전부 환경변수로
  빠져 있었고(README.md의 "배포" 절에 이미 상세히 문서화돼 있었음), 실제 빠진 건 딱 하나 —
  `src/components/AuthPanel.jsx`의 로그인/회원가입 요청이 `apiClient.js`의 공유 `API_BASE`
  (`VITE_API_BASE` 반영)가 아니라 자기만의 하드코딩된 `'http://localhost:8000'`을 따로 쓰고
  있어서, `VITE_API_BASE`를 배포 주소로 설정해도 로그인 화면만 여전히 localhost로 요청을
  보내는 버그였다(다른 화면은 전부 정상). `apiClient.js`의 `API_BASE`를 import하도록 고쳐서
  해결. 그 외 `backend/.env.example`·루트 `.env.example` 신규 추가(기존엔 `.env`만 있고
  예시 파일이 없어서 뭘 채워야 하는지 실제 `.env`를 봐야만 알 수 있었음). 실제 서버에
  올리는 것 자체(Docker/리버스 프록시/도메인·HTTPS 설정)는 여전히 범위 밖 — 필요해지면
  README.md "배포" 절 그대로 따라가면 됨.
- **UI 전면 다듬기(2026-09-28)**: 반응형(모바일 드로어 사이드바, 로그인 화면 포함),
  로그인 카드가 왼쪽 위에 붙어버리던 CSS 버그(`.auth-gate`에 불필요한 `position: relative`가
  `.auth-modal__backdrop`의 `position: fixed`를 같은 우선순위·나중 선언으로 덮어씀) 수정,
  검색 결과 카드가 `glass-panel` 없이 `glass-panel-hover`만 있어서 평소엔 배경/테두리가
  아예 안 보이던 버그 수정, 잘못된 CSS 변수(`var(--color-text-secondary, #6b7280)` 같은
  존재하지 않는 토큰 + 하드코딩 fallback) 3곳 발견·수정, 로딩/스피너·팀 관리 UI 등 다수
  다듬음. 상세는 각 커밋/세션 로그 참고.
- **LLM 비용 최적화 + 백엔드 추상화(2026-09-28)**: OpenAI 크레딧 소진으로 검색이 500 에러
  나는 걸 계기로, `SUMMARY_MODEL`을 `gpt-4o` → `gpt-4o-mini`로 바꿈(비용 약 1/15, 이
  구조화 JSON 요약 작업엔 품질 차이가 크게 체감되지 않음). 여기서 더 나아가 "회사 보안
  정책상 외부 LLM API 자체를 못 쓰는 환경"에 대응하기 위해 `backend/llm_backend.py`를
  새로 만들어 LLM/임베딩 호출을 백엔드 추상화했다 — `LLM_BACKEND` 환경변수(기본값
  `openai`)로 `ollama`를 선택하면, 회사 내부망(또는 로컬)에 띄운 Ollama 서버로 임베딩·
  요약을 전부 대체할 수 있다(문서 내용이 외부로 전혀 안 나감). `rag_pipeline.py`의
  `OllamaDirectEmbeddings`(Chroma용 임베딩 인터페이스 구현)와 `generate_ai_summary`의
  백엔드 분기, `main.py` 기동 시 `ollama_health_check()`로 서버 미설치/모델 미다운로드를
  즉시 경고하는 것까지 넣음. **주의: 이 세션에서는 Ollama 자체를 설치하지 않아서 openai
  경로(기존 동작)만 실제 검색으로 검증했고, ollama 경로는 "서버가 없을 때 500 대신 graceful
  하게 경고하고 죽지 않는다"까지만 확인함** — 실제 로컬 모델로 품질/응답속도를 검증하려면
  Ollama 설치(`ollama pull llama3.1`, `ollama pull nomic-embed-text`) 후 `LLM_BACKEND=ollama`로
  실제 검색을 한 번 돌려봐야 한다.
- **검색 응답 시간 계측(2026-09-28)**: `/api/v1/search`에 벡터 검색/재정렬, 소스별 실시간
  권한 확인, LLM 요약 세 단계의 소요 시간(ms)을 재서 `SearchResponse.timing`(`models.py`의
  `SearchTiming`)으로 내려주고, 백엔드 콘솔에도 한 줄 로그로 남긴다. 프론트(`AISummaryPanel`
  헤더의 "⏱ N초" 배지, hover 시 단계별 분해 tooltip)에도 표시함 — 발표/PPT용 실측 응답속도
  숫자가 필요할 때 이 배지를 그대로 캡처하거나 백엔드 로그에서 평균을 뽑으면 된다.
- **동명이인 배정 — 워크스페이스 전체 로스터까지 확장(세션 간 작업, 2026-09-28~10-06)**:
  이 세션에서는 [알려진 사람 목록](수동 별칭 사전) + [문서 작성자 후보](이번 검색 결과
  문서들의 실제 작성자)까지 2단계로 넣었는데, 그 이후 어느 시점에 `backend/db.py`에
  `workspace_authors` 테이블(동기화마다 문서 author를 누적 저장, `upsert_workspace_authors`/
  `get_workspace_authors`)이 추가되고 `rag_pipeline.py`의 `generate_ai_summary`가
  `workspace_authors` 파라미터와 `[워크스페이스 인물 로스터]` 3단계 후보까지 받도록 더
  확장돼 있었다 — PRD §7이 원래 요청했던 "이번 검색에 안 잡힌 문서의 작성자까지 포함한
  전체 로스터"가 완성된 상태. 세 후보 목록 모두 "두 명 이상 겹치면 임의로 안 찍고 원문
  표현 유지" 안전 규칙을 동일하게 따른다. **이 변경이 정확히 어느 세션/커밋에서 들어왔는지
  이 핸드오프를 쓰는 시점엔 불명확함(git 커밋은 아직 없음, working tree에만 있음)** —
  이어서 작업할 때는 `db.py`의 `workspace_authors` 섹션과 `rag_pipeline.py`의
  `generate_ai_summary` 전체를 한 번 읽고 시작할 것.
- **계정당 하루 LLM 호출 한도(2026-10-06)**: 포트폴리오/데모 목적상 `SIGNUP_ALLOWED_DOMAINS`를
  계속 비워두기로(=가입 제한 없음) 결정하면서, 공개 배포 시 낯선 방문자가 검색을 반복해
  OpenAI 크레딧을 소진시킬 수 있는 리스크를 막기 위해 추가. `main.py`의
  `_check_daily_llm_quota()`가 `/api/v1/search`와 `/api/v1/summarize-document`(문서 클릭
  재요약 — LLM이 호출되는 유일한 다른 경로) 둘 다 요청 처리 시작 전에 24시간 롤링 한도
  (`DAILY_SEARCH_LIMIT`, 기본 50)를 넘었는지 확인하고 넘었으면 429. 두 엔드포인트가 같은
  카운터(`search_history` 테이블)를 공유해야 재요약만 반복해서 한도를 우회하는 걸 막을 수
  있는데, 그러면서 "최근 검색"/"이번 주 검색" UI에 재요약 호출까지 섞여 보이는 부작용이
  생겨서 `search_history`에 `kind`('search' | 'resummarize') 컬럼을 추가하고 `db.py`를
  `get_search_history`/`count_searches_since`(둘 다 'search'만, UI용)와 새
  `count_llm_calls_since`(둘 다 포함, 한도 체크용)로 분리했다. 기존 행은 `kind`가 NULL인데
  이 컬럼이 생기기 전엔 검색만 기록됐으므로 NULL도 'search'로 취급하도록 쿼리에서
  처리함(`WHERE kind IS NULL OR kind = 'search'`). 프론트엔드는 추가 작업 없음 —
  `apiClient.js`의 `apiFetch`가 이미 모든 비-2xx 응답의 `detail`을 그대로 사용자에게
  보여주는 범용 에러 처리라, 429의 한글 메시지도 자동으로 뜬다.
- **배포 플랫폼 Oracle Cloud → Render로 전환(2026-10-11)**: Oracle Cloud Free Tier 가입이
  카드 인증(성공) 이후 "계정을 생성하는 중 오류가 발생했습니다"라는 모호한 에러로 계속
  실패 — 고객지원 채팅에 문의했으나 "처리할 수 없다"는 답변만 받고 더 이상 진전이 안 돼
  Render로 방향을 바꿨다. README.md "비용"/"배포" 논의에서 이미 비교해둔 대안(Vercel은
  서버리스라 SQLite/Chroma 영구 디스크·백그라운드 재동기화 스레드와 안 맞음) 중 가장
  현실적인 선택.
  레포 루트에 `render.yaml`(Blueprint) 신규 추가 — 백엔드+프론트엔드 정적 사이트를 한
  번에 정의. **지금은 Free 플랜으로 작성**해뒀다 — 아직 포트폴리오/데모 단계라 "실사용
  아님"으로 판단, 유료 Starter 플랜(영구 디스크)으로 돈 쓸 단계가 아니라는 사용자 판단에
  따름. Free 플랜은 15분 비활동 후 슬립했다 깨어날 때마다 컨테이너가 새로 생성되며
  `app.db`/`chroma_db`가 초기화된다는 트레이드오프가 있음(회원가입→연동→검색 자체는
  매번 되지만 데모 데이터는 유지 안 됨) — 이 사실을 사용자에게 명확히 설명하고 동의
  받은 뒤 진행.
  나중에 실사용 전환이 필요해질 걸 대비해 `backend/db.py`의 `DB_PATH`와
  `backend/rag_pipeline.py`의 `CHROMA_PERSIST_DIR`을 각각 `DB_PATH`/`CHROMA_PERSIST_DIR`
  환경변수로 덮어쓸 수 있게 미리 수정해둠(안 주면 기존과 동일하게 `backend/` 디렉터리
  안을 그대로 씀 — 로컬 개발은 영향 없음, 디폴트 동작 유지되는 것까지 확인함) — 나중에
  Starter 플랜+디스크로 전환할 때 `render.yaml` 상단 주석의 3단계만 하면 되고 코드 변경은
  필요 없음. **아직 실제 Render 배포는 안 함** — Render 계정 생성·GitHub 저장소 연결·
  Blueprint 적용은 사용자가 직접 해야 하는 부분이라 다음 세션에서 이어서 진행. 서비스
  이름이 이미 쓰이고 있으면 Render가 다른 URL을 배정하므로, 그 경우 `render.yaml`에 미리 적어둔
  `FRONTEND_ORIGINS`/`VITE_API_BASE`/각 `*_OAUTH_REDIRECT_URI`를 실제 배정 URL로
  대시보드에서 다시 맞춰야 한다(README.md "Render로 배포하기" 절에 기록해둠).

---

## 3. 핵심 설계 (코드 읽기 전에)

### 문서 메타데이터 3종
모든 문서(Chroma 메타데이터)에 붙는다. 여러 기능이 여기 의존한다.

- `syncedBy` — 이 문서를 가져온 사용자 id 목록. `",1,3,"` 형태 문자열.
  → 통계 범위 제한, 연동 해제 시 정리의 기준. **같은 문서를 여러 명이 연동할 수 있어 합집합으로 병합한다.**
- `sourceUpdatedAt` — 원본 최종 수정 시각. 커넥터가 "본문을 다시 받을지" 판단하는 기준.
- `contentHash` — `sha256(제목+본문)`. 같으면 재임베딩을 건너뛴다.

### 커넥터 계약
```python
fetch_X_documents_for_user(token, known) -> (documents, seen_ids)
#   known     : {문서id: 지난번 sourceUpdatedAt}
#   documents : 본문을 새로 가져온 것만
#   seen_ids  : 원본에 "현재 존재하는" 전체 id (정리에 필요하므로 항상 전부)
```
목록 조회는 싸니까 매번 전부 하고, **비싼 본문 가져오기만** 변경분에 대해 한다.

⚠️ **정리(pruning) 주의** — `known - seen_ids`를 "삭제된 문서"로 보고 지운다.
그래서 수집이 부분 실패하면 멀쩡한 문서가 지워질 수 있다. 이를 막는 장치가 두 개 있으니
커넥터를 고칠 때 깨뜨리지 말 것:
1. 저장소/채널 단위로 실패하면, 그 범위의 기존 id를 `seen_ids`에 도로 넣는다(= 살아있는 것으로 간주)
2. `seen_ids`가 통째로 비면 그 주기의 정리를 아예 건너뛴다

### 권한 확인 4상태
`main.py`의 `_check_*_access`는 bool이 아니라 넷 중 하나를 돌려준다.
```
allowed / denied / auth_failed(토큰 만료→재연결 안내) / unavailable(일시적)
```
`auth_failed`면 저장된 refresh_token으로 한 번 갱신 후 재시도한다.

### 토큰 저장 방식
| 소스 | 저장 | 비고 |
|---|---|---|
| Google | refresh_token | access token 1시간 만료 → 매번 갱신 |
| GitLab | access + refresh | **2시간 만료** — refresh 없으면 연동이 조용히 죽는다 |
| GitHub | access (+refresh) | OAuth App 토큰은 보통 만료 없음 |
| Slack / Notion | access | 만료 없음 |

---

## 4. 알려진 함정 (겪었던 것들)

1. **`uvicorn --reload`가 가끔 워커를 갱신하지 않는다.** 새 라우트가 404/405로 나오면 리로드를
   믿지 말고 프로세스를 완전히 죽였다 다시 띄운다. 포트 점유 확인: `netstat -ano | findstr :8000`
   **(2026-09-21 진짜 원인 특정함 — "재부팅해야 하는 좀비 포트"의 정체)** Windows에서
   `uvicorn --reload`는 감독 프로세스(reloader) + `multiprocessing.spawn`으로 뜨는 별도 자식
   워커 프로세스로 나뉜다. `netstat -ano`가 보여주는 PID(예: 6860)는 보통 감독 프로세스인데,
   `taskkill /F`로 그것만 죽이면 **실제로 포트를 물고 요청을 처리하던 자식 프로세스는 안 죽고
   계속 산다** — `netstat`은 여전히 죽은 감독 프로세스의 PID를 보여줘서 `Get-Process`/
   `Stop-Process`로는 그 PID를 못 찾으니(이미 죽었으니까) 마치 "귀신 프로세스가 포트를 영원히
   붙잡고 있다"처럼 보이고, 예전엔 이걸 "소프트웨어로는 못 고치고 재부팅해야 한다"고 결론
   냈었다. **진짜 해법**: `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like
   "*multiprocessing-fork*" }`로 `ParentProcessId`가 죽은 감독 PID와 일치하는 자식을 찾아서
   그 자식을 `taskkill /F`하면 재부팅 없이 바로 풀린다. 애초에 이 상황을 안 만들려면
   `--reload` 프로세스를 끌 때 감독만 죽이지 말고, 먼저 `netstat -ano | findstr :8000`으로 PID를
   확인한 뒤 그 PID의 자식까지 같이 확인해서 정리할 것.
2. **Windows Smart App Control이 서명 없는 네이티브 모듈을 차단한다.** 실제로 `tiktoken`이
   막혀 백엔드가 기동조차 못 했다. 그래서 `langchain_openai`를 걷어내고 `openai` SDK를 직접
   호출하도록 바꿨다(`rag_pipeline.OpenAIDirectEmbeddings`). **requirements에 tiktoken/
   langchain-openai를 다시 추가하지 말 것.**
3. **Google Cloud는 클라이언트 시크릿을 한 번만 보여준다.** 잃어버렸으면 클라이언트 상세 화면
   하단 **"+ Add secret"** 으로 새로 발급하면 된다(클라이언트 ID는 그대로).
4. **Google Sheets API는 사용자당 분당 60건 제한.** 시트가 수십 개면 금방 걸린다. 호출 간
   최소 간격 + 백오프가 `gdrive_connector._sheets_api_call`에 들어 있다.
5. **문서 id 형식을 바꾸면 기존 문서가 중복으로 남는다.** 실제로 GitHub id를 바꿨을 때 197개가
   중복됐다. 바꿔야 한다면 옛 id 문서를 지우는 정리를 같이 해야 한다.
   **(2026-09-21 재발 확인·정리)** `ingest_documents()`가 `ids=`를 안 넘기던 시절(업서트 버그
   고치기 전)에 들어간 문서는 Chroma의 실제 pk가 랜덤 UUID라서, 나중에 같은 문서가 올바른
   id로 다시 들어와도 예전 행이 안 지워지고 검색 결과에 같은 문서가 2번 나온다(예:
   `paper_draft`, `YunhuPark/Medical_Insight_Lab#1`). **판별법**: `metadata['id']`와 Chroma
   실제 pk가 다른 행 중, 그 `metadata['id']`가 *다른* 행의 실제 pk로 존재하면 안전하게 지울 수
   있는 예전 행이다(둘 다 실제 pk == metadata.id인 정상 행만 있으면 지울 필요 없음). 이번에
   6건 발견해 정리함. **아직 5건 남아있음** — Notion 문서 몇 개가 여전히 랜덤 UUID pk로만
   존재하고 올바른 id의 짝이 없다(그 페이지가 아직 새 방식으로 재동기화된 적이 없어서) —
   지금은 진짜 유일한 사본이라 그대로 뒀지만, 그 페이지가 나중에 다시 동기화되면 같은 패턴의
   중복이 또 생길 수 있으니 그때 같은 방식으로 정리할 것.
   **위 정리를 할 때 서버를 꼭 내려두고 할 것** — 2026-09-21에 서버를 켠 채로 별도 프로세스에서
   Chroma를 직접 `delete()`했더니, 서버가 메모리에 들고 있던 인덱스와 디스크 상태가 어긋나서
   검색이 500 에러를 내기 시작했다(재시작으로 해결됨, 위 1번 항목의 자식 프로세스 문제와 겹쳐서
   원인 파악이 오래 걸렸다). Chroma persistent client는 여러 프로세스의 동시 쓰기를 안전하게
   지원하지 않는다.
6. **Slack OAuth는 `localhost`를 거부한다** → `127.0.0.1` 사용. postMessage origin도 둘 다
   허용해야 한다(`FRONTEND_ORIGINS`).
7. **관련도 임계값(`MIN_SEARCH_RELEVANCE`)은 고정 숫자로 완벽히 못 가른다.** 실측
   (2026-09-21): 무의미한 검색어의 관련도(0.22~0.37)와 실제 존재하는 주제어의 관련도
   (0.32~0.52) 구간이 겹친다 — 문서 수가 수백 개 수준으로 작아서 벡터 거리만으로는 노이즈와
   진짜 약한 매칭을 완전히 못 가림. 0.3→0.35로 올려 대부분의 무의미한 검색어는 걸러지지만
   `!@#$%^&*` 같은 극단적 예외는 여전히 통과할 수 있다. 더 정밀하게 하려면 고정 임계값이
   아니라 reranker나 후보군 점수 분포 기반 판별이 필요함(이번엔 범위 밖).
8. **GitHub의 "보조 남용 방지(secondary rate limit)"는 `GET /rate_limit`에 안 잡힌다.**
   2026-09-21~22에 GitHub 저장소 전체 파일 색인(FR-6 확장)을 검증하면서 짧은 시간에 API를
   너무 많이 두드렸더니(수동 테스트 + 전체 동기화 여러 번 반복), `/rate_limit`의 core는
   `remaining: 5000`으로 멀쩡한데 실제 요청은 전부 403 `"API rate limit exceeded for user
   ID ..."`로 막히는 상태가 됨 — 시간당 5000회 한도(primary)와 별개의 한도라 이 엔드포인트로는
   미리 확인이 안 된다. 짧은 시간에 반복 테스트할 때는 이 가능성을 염두에 둘 것 — 데이터
   손실은 없다(이미 동기화된 문서는 그대로 있고, 검색 시점 실시간 권한 확인만 막힘), 시간이
   지나면 자연히 풀린다.
9. **git 저장소에 `.gitignore` 없이 venv/node_modules가 통째로 커밋된 경우가 실제로 있다.**
   GitHub 저장소 전체 파일 색인 중 한 저장소(5697개 파일)의 98%(5587개)가 커밋된 Python
   venv(site-packages)였다 — Drive 사고와 같은 패턴. `github_connector._VENDOR_PATH_SEGMENTS`
   (venv/site-packages/node_modules/__pycache__ 등 경로 세그먼트)로 걸러낸다. 비슷한 새 패턴이
   보이면 같은 방식으로 추가할 것.

---

## 5. 빠른 검증 스니펫

```bash
# 서버 상태
curl -s http://localhost:8000/ && curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5173

# 권한 격리: 로그인 없이 통계 → 401 이어야 정상
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/v1/stats

# 로그인 후 내 통계
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"내이메일","password":"내비밀번호"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s http://localhost:8000/api/v1/stats -H "Authorization: Bearer $TOKEN"
```

```python
# 증분 동기화 확인 — 두 번 연속 돌려서 두 번째가 "새 임베딩 0개"면 정상
# backend 디렉터리에서 venv 활성화 후 실행
import db, auth, rag_pipeline
for acc in db.get_all_accounts_with_tokens(['google','github','gitlab','slack','notion']):
    tok = acc['access_token']
    if acc['provider'] == 'google':
        tok = auth.refresh_google_access_token(tok)
    print(acc['provider'], rag_pipeline.sync_documents_for_user(acc['provider'], tok, acc['user_id']))
```

---

## 6. 이어서 작업할 때 참고

- 기능/결정의 배경은 전부 [PRD.md](PRD.md)에 남겨두었다. 특히 **FR-15(계정 연동 시 자동 수집)**,
  **FR-16(실사용 전 전수 감사)** 이 이번 작업의 핵심이다.
- 왜 그렇게 짰는지가 애매한 코드는 대부분 주석에 "예전엔 …였는데 ~ 문제가 있어서" 형태로
  이유를 적어두었다. 고치기 전에 그 주석을 먼저 읽을 것.
- 이 문서와 PRD의 상태 표기가 코드와 어긋나면 **코드가 정답**이다. 발견하면 문서를 고친다.
