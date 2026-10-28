#!/usr/bin/env bash
# Oracle Cloud Ubuntu VM에서 한 번만 실행하는 초기 설정 스크립트.
# 사용: DOMAIN=내이름.duckdns.org REPO=https://github.com/YunhuPark/topic-ai.git bash setup.sh
set -euo pipefail

: "${DOMAIN:?DOMAIN 환경변수를 지정하세요 (예: myapp.duckdns.org)}"
REPO="${REPO:-https://github.com/YunhuPark/topic-ai.git}"
APP_DIR="$HOME/topic-ai"
DATA_DIR="$HOME/data"

echo "[0/6] 스왑 2GB 설정 (메모리 1GB 서버에서 동기화 중 메모리 부족 방지)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "[1/6] 패키지 설치"
sudo apt-get update -y
sudo apt-get install -y software-properties-common git curl debian-keyring debian-archive-keyring apt-transport-https gpg iptables-persistent
# 이 프로젝트는 파이썬 3.12 기준 (Ubuntu 22.04 기본은 3.10이라 deadsnakes PPA로 설치)
if ! command -v python3.12 >/dev/null; then
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt-get update -y
  sudo apt-get install -y python3.12 python3.12-venv python3.12-dev build-essential
fi
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
  sudo apt-get update -y
  sudo apt-get install -y caddy
fi

echo "[2/6] 서버 안 방화벽에서 80/443 열기 (Oracle 콘솔의 보안 목록과 별개로 필요)"
sudo iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 1 -p tcp --dport 80 -j ACCEPT
sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save

echo "[3/6] 코드 받기"
if [ -d "$APP_DIR/.git" ]; then git -C "$APP_DIR" pull; else git clone "$REPO" "$APP_DIR"; fi
mkdir -p "$DATA_DIR"

echo "[4/6] 파이썬 환경 + 의존성 (몇 분 걸림)"
rm -rf "$APP_DIR/backend/venv"
python3.12 -m venv "$APP_DIR/backend/venv"
"$APP_DIR/backend/venv/bin/pip" install --upgrade pip
"$APP_DIR/backend/venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"

echo "[5/6] systemd 서비스 등록"
sed -e "s#__USER__#$USER#g" -e "s#__APP_DIR__#$APP_DIR#g" "$APP_DIR/deploy/oracle/topic-thread.service" | sudo tee /etc/systemd/system/topic-thread.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable topic-thread

echo "[6/6] Caddy(HTTPS 프록시) 설정"
sed -e "s#__DOMAIN__#$DOMAIN#g" "$APP_DIR/deploy/oracle/Caddyfile.template" | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo systemctl reload caddy || sudo systemctl restart caddy

cat <<MSG

설정 완료. 이제 아래를 하세요:
  1) $APP_DIR/backend/.env 를 만들고 값을 채우기 (SETUP.md의 '환경변수' 참고)
       DB_PATH=$DATA_DIR/app.db
       CHROMA_PERSIST_DIR=$DATA_DIR/chroma_db
  2) sudo systemctl start topic-thread
  3) 확인: curl https://$DOMAIN/docs
MSG
