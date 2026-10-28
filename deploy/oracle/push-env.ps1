# 내 PC에서 실행(PowerShell): 로컬 backend/.env 의 비밀 값 + 운영용 값으로 서버의 .env 를 만들어 올린다.
# 비밀 값은 화면에 출력하지 않는다. JWT_SECRET 은 서버용으로 새로 만든다(로컬 것을 재사용하지 않음).
#
# 사용:  powershell -ExecutionPolicy Bypass -File .\push-env.ps1
param(
    [string]$Domain = "topic-thread-ai.duckdns.org",
    [string]$Server = "ubuntu@168.138.38.15",
    [string]$Key = "$env:USERPROFILE\Downloads\ssh-key-2026-10-27.key",
    [string]$LocalEnv = (Join-Path $PSScriptRoot "..\..\backend\.env")
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $LocalEnv)) { throw "로컬 .env 를 찾을 수 없습니다: $LocalEnv" }

# 로컬 .env 파싱 (KEY=VALUE, 주석/빈 줄 제외)
$local = @{}
foreach ($line in Get-Content $LocalEnv -Encoding UTF8) {
    if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') { $local[$Matches[1]] = $Matches[2].Trim() }
}

# 서버로 복사할 비밀/ID 항목 (로컬 값 그대로)
$copyKeys = @(
    "OPENAI_API_KEY",
    "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET",
    "GITHUB_OAUTH_CLIENT_ID", "GITHUB_OAUTH_CLIENT_SECRET",
    "GITLAB_OAUTH_CLIENT_ID", "GITLAB_OAUTH_CLIENT_SECRET",
    "SLACK_OAUTH_CLIENT_ID", "SLACK_OAUTH_CLIENT_SECRET",
    "NOTION_OAUTH_CLIENT_ID", "NOTION_OAUTH_CLIENT_SECRET",
    "KAKAO_CLIENT_ID", "KAKAO_CLIENT_SECRET"
)

# 서버용 새 JWT 비밀
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$jwt = -join ($bytes | ForEach-Object { $_.ToString("x2") })

$base = "https://$Domain/api/v1/auth"
$out = New-Object System.Collections.Generic.List[string]
$out.Add("# 서버용 .env — push-env.ps1 로 생성")
$out.Add("LLM_BACKEND=openai")
$out.Add("JWT_SECRET=$jwt")
$out.Add("DB_PATH=/home/ubuntu/data/app.db")
$out.Add("CHROMA_PERSIST_DIR=/home/ubuntu/data/chroma_db")
$out.Add("FRONTEND_ORIGINS=https://topic-thread-frontend.onrender.com")
$out.Add("MAX_CONCURRENT_SYNCS=1")
$out.Add("GOOGLE_OAUTH_REDIRECT_URI=$base/link/google/callback")
$out.Add("GOOGLE_LOGIN_REDIRECT_URI=$base/google/callback")
$out.Add("GITHUB_OAUTH_REDIRECT_URI=$base/link/github/callback")
$out.Add("GITLAB_OAUTH_REDIRECT_URI=$base/link/gitlab/callback")
$out.Add("SLACK_OAUTH_REDIRECT_URI=$base/link/slack/callback")
$out.Add("NOTION_OAUTH_REDIRECT_URI=$base/link/notion/callback")
$out.Add("KAKAO_LOGIN_REDIRECT_URI=$base/kakao/callback")

$missing = @()
foreach ($k in $copyKeys) {
    if ($local.ContainsKey($k) -and $local[$k] -ne "") { $out.Add("$k=$($local[$k])") } else { $missing += $k }
}

# 임시 파일(UTF-8, BOM 없음, LF) → scp → 권한 600 → 임시 파일 삭제
$tmp = Join-Path $env:TEMP ("env-" + [guid]::NewGuid().ToString("N") + ".tmp")
try {
    [IO.File]::WriteAllText($tmp, (($out -join "`n") + "`n"), (New-Object Text.UTF8Encoding $false))
    scp -i $Key -o ConnectTimeout=20 $tmp "${Server}:/home/ubuntu/topic-ai/backend/.env"
    if ($LASTEXITCODE -ne 0) { throw "scp 실패" }
    ssh -i $Key $Server "chmod 600 /home/ubuntu/topic-ai/backend/.env; mkdir -p /home/ubuntu/data"
} finally {
    if (Test-Path $tmp) { Remove-Item $tmp -Force }
}

Write-Host "서버 .env 생성 완료 (값은 출력하지 않음)."
Write-Host ("복사한 항목 수: {0}" -f ($copyKeys.Count - $missing.Count))
if ($missing.Count -gt 0) {
    Write-Host "로컬 .env 에 없어서 비어 있는 항목(서버에서 직접 추가 필요):"
    $missing | ForEach-Object { Write-Host "  - $_" }
}
