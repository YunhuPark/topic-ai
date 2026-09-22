# 인수인계 — 다른 환경에서 이어서 작업하기

> 이 문서는 "새 노트북에서 이 저장소를 받아 이어서 개발한다"를 위한 것이다.
> 기능 명세는 [PRD.md](PRD.md), 설치·연동 설정은 [README.md](README.md)를 본다.
> 마지막 갱신: 2026-09-21

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
  구성)를 색인한다**(2026-09-22 추가) — 예전엔 표 내용이 통째로 안 읽히고, 데이터베이스
  이름으로 검색해도 안 걸렸다. 이미지 본문(OCR)·임베드/북마크/파일 블록은 여전히 범위 밖.
  이 프로젝트 계정엔 공유된 Notion 데이터베이스가 없어서 표/이미지 변환 로직만 합성
  데이터로 검증했고, 데이터베이스 색인은 아직 실제 데이터로 확인 못함 — 나중에 실제
  데이터베이스를 연동하면 한 번 확인할 것.
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
- 대용량 문서 청킹 (지금은 임베딩 입력을 어림치로 잘라 넣음)
- 배포 구성 (현재 로컬/사내망 전용, CORS·OAuth URI가 localhost 고정)
- 가입 도메인 제한, 비밀번호 재설정(SMTP 필요) — 실사용 논의 중 "나중에"로 보류

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
