# TTS App Launcher

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($env:TTS_APP_HOME) { $AppHome = $env:TTS_APP_HOME }
else { $AppHome = Join-Path $env:LOCALAPPDATA "TTS配音APP" }

$RuntimeDir = Join-Path $AppHome "runtime"
$UvDir      = Join-Path $RuntimeDir "uv"
$UvExe      = Join-Path $UvDir "uv.exe"
$VenvDir    = Join-Path $RuntimeDir "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$BackendDir = Join-Path $ScriptDir "backend"
$ReqFile    = Join-Path $BackendDir "requirements.txt"
$Port       = 8765

Write-Host ""
Write-Host "  === TTS App ===" -ForegroundColor Cyan
Write-Host "  APP_HOME: $AppHome" -ForegroundColor Gray
Write-Host ""

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

# Step 1: Download uv
if (-not (Test-Path $UvExe)) {
    Write-Host "  [1/4] Downloading uv..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $UvDir | Out-Null
    $ZipPath = Join-Path $UvDir "uv.zip"
    try {
        Invoke-WebRequest `
            -Uri "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" `
            -OutFile $ZipPath -UseBasicParsing
    } catch {
        Write-Host "  [ERROR] Download failed: $($_.Exception.Message)" -ForegroundColor Red
        Read-Host "Press Enter to exit"; exit 1
    }
    Expand-Archive -Path $ZipPath -DestinationPath $UvDir -Force
    Remove-Item $ZipPath -ErrorAction SilentlyContinue
    Write-Host "  [OK] uv installed" -ForegroundColor Green
} else {
    Write-Host "  [1/4] uv already installed" -ForegroundColor Gray
}

# Step 2: Install Python 3.10 (uv manages the location)
$UvMarker = Join-Path $RuntimeDir ".uv-installed"
Write-Host "  [2/4] Ensuring Python 3.10 is available..." -ForegroundColor Yellow
& $UvExe python install 3.10
Write-Host "  [OK] Python 3.10 ready" -ForegroundColor Green
if (-not (Test-Path $UvMarker)) { New-Item -ItemType File -Path $UvMarker -Force | Out-Null }
$PyMarker = Join-Path $RuntimeDir ".python-installed"
if (-not (Test-Path $PyMarker)) { New-Item -ItemType File -Path $PyMarker -Force | Out-Null }

# Step 3: Create venv with --no-system-site-packages（完全隔離系統套件）
$VenvCfg = Join-Path $VenvDir "pyvenv.cfg"
if (-not (Test-Path $VenvCfg)) {
    Write-Host "  [3/4] Creating isolated venv..." -ForegroundColor Yellow
    # uv venv 預設就不繼承系統套件，無需額外旗標
    & $UvExe venv $VenvDir --python 3.10
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] venv creation failed" -ForegroundColor Red
        Read-Host "Press Enter to exit"; exit 1
    }
} else {
    Write-Host "  [3/4] venv exists, skipping creation" -ForegroundColor Gray
}

# 每次啟動都同步套件（uv 已安裝的不會重裝，速度很快）
Write-Host "         Syncing packages from requirements.txt..." -ForegroundColor Yellow
& $UvExe pip install --python $VenvPython -r $ReqFile
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] Package install failed" -ForegroundColor Red
    Read-Host "Press Enter to exit"; exit 1
}
Write-Host "  [OK] Packages ready" -ForegroundColor Green

# Step 4: Start backend
Write-Host "  [4/4] Starting backend on port $Port..." -ForegroundColor Yellow

# 套件隔離：清除可能干擾的環境變數，只設定必要的
$env:TTS_APP_HOME    = $AppHome
$env:TTS_REPO_DIR    = $ScriptDir
$env:PYTHONPATH      = $BackendDir         # 讓 backend/ 下的模組可 import
$env:PYTHONNOUSERSITE = "1"               # 不載入 user site-packages（~/.local/lib）
$env:PYTHONPATH      = $BackendDir        # 再確認一次（覆蓋任何外部設定）

# 用 venv 的 python 直接啟動，不透過系統 python
$BackendProc = Start-Process -FilePath $VenvPython `
    -ArgumentList @(
        "-m", "uvicorn", "app:app",
        "--host", "127.0.0.1",
        "--port", "$Port",
        "--app-dir", $BackendDir,
        "--log-level", "info"       # 顯示 log，方便除錯
    ) `
    -PassThru -WindowStyle Normal

# Wait up to 30s for backend
Write-Host "  Waiting for server..." -ForegroundColor Gray
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2
        $ready = $true; break
    } catch { }
}

$Url = "http://localhost:$Port"
if ($ready) { Write-Host "  [OK] Server ready!" -ForegroundColor Green }
else { Write-Host "  [WARN] Server slow to start, opening browser anyway..." -ForegroundColor Yellow }

Write-Host ""
Write-Host "  URL: $Url" -ForegroundColor Cyan
Write-Host "  Press Enter to stop the server."
Write-Host ""

Start-Process $Url
Read-Host | Out-Null
try { $BackendProc.Kill() } catch { }
Write-Host "  Server stopped."
