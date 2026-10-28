#!/usr/bin/env bash
# 코드를 새로 받아 반영 (GitHub에 푸시한 뒤 서버에서 실행). 데이터(~/data)는 건드리지 않는다.
set -euo pipefail
APP_DIR="$HOME/topic-ai"
git -C "$APP_DIR" pull
"$APP_DIR/backend/venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"
sudo systemctl restart topic-thread
echo "재시작 완료"
