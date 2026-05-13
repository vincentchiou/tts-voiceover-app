#Requires -Version 5.1
<#
.SYNOPSIS
    安裝 GPT-SoVITS v4（程式碼 + 權重 + 獨立 venv）
.DESCRIPTION
    1. 確認 GPT-SoVITS/ 已 clone（若無則 git clone）
    2. 下載 pretrained_models.zip（5.3 GB，含 v4 所需檔案）
    3. 下載 G2PWModel.zip（約 1 GB，中文 G2P）
    4. 解壓至 GPT-SoVITS/GPT_SoVITS/pretrained_models/
    5. 建立獨立 venv（runtime/gptsovits_venv），裝 PyTorch CUDA 12.1 + GPT-SoVITS 依賴
    6. 啟動測試（連通 port 9880）
.NOTES
    可重複執行，已完成的步驟會自動跳過。
#>

# ──────────────────────────────────────────────────────────
# 強制 UTF-8 輸出（Windows PowerShell 5.1 預設 cp950 會吃掉中文）
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"

$REPO_DIR     = Split-Path -Parent $MyInvocation.MyCommand.Path
$APP_HOME     = if ($env:TTS_APP_HOME) { $env:TTS_APP_HOME } else { "$env:LOCALAPPDATA\TTS配音APP" }
$RUNTIME_DIR  = Join-Path $APP_HOME "runtime"
$GPTSOVITS_DIR = Join-Path $REPO_DIR "GPT-SoVITS"
$PRETRAINED   = Join-Path $GPTSOVITS_DIR "GPT_SoVITS\pretrained_models"
$VENV_DIR     = Join-Path $RUNTIME_DIR "gptsovits_venv"
$DOWNLOADS    = Join-Path $APP_HOME "downloads"
$MARKER       = Join-Path $RUNTIME_DIR ".gptsovits-installed"

function Log-Info($msg)    { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Log-Ok($msg)      { Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Log-Warn($msg)    { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Log-Err($msg)     { Write-Host "[ERR ] $msg" -ForegroundColor Red }

New-Item -ItemType Directory -Force -Path $RUNTIME_DIR, $DOWNLOADS | Out-Null

Log-Info "REPO_DIR       = $REPO_DIR"
Log-Info "GPT-SoVITS dir = $GPTSOVITS_DIR"
Log-Info "venv           = $VENV_DIR"

# ──────────────────────────────────────────────────────────
# 步驟 1：clone GPT-SoVITS（若不存在）
if (-not (Test-Path $GPTSOVITS_DIR)) {
    Log-Info "Clone GPT-SoVITS..."
    & git clone --depth=1 https://github.com/RVC-Boss/GPT-SoVITS.git $GPTSOVITS_DIR
    if ($LASTEXITCODE -ne 0) { throw "git clone 失敗" }
    Log-Ok "GPT-SoVITS clone 完成"
} else {
    Log-Ok "GPT-SoVITS 已存在（略過 clone）"
}

# ──────────────────────────────────────────────────────────
# 步驟 2：下載 pretrained_models.zip + G2PWModel.zip
function Download-File($url, $dest, $label) {
    if (Test-Path $dest) {
        Log-Ok "$label 已下載"
        return
    }
    Log-Info "下載 $label ..."
    # 使用 BITS 取得進度回報；BITS 在新版仍可用
    try {
        Start-BitsTransfer -Source $url -Destination $dest -ErrorAction Stop
    } catch {
        Log-Warn "BITS 失敗，改用 Invoke-WebRequest"
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    }
    Log-Ok "$label 下載完成"
}

$PRETRAINED_ZIP = Join-Path $DOWNLOADS "pretrained_models.zip"
$G2PW_ZIP       = Join-Path $DOWNLOADS "G2PWModel.zip"

# v4 需要 vocoder 等檔案，全包在 pretrained_models.zip 內
Download-File `
    "https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/pretrained_models.zip" `
    $PRETRAINED_ZIP "pretrained_models.zip (~5.3GB)"
Download-File `
    "https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/G2PWModel.zip" `
    $G2PW_ZIP "G2PWModel.zip (~1GB)"

# ──────────────────────────────────────────────────────────
# 步驟 3：解壓
function Expand-IfNeeded($zip, $dest, $marker_file) {
    if (Test-Path $marker_file) { Log-Ok "$([System.IO.Path]::GetFileName($zip)) 已解壓"; return }
    Log-Info "解壓 $([System.IO.Path]::GetFileName($zip)) ..."
    Expand-Archive -Path $zip -DestinationPath $dest -Force
    New-Item -ItemType File -Force -Path $marker_file | Out-Null
    Log-Ok "解壓完成 → $dest"
}

Expand-IfNeeded $PRETRAINED_ZIP $PRETRAINED (Join-Path $PRETRAINED ".extracted")
$G2PW_DEST = Join-Path $GPTSOVITS_DIR "GPT_SoVITS\text"
Expand-IfNeeded $G2PW_ZIP $G2PW_DEST (Join-Path $G2PW_DEST ".g2pw_extracted")

# 驗證 v4 關鍵檔案存在
$REQUIRED_FILES = @(
    "$PRETRAINED\s1v3.ckpt",
    "$PRETRAINED\gsv-v4-pretrained\s2Gv4.pth",
    "$PRETRAINED\chinese-roberta-wwm-ext-large",
    "$PRETRAINED\chinese-hubert-base"
)
foreach ($f in $REQUIRED_FILES) {
    if (-not (Test-Path $f)) {
        Log-Err "缺少必要檔案：$f"
        throw "v4 權重檔案不完整，請重新下載"
    }
}
Log-Ok "v4 權重檔案完整"

# ──────────────────────────────────────────────────────────
# 步驟 4：建立獨立 venv（uv 或 python -m venv）
$UV = Join-Path $RUNTIME_DIR "uv\uv.exe"

if (-not (Test-Path "$VENV_DIR\Scripts\python.exe")) {
    Log-Info "建立 GPT-SoVITS 專用 venv..."
    if (Test-Path $UV) {
        & $UV venv --python 3.10 $VENV_DIR
    } else {
        Log-Warn "未找到 uv，改用系統 python -m venv（請確認系統 Python 為 3.10+）"
        & python -m venv $VENV_DIR
    }
    if (-not (Test-Path "$VENV_DIR\Scripts\python.exe")) { throw "venv 建立失敗" }
    Log-Ok "venv 建立完成"
} else {
    Log-Ok "venv 已存在"
}

$VENV_PY = Join-Path $VENV_DIR "Scripts\python.exe"

# ──────────────────────────────────────────────────────────
# 步驟 5：安裝 PyTorch + GPT-SoVITS 依賴
function Pip-Install($pkgs, $extra_args = @()) {
    if (Test-Path $UV) {
        & $UV pip install --python $VENV_PY @pkgs @extra_args
    } else {
        & $VENV_PY -m pip install @pkgs @extra_args
    }
    if ($LASTEXITCODE -ne 0) { throw "pip install 失敗：$pkgs" }
}

# 偵測 NVIDIA GPU；有則裝 cu121，沒有則 cpu wheel
$HAS_NVIDIA = $false
try {
    $nvidia = & nvidia-smi 2>$null
    if ($LASTEXITCODE -eq 0) { $HAS_NVIDIA = $true }
} catch {}

Log-Info "安裝 PyTorch...（NVIDIA detected = $HAS_NVIDIA）"
if ($HAS_NVIDIA) {
    Pip-Install @("torch==2.5.1", "torchaudio==2.5.1") @("--index-url", "https://download.pytorch.org/whl/cu121")
} else {
    Pip-Install @("torch==2.5.1", "torchaudio==2.5.1") @("--index-url", "https://download.pytorch.org/whl/cpu")
}

Log-Info "安裝 GPT-SoVITS 依賴套件..."
$REQ = Join-Path $GPTSOVITS_DIR "requirements.txt"
if (Test-Path $REQ) {
    Pip-Install @("-r", $REQ)
}
$EXTRA_REQ = Join-Path $GPTSOVITS_DIR "extra-req.txt"
if (Test-Path $EXTRA_REQ) {
    try { Pip-Install @("-r", $EXTRA_REQ) } catch { Log-Warn "extra-req 部分套件可選，繼續..." }
}

# httpx 主後端會用，順便確認
Pip-Install @("httpx", "fastapi", "uvicorn[standard]")

Log-Ok "依賴安裝完成"

# ──────────────────────────────────────────────────────────
# 步驟 6：smoke test — 啟動 api_v2.py，確認 9880 可連線
Log-Info "嘗試啟動 GPT-SoVITS api_v2.py（5 秒內看 9880）..."
$proc = Start-Process -FilePath $VENV_PY `
    -ArgumentList "api_v2.py","-a","127.0.0.1","-p","9880","-c","GPT_SoVITS/configs/tts_infer.yaml" `
    -WorkingDirectory $GPTSOVITS_DIR `
    -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $RUNTIME_DIR "gptsovits_smoke.log") `
    -RedirectStandardError  (Join-Path $RUNTIME_DIR "gptsovits_smoke.err.log")

Start-Sleep -Seconds 30
$test = Test-NetConnection -ComputerName 127.0.0.1 -Port 9880 -InformationLevel Quiet
if ($test) {
    Log-Ok "GPT-SoVITS 服務已啟動於 http://127.0.0.1:9880"
} else {
    Log-Warn "30 秒內未偵測到 9880，可能仍在載入模型，請查看 runtime\gptsovits_smoke.log"
}

# 關掉測試行程
try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}

New-Item -ItemType File -Force -Path $MARKER | Out-Null
Log-Ok "安裝完成！主後端啟動時會自動拉起 GPT-SoVITS。"
Log-Info "下一步：執行 start.ps1 啟動主應用。"
