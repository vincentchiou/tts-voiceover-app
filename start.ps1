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
$ModelsDir  = Join-Path $AppHome "models"
$IndexAppHome = Join-Path $env:LOCALAPPDATA "TTSVoiceoverApp"
$IndexRuntimeDir = Join-Path $IndexAppHome "runtime"
$IndexModelsDir = Join-Path $IndexAppHome "models"
$IndexRepoDir = Join-Path $IndexRuntimeDir "IndexTTS2"
$IndexVenvDir = Join-Path $IndexRuntimeDir "indextts2_venv"
$IndexPython = Join-Path $IndexVenvDir "Scripts\python.exe"
$IndexModelDir = Join-Path $IndexModelsDir "IndexTTS-2"
$IndexMarker = Join-Path $IndexRuntimeDir ".indextts2-installed"
$TtsSettingsFile = Join-Path $AppHome "tts_settings.json"
$GptSetupScript = Join-Path $ScriptDir "setup_gptsovits.ps1"
$GptRepoDir = Join-Path $ScriptDir "GPT-SoVITS"
$GptPretrainedDir = Join-Path $GptRepoDir "GPT_SoVITS\pretrained_models"
$GptMarker = Join-Path $RuntimeDir ".gptsovits-cu128-installed"
$BackendDir = Join-Path $ScriptDir "backend"
$ReqFile    = Join-Path $BackendDir "requirements.txt"
$Port       = 8765

Write-Host ""
Write-Host "  === TTS App ===" -ForegroundColor Cyan
Write-Host "  APP_HOME: $AppHome" -ForegroundColor Gray
Write-Host ""

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null
New-Item -ItemType Directory -Force -Path $IndexRuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $IndexModelsDir | Out-Null
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# Step 1: Download uv
if (-not (Test-Path $UvExe)) {
    Write-Host "  [1/5] Downloading uv..." -ForegroundColor Yellow
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
    Write-Host "  [1/5] uv already installed" -ForegroundColor Gray
}

# Step 2: Install Python 3.10 (uv manages the location)
$UvMarker = Join-Path $RuntimeDir ".uv-installed"
Write-Host "  [2/5] Ensuring Python 3.10 is available..." -ForegroundColor Yellow
& $UvExe python install 3.10
Write-Host "  [OK] Python 3.10 ready" -ForegroundColor Green
if (-not (Test-Path $UvMarker)) { New-Item -ItemType File -Path $UvMarker -Force | Out-Null }
$PyMarker = Join-Path $RuntimeDir ".python-installed"
if (-not (Test-Path $PyMarker)) { New-Item -ItemType File -Path $PyMarker -Force | Out-Null }

# Step 3: Create venv with --no-system-site-packages（完全隔離系統套件）
$VenvCfg = Join-Path $VenvDir "pyvenv.cfg"
if (-not (Test-Path $VenvCfg)) {
    Write-Host "  [3/5] Creating isolated venv..." -ForegroundColor Yellow
    # uv venv 預設就不繼承系統套件，無需額外旗標
    & $UvExe venv $VenvDir --python 3.10
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] venv creation failed" -ForegroundColor Red
        Read-Host "Press Enter to exit"; exit 1
    }
} else {
    Write-Host "  [3/5] venv exists, skipping creation" -ForegroundColor Gray
}

# 每次啟動都同步套件（uv 已安裝的不會重裝，速度很快）
Write-Host "         Syncing packages from requirements.txt..." -ForegroundColor Yellow
& $UvExe pip install --python $VenvPython -r $ReqFile
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] Package install failed" -ForegroundColor Red
    Read-Host "Press Enter to exit"; exit 1
}
Write-Host "  [OK] Packages ready" -ForegroundColor Green


function Ensure-GptSoVITS {
    if ($env:TTS_SKIP_GPTSOVITS_INSTALL -eq "1") {
        Write-Host "         Skipping GPT-SoVITS install (TTS_SKIP_GPTSOVITS_INSTALL=1)" -ForegroundColor Yellow
        return
    }

    if ((Test-Path $GptMarker) -and (Test-Path $GptRepoDir) -and (Test-Path $GptPretrainedDir)) {
        Write-Host "         GPT-SoVITS already installed" -ForegroundColor Gray
        return
    }

    if (-not (Test-Path $GptSetupScript)) {
        throw "找不到 setup_gptsovits.ps1，無法自動安裝 GPT-SoVITS。"
    }

    Write-Host "         Preparing GPT-SoVITS local engine (first run downloads large files)..." -ForegroundColor Yellow
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $GptSetupScript
    if ($LASTEXITCODE -ne 0) { throw "GPT-SoVITS 自動安裝失敗" }
}
function Write-TtsSettingsForIndexTTS2 {
    $settings = @{}
    if (Test-Path $TtsSettingsFile) {
        try {
            $raw = Get-Content -LiteralPath $TtsSettingsFile -Raw -Encoding UTF8
            if ($raw.Trim()) {
                $obj = $raw | ConvertFrom-Json
                foreach ($prop in $obj.PSObject.Properties) { $settings[$prop.Name] = $prop.Value }
            }
        } catch { }
    }
    if (-not $settings.ContainsKey("provider")) { $settings["provider"] = "gptsovits" }
    $settings["indextts2_python"] = $IndexPython
    $settings["indextts2_model_dir"] = $IndexModelDir
    $settings["indextts2_config_path"] = Join-Path $IndexModelDir "config.yaml"
    if (-not $settings.ContainsKey("indextts2_use_fp16")) { $settings["indextts2_use_fp16"] = $true }
    if (-not $settings.ContainsKey("indextts2_emotion")) { $settings["indextts2_emotion"] = "自然、親切、像台灣老師在講課，語氣有溫度但不要誇張。" }
    $jsonObj = [pscustomobject]$settings
    $jsonObj | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $TtsSettingsFile -Encoding UTF8
}

function Ensure-IndexTTS2 {
    if ($env:TTS_SKIP_INDEXTTS2_INSTALL -eq "1") {
        Write-Host "         Skipping IndexTTS2 install (TTS_SKIP_INDEXTTS2_INSTALL=1)" -ForegroundColor Yellow
        return
    }

    $configPath = Join-Path $IndexModelDir "config.yaml"
    if ((Test-Path $IndexMarker) -and (Test-Path $IndexPython) -and (Test-Path $configPath)) {
        Write-Host "         IndexTTS2 already installed" -ForegroundColor Gray
        Write-TtsSettingsForIndexTTS2
        return
    }

    Write-Host "         Preparing IndexTTS2 local engine (first run may take a long time)..." -ForegroundColor Yellow

    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        throw "IndexTTS2 自動安裝需要 Git。請先安裝 Git，或設定 TTS_SKIP_INDEXTTS2_INSTALL=1 暫時略過。"
    }

    if (-not (Test-Path $IndexRepoDir)) {
        Write-Host "         Cloning IndexTTS2 source..." -ForegroundColor Yellow
        git clone https://github.com/index-tts/index-tts.git $IndexRepoDir
        if ($LASTEXITCODE -ne 0) { throw "IndexTTS2 git clone 失敗" }
    } else {
        Write-Host "         Updating IndexTTS2 source..." -ForegroundColor Gray
        git -C $IndexRepoDir pull --ff-only
        if ($LASTEXITCODE -ne 0) { Write-Host "         [WARN] IndexTTS2 source update failed; using existing copy" -ForegroundColor Yellow }
    }

    if (-not (Test-Path (Join-Path $IndexVenvDir "pyvenv.cfg"))) {
        Write-Host "         Creating IndexTTS2 isolated venv..." -ForegroundColor Yellow
        & $UvExe venv $IndexVenvDir --python 3.10
        if ($LASTEXITCODE -ne 0) { throw "IndexTTS2 venv 建立失敗" }
    }

    Write-Host "         Installing IndexTTS2 package..." -ForegroundColor Yellow
    & $UvExe pip install --python $IndexPython -U pip setuptools wheel
    if ($LASTEXITCODE -ne 0) { throw "IndexTTS2 基礎套件安裝失敗" }
    & $UvExe pip install --python $IndexPython -e $IndexRepoDir
    if ($LASTEXITCODE -ne 0) { throw "IndexTTS2 套件安裝失敗" }

    Write-Host "         Installing HuggingFace downloader..." -ForegroundColor Yellow
    & $UvExe pip install --python $IndexPython "huggingface-hub[cli,hf_xet]>=0.23"
    if ($LASTEXITCODE -ne 0) { throw "huggingface_hub 安裝失敗" }

    if (-not (Test-Path $configPath)) {
        Write-Host "         Downloading IndexTTS2 checkpoints to $IndexModelDir ..." -ForegroundColor Yellow
        New-Item -ItemType Directory -Force -Path $IndexModelDir | Out-Null
        $downloadScript = @"
from huggingface_hub import snapshot_download
snapshot_download('IndexTeam/IndexTTS-2', local_dir=r'$IndexModelDir')
print('DONE')
"@
        & $IndexPython -c $downloadScript
        if ($LASTEXITCODE -ne 0) { throw "IndexTTS2 checkpoints 下載失敗" }
    }

    if (-not (Test-Path $configPath)) {
        throw "IndexTTS2 checkpoints 缺少 config.yaml：$configPath"
    }

    Write-TtsSettingsForIndexTTS2
    New-Item -ItemType File -Path $IndexMarker -Force | Out-Null
    Write-Host "         [OK] IndexTTS2 ready" -ForegroundColor Green
}

# Step 4: Start backend
Write-Host "  [4/5] Ensuring optional TTS engines..." -ForegroundColor Yellow
try {
    Ensure-GptSoVITS
    Ensure-IndexTTS2
} catch {
    Write-Host "  [ERROR] Optional TTS engine install failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "          Set TTS_SKIP_GPTSOVITS_INSTALL=1 or TTS_SKIP_INDEXTTS2_INSTALL=1 to skip one engine temporarily." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"; exit 1
}

if ($env:TTS_INSTALL_ONLY -eq "1") {
    Write-Host "  [OK] Install-only check complete." -ForegroundColor Green
    exit 0
}

Write-Host "  [5/5] Starting backend on port $Port..." -ForegroundColor Yellow

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

if ($env:TTS_SMOKE_TEST -eq "1") {
    try { $BackendProc.Kill() } catch { }
    Write-Host "  [OK] Smoke test complete; server stopped." -ForegroundColor Green
    exit 0
}

if ($env:TTS_NO_BROWSER -ne "1") {
    Start-Process $Url
}
Read-Host | Out-Null
try { $BackendProc.Kill() } catch { }
Write-Host "  Server stopped."
