#!/bin/bash
# Oracle 서버(항상 켜져 있는 Micro)에서 무료 A1 서버가 잡힐 때까지 생성을 반복 시도한다.
# 인증: 이 서버의 Instance Principal (IAM 동적 그룹+정책 필요, SETUP-A1-RETRY.md 참고). 비밀 키를 서버에 두지 않는다.
set -u
OCI="$HOME/ocienv/bin/oci --auth instance_principal"
META=$(curl -s -H "Authorization: Bearer Oracle" http://169.254.169.254/opc/v2/instance/)
TEN=$(echo "$META" | python3 -c 'import sys,json; print(json.load(sys.stdin)["tenantId"])' 2>/dev/null)
AD=$(echo "$META" | python3 -c 'import sys,json; print(json.load(sys.stdin)["availabilityDomain"])' 2>/dev/null)
PUB="$HOME/.ssh/authorized_keys"
LOG="$HOME/a1-retry.log"
exec >> "$LOG" 2>&1
echo "[$(date '+%F %T')] 시작 tenancy=${TEN:0:30} AD=$AD"
[ -n "$TEN" ] || { echo "메타데이터를 읽지 못했습니다"; exit 1; }

# 이미 A1이 있으면 끝낸다
EXIST=$($OCI compute instance list --compartment-id "$TEN" --display-name topic-thread-a1 --lifecycle-state RUNNING --query 'data[0].id' --raw-output 2>/dev/null)
if [ -n "$EXIST" ] && [ "$EXIST" != "null" ]; then echo "이미 존재: $EXIST"; exit 0; fi

SUB=$($OCI network subnet list --compartment-id "$TEN" --all --query 'data[?contains("display-name",`public`)]|[0].id' --raw-output)
IMG=$($OCI compute image list --compartment-id "$TEN" --operating-system 'Canonical Ubuntu' --operating-system-version '22.04' --shape VM.Standard.A1.Flex --sort-by TIMECREATED --sort-order DESC --query 'data[0].id' --raw-output)
echo "SUB=${SUB:0:40} IMG=${IMG:0:40}"
[ -n "$SUB" ] && [ -n "$IMG" ] || { echo "서브넷/이미지 조회 실패(권한 확인 필요)"; exit 1; }

n=0
while true; do
  OUT=$($OCI compute instance launch --compartment-id "$TEN" --availability-domain "$AD" \
    --shape VM.Standard.A1.Flex --shape-config '{"ocpus":2,"memoryInGBs":12}' \
    --image-id "$IMG" --subnet-id "$SUB" --assign-public-ip true --display-name topic-thread-a1 \
    --ssh-authorized-keys-file "$PUB" --query 'data.id' --raw-output 2>/tmp/a1.err)
  if [ $? -eq 0 ] && [ -n "$OUT" ]; then echo "[$(date '+%F %T')] CREATED: $OUT"; exit 0; fi
  n=$((n+1))
  echo "[$n] $(date +%H:%M:%S) $(grep -o -i -E 'out of host capacity|LimitExceeded|TooManyRequests|NotAuthorized[A-Za-z]*|NotAuthenticated' /tmp/a1.err | head -1)"
  sleep 60
done
