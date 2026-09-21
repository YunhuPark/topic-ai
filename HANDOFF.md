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
- 15분 간격 백그라운드 **증분** 재동기화 (바뀐 문서만 다시 임베딩)
- 권한 인지형 검색 — 검색하는 사람 본인 토큰으로 문서마다 실시간 확인(기본 거부)
- GPT-4o 요약 + 의사결정 흐름 + 할 일 리스트(담당자 자동 추론)
- 대시보드 통계는 **본인이 연동한 문서만** 집계
- 연동 해제, 할 일 삭제

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
6. **Slack OAuth는 `localhost`를 거부한다** → `127.0.0.1` 사용. postMessage origin도 둘 다
   허용해야 한다(`FRONTEND_ORIGINS`).

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
