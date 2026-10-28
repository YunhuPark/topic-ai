# Oracle Cloud 무료 VM에 백엔드 올리기

프런트는 Render 정적 사이트 그대로 두고, **백엔드만** Oracle VM으로 옮긴다.
VM 디스크는 영구라서 `app.db`(계정·연동)와 `chroma_db`(문서)가 재시작·슬립 후에도 남는다.

> 가격·정책·화면 구성은 바뀔 수 있다. 막히면 각 서비스 공식 문서를 우선한다.

## 0. 준비물
- Oracle Cloud 계정 (카드 인증 필요, 무료 범위 안이면 과금 없음)
- 무료 도메인: https://www.duckdns.org (GitHub/Google 로그인) — HTTPS와 OAuth 때문에 도메인이 필요하다
- Render 대시보드, 각 OAuth 콘솔(Google/GitHub/GitLab/Slack/Notion/Kakao) 접근 권한

## 1. VM 만들기 (Oracle 콘솔)
1. Compute → Instances → **Create instance**
2. Image: **Ubuntu 22.04 또는 24.04**
3. Shape: **Ampere A1 (VM.Standard.A1.Flex)** 권장 — 2 OCPU / 12GB 정도면 충분 (Always Free 범위 안).
   "Out of capacity"가 뜨면 시간을 두고 재시도하거나 다른 가용성 도메인을 고른다.
   (대안: AMD `VM.Standard.E2.1.Micro`는 메모리 1GB라 빠듯함)
4. SSH 키: **Generate a key pair** → 개인키(.key)를 안전한 곳에 저장
5. 생성 후 **Public IP**를 적어 둔다
6. 보안 목록 열기: 인스턴스의 서브넷 → Security List → **Ingress Rules 추가**
   - Source `0.0.0.0/0`, TCP, Destination port `80`
   - Source `0.0.0.0/0`, TCP, Destination port `443`

## 2. 도메인 연결 (DuckDNS)
1. duckdns.org에서 서브도메인을 만든다 (예: `mytopic` → `mytopic.duckdns.org`)
2. current ip 칸에 VM의 Public IP를 넣고 update

## 3. 서버 설정
PC 터미널에서 접속:
```bash
ssh -i <개인키 경로> ubuntu@<Public IP>
```
접속한 뒤 (저장소가 private이면 `REPO`에 토큰 포함 주소가 필요):
```bash
curl -O https://raw.githubusercontent.com/YunhuPark/topic-ai/main/deploy/oracle/setup.sh
DOMAIN=mytopic.duckdns.org bash setup.sh
```

## 4. 환경변수 (`~/topic-ai/backend/.env`)
`~/topic-ai/backend/.env.example`을 복사해서 채운다. **비밀 값은 채팅에 붙여넣지 말 것.**
```bash
cp ~/topic-ai/backend/.env.example ~/topic-ai/backend/.env
nano ~/topic-ai/backend/.env
```
꼭 채울 것:
- `JWT_SECRET`, `OPENAI_API_KEY`
- `DB_PATH=/home/ubuntu/data/app.db`, `CHROMA_PERSIST_DIR=/home/ubuntu/data/chroma_db`
- `FRONTEND_ORIGINS=https://topic-thread-frontend.onrender.com`
- 각 OAuth `CLIENT_ID` / `CLIENT_SECRET` (Render에 넣어둔 값과 동일)
- 아래 6개 **리다이렉트 URI는 새 도메인으로** (`mytopic.duckdns.org` 부분을 본인 도메인으로):

| 환경변수 | 값 |
|---|---|
| `GOOGLE_OAUTH_REDIRECT_URI` | `https://mytopic.duckdns.org/api/v1/auth/link/google/callback` |
| `GOOGLE_LOGIN_REDIRECT_URI` | `https://mytopic.duckdns.org/api/v1/auth/google/callback` |
| `GITHUB_OAUTH_REDIRECT_URI` | `https://mytopic.duckdns.org/api/v1/auth/link/github/callback` |
| `GITLAB_OAUTH_REDIRECT_URI` | `https://mytopic.duckdns.org/api/v1/auth/link/gitlab/callback` |
| `SLACK_OAUTH_REDIRECT_URI` | `https://mytopic.duckdns.org/api/v1/auth/link/slack/callback` |
| `NOTION_OAUTH_REDIRECT_URI` | `https://mytopic.duckdns.org/api/v1/auth/link/notion/callback` |
| `KAKAO_LOGIN_REDIRECT_URI` | `https://mytopic.duckdns.org/api/v1/auth/kakao/callback` |

시작:
```bash
sudo systemctl start topic-thread
sudo systemctl status topic-thread
curl https://mytopic.duckdns.org/docs   # HTML이 오면 성공
```
로그 보기: `journalctl -u topic-thread -f`

## 5. OAuth 콘솔에 새 Redirect URL 추가
위 표의 주소를 **각 서비스 앱 설정의 Redirect/Callback URL에 추가**한다(기존 Render 주소는 지우지 말고 둬도 된다).
Google · GitHub · GitLab · Slack · Notion · Kakao 6곳.

## 6. 프런트가 새 백엔드를 보게 하기
Render → `topic-thread-frontend` → Environment → `VITE_API_BASE` 를 `https://mytopic.duckdns.org` 로 변경 → 재배포.

## 7. 확인
- 사이트 접속 → 가입/로그인 → 소스 연결 → F5 / 시간이 지나도 로그인·연동이 유지되는지
- 이전 Render 백엔드는 필요 없으면 일시정지/삭제

## 코드 업데이트 반영
GitHub에 푸시한 뒤 서버에서:
```bash
bash ~/topic-ai/deploy/oracle/update.sh
```

## 문제 해결
- **443 접속 안 됨**: Oracle 보안 목록(1-6)과 서버 안 iptables(setup.sh 2단계) 둘 다 열렸는지 확인
- **인증서 발급 실패**: DuckDNS가 VM IP를 가리키는지, 80포트가 열렸는지 확인 (`sudo journalctl -u caddy`)
- **서버가 죽음/재시작**: `journalctl -u topic-thread`, `free -h`로 메모리 확인
- **백업**: `~/data` 폴더가 전부다. `tar czf backup.tgz ~/data`
