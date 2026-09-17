param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
$runtimePath = Join-Path $projectDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtimePath)) { $runtimePath = Join-Path $projectDirectory '.conda\python.exe' }
if (-not (Test-Path -LiteralPath $runtimePath)) { throw 'README의 Python 환경 설치를 먼저 진행해주세요.' }
if (-not $SkipBuild) {
    Push-Location (Join-Path $projectDirectory 'web')
    try {
        & npm.cmd run build -- --logLevel warn
        if ($LASTEXITCODE -ne 0) { throw '웹 화면 빌드에 실패했습니다.' }
    } finally { Pop-Location }
}
Write-Host 'Code Retro: http://127.0.0.1:8000 (종료: Ctrl+C)'
& $runtimePath -m server.launch
