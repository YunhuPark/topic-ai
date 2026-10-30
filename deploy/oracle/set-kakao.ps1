# 내 PC에서 실행(PowerShell): 카카오 REST API 키와 Client Secret 을 서버 .env 에 넣고 앱을 재시작한다.
# 값은 실행할 때 직접 입력한다(화면에 보이지 않게 입력받고, 명령줄 인자나 로그에 남기지 않는다).
#
# 사용:  powershell -ExecutionPolicy Bypass -File .\set-kakao.ps1
param(
    [string]$Server = "ubuntu@168.138.38.15",
    [string]$Key = "$env:USERPROFILE\Downloads\ssh-key-2026-10-27.key"
)

$ErrorActionPreference = "Stop"

function Read-Secret([string]$prompt) {
    $s = Read-Host -Prompt $prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

Write-Host "카카오 개발자 콘솔 > 앱 > 플랫폼 키 > REST API 키 값을 입력하세요."
$clientId = (Read-Secret "KAKAO_CLIENT_ID (REST API 키)").Trim()
Write-Host "카카오 로그인 > 보안 > Client Secret 값을 입력하세요 (사용하지 않으면 그냥 Enter)."
$clientSecret = (Read-Secret "KAKAO_CLIENT_SECRET").Trim()

if (-not $clientId) { throw "REST API 키가 비어 있습니다." }

$payload = "KAKAO_CLIENT_ID=$clientId`n"
if ($clientSecret) { $payload += "KAKAO_CLIENT_SECRET=$clientSecret`n" }

# 값은 SSH 표준입력으로만 보낸다(프로세스 목록에 노출되지 않음). Windows 줄바꿈(CR)은 서버에서 제거.
$remote = @'
set -e
umask 077
tr -d '\r' > ~/kakao.env.tmp
cd ~/topic-ai/backend
sed -i '/^KAKAO_CLIENT_ID=/d;/^KAKAO_CLIENT_SECRET=/d' .env
cat ~/kakao.env.tmp >> .env
rm -f ~/kakao.env.tmp
chmod 600 .env
sudo systemctl restart topic-thread
sleep 20
echo "service: $(systemctl is-active topic-thread)"
echo "kakao keys in .env: $(grep -c '^KAKAO_' .env)"
'@

$payload | ssh -i $Key $Server $remote
$payload = $null; $clientId = $null; $clientSecret = $null
Write-Host "완료. 사이트에서 '카카오로 계속하기'를 눌러 확인하세요."
