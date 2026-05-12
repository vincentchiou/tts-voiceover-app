/* ========================================
   app.js — 文生語音 APP 前端邏輯
   純原生 JS，無框架依賴
   ======================================== */

const API = "http://localhost:8765";

// ── 全域狀態 ──────────────────────────────────────────────
const state = {
  currentStep: 1,
  inputType: "topic",       // topic / pdf / youtube / srt / script
  outputMode: "single",     // single / duo / short_video
  targetMinutes: 5,
  voiceA: "台灣女聲",
  voiceB: "台灣男聲",
  customVoiceA: "",
  customVoiceB: "",
  jobId: null,
  pollTimer: null,
  pdfUploadPath: null,       // 已上傳 PDF 的伺服器路徑
  srtContent: null,          // 已解析的 SRT 文字
  srtSubtype: "srt",        // srt / script
};

// ── 初始化 ─────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", () => {
  initInputTabs();
  initSrtSubtabs();
  initModeCards();
  initDurationSlider();
  initVoiceUploads();
  initButtons();
  initFileDropZone();
  initLlmSettings();
  loadVoices();
  loadSystemInfo();
});

// ── 輸入類型 Tab ──────────────────────────────────────────
function initInputTabs() {
  document.querySelectorAll(".input-tabs .tab-btn[data-type]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.inputType = btn.dataset.type;
      document.querySelectorAll(".input-tabs .tab-btn[data-type]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      // 切換顯示的輸入區塊
      ["inputTopic", "inputPdf", "inputYoutube", "inputSrt"].forEach(id => {
        document.getElementById(id).classList.add("hidden");
      });
      const mapping = { topic: "inputTopic", pdf: "inputPdf", youtube: "inputYoutube", srt: "inputSrt" };
      document.getElementById(mapping[state.inputType])?.classList.remove("hidden");
    });
  });
}

// ── SRT / 腳本 子類型 ──────────────────────────────────────
function initSrtSubtabs() {
  document.querySelectorAll(".tab-btn[data-subtype]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.srtSubtype = btn.dataset.subtype;
      document.querySelectorAll(".tab-btn[data-subtype]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("srtUploadZone").classList.toggle("hidden", state.srtSubtype !== "srt");
      document.getElementById("scriptInputZone").classList.toggle("hidden", state.srtSubtype !== "script");
    });
  });

  // SRT 檔案上傳
  document.getElementById("srtFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const text = await file.text();
    document.getElementById("srtText").value = text;
  });
}

// ── 輸出模式卡片 ──────────────────────────────────────────
function initModeCards() {
  document.querySelectorAll(".mode-card").forEach(card => {
    card.addEventListener("click", () => {
      state.outputMode = card.dataset.mode;
      document.querySelectorAll(".mode-card").forEach(c => c.classList.remove("active"));
      card.classList.add("active");
      // 短影音：隱藏時長選擇
      const isDuo = state.outputMode === "duo";
      const isShort = state.outputMode === "short_video";
      document.getElementById("durationRow").classList.toggle("hidden", isShort);
      document.getElementById("voiceBSlot").classList.toggle("hidden", !isDuo);
      if (isShort) state.targetMinutes = 1.5;
    });
  });
}

// ── 時長滑桿 ─────────────────────────────────────────────
function initDurationSlider() {
  const slider   = document.getElementById("durationSlider");
  const valEl    = document.getElementById("durationVal");
  const approxEl = document.getElementById("durationApprox");

  function setDuration(min) {
    min = Math.max(1, Math.min(30, parseInt(min)));
    state.targetMinutes = min;
    slider.value = min;
    valEl.textContent = min;
    // 口語速度：約 260 字/分鐘
    const chars = min * 260;
    const charsStr = chars >= 1000 ? (chars / 1000).toFixed(1) + "K" : String(chars);
    if (approxEl) approxEl.textContent = `≈ ${charsStr} 字`;
    // 同步快選按鈕 active 狀態
    document.querySelectorAll(".dur-btn").forEach(b => {
      b.classList.toggle("active", parseInt(b.dataset.min) === min);
    });
  }

  slider.addEventListener("input", () => setDuration(slider.value));

  document.querySelectorAll(".dur-btn").forEach(btn => {
    btn.addEventListener("click", () => setDuration(btn.dataset.min));
  });

  setDuration(5);  // 預設 5 分鐘
}

// ── 聲音複製上傳 ──────────────────────────────────────────
function initVoiceUploads() {
  const cloneFile = document.getElementById("voiceCloneFile");
  const cloneForm = document.getElementById("voiceCloneForm");
  const cloneName = document.getElementById("voiceCloneName");

  cloneFile.addEventListener("change", () => {
    if (cloneFile.files[0]) {
      cloneName.textContent = "✓ " + cloneFile.files[0].name;
      cloneForm.classList.remove("hidden");
    }
  });

  document.getElementById("doCloneVoice").addEventListener("click", async () => {
    const file = cloneFile.files[0];
    const label = document.getElementById("voiceCloneLabel").value.trim() || "自訂音色";
    const refText = document.getElementById("voiceCloneRefText").value.trim();
    if (!file) return showToast("請先選擇音檔", "error");

    const btn = document.getElementById("doCloneVoice");
    btn.disabled = true; btn.textContent = "上傳中...";

    const form = new FormData();
    form.append("file", file);
    form.append("voice_name", label);
    form.append("reference_text", refText);

    try {
      const res = await fetch(`${API}/voices/clone`, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "上傳失敗");
      showToast(`✓ 音色「${label}」已建立！`, "success");
      state.customVoiceA = data.voice_id;
      cloneForm.classList.add("hidden");
      loadVoices();
    } catch (e) {
      showToast("音色複製失敗：" + e.message, "error");
    } finally {
      btn.disabled = false; btn.textContent = "上傳並建立音色";
    }
  });
}

// ── PDF 拖放區域 ──────────────────────────────────────────
function initFileDropZone() {
  const zone = document.getElementById("pdfZone");
  const fileInput = document.getElementById("pdfFile");

  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file?.type === "application/pdf") handlePdfUpload(file);
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) handlePdfUpload(fileInput.files[0]);
  });
}

async function handlePdfUpload(file) {
  document.getElementById("pdfFileName").textContent = "上傳中... " + file.name;
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch(`${API}/upload`, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);
    state.pdfUploadPath = data.path;
    document.getElementById("pdfFileName").textContent = "✓ " + file.name;
  } catch (e) {
    document.getElementById("pdfFileName").textContent = "✗ 上傳失敗：" + e.message;
  }
}

// ── 按鈕初始化 ───────────────────────────────────────────
function initButtons() {
  // Step 1 → 2
  document.getElementById("nextToStep2").addEventListener("click", () => {
    if (!validateStep1()) return;
    goToStep(2);
    refreshLlmStatusHint();  // 進入 step2 時更新 LLM 狀態提示
  });

  // Step 2 返回
  document.getElementById("backToStep1").addEventListener("click", () => goToStep(1));

  // 開始生成
  document.getElementById("startGenerate").addEventListener("click", startGenerate);

  // 審閱：重新生成
  document.getElementById("regenScript").addEventListener("click", () => {
    goToStep(1);
    state.jobId = null;
  });

  // 審閱：核准並合成
  document.getElementById("approveScript").addEventListener("click", approveAndSynthesize);

  // 完成：重新開始
  document.getElementById("restartBtn").addEventListener("click", restart);

  // 系統安裝按鈕
  document.getElementById("installBtn").addEventListener("click", startInstall);
  document.getElementById("downloadCosyvoiceBtn").addEventListener("click", () => downloadModel("cosyvoice2-0.5b"));
  document.getElementById("downloadWhisperBtn").addEventListener("click", () => downloadModel("faster-whisper-medium"));
  document.getElementById("repairCosyvoiceBtn").addEventListener("click", repairCosyvoice);
}

// ── 表單驗證 ─────────────────────────────────────────────
function validateStep1() {
  if (state.inputType === "topic") {
    const v = document.getElementById("topicText").value.trim();
    if (!v) return showToast("請輸入教學主題", "error"), false;
  } else if (state.inputType === "pdf") {
    if (!state.pdfUploadPath) return showToast("請先上傳 PDF 檔案", "error"), false;
  } else if (state.inputType === "youtube") {
    const v = document.getElementById("youtubeUrl").value.trim();
    if (!v || !v.startsWith("http")) return showToast("請輸入有效的 YouTube 網址", "error"), false;
  } else if (state.inputType === "srt") {
    const v = state.srtSubtype === "script"
      ? document.getElementById("scriptText").value.trim()
      : document.getElementById("srtText").value.trim();
    if (!v) return showToast("請輸入或上傳文字內容", "error"), false;
  }
  return true;
}

// ── 取得輸入內容 ─────────────────────────────────────────
function getInputContent() {
  switch (state.inputType) {
    case "topic": {
      const topic = document.getElementById("topicText").value.trim();
      const note = document.getElementById("topicNote").value.trim();
      return note ? `${topic}\n\n補充：${note}` : topic;
    }
    case "pdf":
      return state.pdfUploadPath;
    case "youtube":
      return document.getElementById("youtubeUrl").value.trim();
    case "srt":
      return state.srtSubtype === "script"
        ? document.getElementById("scriptText").value.trim()
        : document.getElementById("srtText").value.trim();
  }
}

function getActualInputType() {
  if (state.inputType === "srt") return state.srtSubtype; // "srt" or "script"
  if (state.inputType === "pdf") return "pdf";
  return state.inputType;
}

// ── 開始生成腳本 ─────────────────────────────────────────
async function startGenerate() {
  const content = getInputContent();
  const inputType = getActualInputType();

  const body = {
    input_type: inputType,
    content: content,
    output_mode: state.outputMode,
    target_minutes: state.targetMinutes,
    voice_a: document.getElementById("voiceASelect").value || state.voiceA,
    voice_b: document.getElementById("voiceBSelect").value || state.voiceB,
    custom_voice_a: state.customVoiceA,
    custom_voice_b: state.customVoiceB,
  };

  goToStep(3);
  updateProgress(5, "建立工作...");

  try {
    const res = await fetch(`${API}/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const job = await res.json();
    if (!res.ok) throw new Error(job.detail || "建立工作失敗");
    state.jobId = job.id;
    startPolling();
  } catch (e) {
    showToast("❌ " + e.message, "error");
    goToStep(2);
  }
}

// ── 輪詢工作狀態 ─────────────────────────────────────────
function startPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(pollJob, 1200);
}

async function pollJob() {
  if (!state.jobId) return;
  try {
    const res = await fetch(`${API}/jobs/${state.jobId}`);
    const job = await res.json();
    handleJobUpdate(job);
  } catch (e) {
    // 網路錯誤：繼續輪詢
  }
}

function handleJobUpdate(job) {
  const emojis = { running: "✨", awaiting_review: "📋", synthesizing: "🎙️", complete: "🎉", failed: "😢" };
  const emoji = emojis[job.status] || "⏳";

  if (job.status === "running" || job.status === "queued") {
    document.getElementById("progressEmoji").textContent = emoji;
    updateProgress(job.progress || 5, job.message || "處理中...");
  } else if (job.status === "awaiting_review") {
    clearInterval(state.pollTimer);
    showReviewStep(job);
  } else if (job.status === "synthesizing") {
    updateProgress(job.progress || 72, job.message || "語音合成中...");
    document.getElementById("progressTitle").textContent = "語音合成中";
    document.getElementById("progressEmoji").textContent = "🎙️";
  } else if (job.status === "complete") {
    clearInterval(state.pollTimer);
    showCompleteStep(job);
  } else if (job.status === "failed") {
    clearInterval(state.pollTimer);
    // 顯示完整錯誤（包含 LLM 連線問題的提示）
    const errMsg = job.error || "未知錯誤";
    showErrorPanel(errMsg);
    goToStep(2);
  }
}

// ── 錯誤面板（顯示詳細錯誤）────────────────────────────────
function showErrorPanel(msg) {
  let panel = document.getElementById("errorPanel");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "errorPanel";
    panel.className = "error-panel";
    // 插入 step2 卡片頂部
    const step2 = document.getElementById("step2");
    step2.insertBefore(panel, step2.firstChild);
  }
  panel.innerHTML = `
    <div class="error-panel-title">❌ 發生錯誤</div>
    <div class="error-panel-msg">${esc(msg)}</div>
    <button onclick="document.getElementById('errorPanel').remove()" class="error-panel-close">✕ 關閉</button>
  `;
  panel.classList.remove("hidden");
  // 捲動到頂部
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ── 審閱腳本 ─────────────────────────────────────────────
function showReviewStep(job) {
  const modeLabels = { single: "單人解說", duo: "雙人 Podcast", short_video: "短影音" };
  document.getElementById("estMinutes").textContent = `⏱️ 估算時長：${job.estimated_minutes} 分鐘`;
  document.getElementById("segCount").textContent = `📝 段落數：${job.segments?.length || 0}`;
  document.getElementById("outputModeLabel").textContent = `🎙️ ${modeLabels[job.output_mode] || job.output_mode}`;
  document.getElementById("scriptReview").value = job.script_text || "";
  goToStep(4);
}

// ── 核准並合成 ───────────────────────────────────────────
async function approveAndSynthesize() {
  if (!state.jobId) return;
  const scriptText = document.getElementById("scriptReview").value;

  const btn = document.getElementById("approveScript");
  btn.disabled = true; btn.textContent = "檢查環境...";

  // 先確認語音引擎就緒
  try {
    const sysRes = await fetch(`${API}/system/check`);
    const sysData = await sysRes.json();
    if (!sysData.components.cosyvoice_code) {
      showToast("⚠️ 請先在「系統資訊」安裝語音引擎 CosyVoice2", "error");
      btn.disabled = false; btn.textContent = "✅ 確認，開始合成語音";
      // 自動展開系統資訊區塊提示使用者
      const body = document.getElementById("systemInfoBody");
      if (body.classList.contains("hidden")) toggleSystemInfo();
      return;
    }
    if (!sysData.components.cosyvoice_model) {
      showToast("⚠️ 請先在「系統資訊」下載 CosyVoice2 模型（1.5GB）", "error");
      btn.disabled = false; btn.textContent = "✅ 確認，開始合成語音";
      const body = document.getElementById("systemInfoBody");
      if (body.classList.contains("hidden")) toggleSystemInfo();
      return;
    }
  } catch {
    // 後端無法連線，讓後端自己報錯
  }

  btn.textContent = "處理中...";

  try {
    // 先更新腳本
    await fetch(`${API}/jobs/${state.jobId}/script`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ script_text: scriptText }),
    });
    // 核准
    const res = await fetch(`${API}/jobs/${state.jobId}/approve`, { method: "POST" });
    if (!res.ok) throw new Error("核准失敗");

    goToStep(3);
    document.getElementById("progressTitle").textContent = "語音合成中";
    document.getElementById("progressEmoji").textContent = "🎙️";
    updateProgress(72, "開始語音合成...");
    startPolling();
  } catch (e) {
    showToast("❌ " + e.message, "error");
  } finally {
    btn.disabled = false; btn.textContent = "✅ 確認，開始合成語音";
  }
}

// ── 完成頁面 ─────────────────────────────────────────────
function showCompleteStep(job) {
  const audioUrl = `${API}/jobs/${job.id}/download`;
  document.getElementById("audioPlayer").src = audioUrl;
  const downloadBtn = document.getElementById("downloadBtn");
  downloadBtn.href = audioUrl;
  downloadBtn.download = `語音_${new Date().toLocaleDateString("zh-TW").replace(/\//g,"")}.mp3`;
  goToStep(5);
  launchConfetti();
}

function restart() {
  state.jobId = null;
  state.pdfUploadPath = null;
  state.srtContent = null;
  state.customVoiceA = "";
  // 重置表單
  document.getElementById("topicText").value = "";
  document.getElementById("topicNote").value = "";
  document.getElementById("youtubeUrl").value = "";
  document.getElementById("srtText").value = "";
  document.getElementById("scriptText").value = "";
  document.getElementById("pdfFileName").textContent = "";
  document.getElementById("voiceCloneName").textContent = "";
  document.getElementById("voiceCloneForm").classList.add("hidden");
  goToStep(1);
}

// ── Step 切換 ─────────────────────────────────────────────
function goToStep(n) {
  state.currentStep = n;
  [1,2,3,4,5].forEach(i => {
    document.getElementById(`step${i}`)?.classList.toggle("hidden", i !== n);
    const dot = document.querySelector(`.step-dot[data-step="${i}"]`);
    if (dot) {
      dot.classList.toggle("active", i === n);
      dot.classList.toggle("done", i < n);
    }
  });
}

function updateProgress(pct, msg) {
  document.getElementById("progressBar").style.width = pct + "%";
  document.getElementById("progressPct").textContent = pct + "%";
  document.getElementById("progressMsg").textContent = msg;
}

// ── 音色列表載入 ─────────────────────────────────────────
async function loadVoices() {
  try {
    const res = await fetch(`${API}/voices`);
    const data = await res.json();

    const allVoices = [
      ...data.preset.map(v => ({ value: v.id, label: v.label })),
      ...data.cloned.map(v => ({ value: v.id, label: `🎤 ${v.label}（複製）` })),
    ];

    ["voiceASelect", "voiceBSelect"].forEach((selId, idx) => {
      const sel = document.getElementById(selId);
      sel.innerHTML = allVoices.map(v =>
        `<option value="${esc(v.value)}">${esc(v.label)}</option>`
      ).join("");
      // 預設值：A 選女聲，B 選男聲
      sel.value = idx === 0 ? "台灣女聲" : "台灣男聲";
    });
  } catch {
    // API 未啟動時靜默失敗，等下次再試
    setTimeout(loadVoices, 3000);
  }
}

// ── 系統資訊 ─────────────────────────────────────────────
async function loadSystemInfo() {
  try {
    const res = await fetch(`${API}/system/check`);
    const data = await res.json();

    const grid = document.getElementById("hwGrid");
    grid.innerHTML = `
      <div class="hw-item">
        <span class="hw-label">作業系統</span>
        <span class="hw-value">${esc(data.os)}</span>
      </div>
      <div class="hw-item">
        <span class="hw-label">記憶體</span>
        <span class="hw-value">${data.ram_gb} GB</span>
      </div>
      <div class="hw-item">
        <span class="hw-label">GPU</span>
        <span class="hw-value">${data.gpu ? esc(data.gpu.name) : "無 / CPU 模式"}</span>
      </div>
      <div class="hw-item">
        <span class="hw-label">安裝模式</span>
        <span class="hw-value">${esc(data.install_profile)}</span>
      </div>
      <div class="hw-item">
        <span class="hw-label">Ollama</span>
        <span class="hw-value">
          <span class="status-dot ${data.ollama_available ? "status-ok" : "status-no"}"></span>
          ${data.ollama_available ? "已安裝" : "未偵測"}
        </span>
      </div>
      <div class="hw-item">
        <span class="hw-label">CosyVoice2</span>
        <span class="hw-value">
          <span class="status-dot ${data.components.cosyvoice ? "status-ok" : "status-warn"}"></span>
          ${data.components.cosyvoice ? "已安裝" : "未安裝"}
        </span>
      </div>
      <div class="hw-item">
        <span class="hw-label">FFmpeg</span>
        <span class="hw-value">
          <span class="status-dot ${data.components.ffmpeg ? "status-ok" : "status-warn"}"></span>
          ${data.components.ffmpeg ? "已安裝" : "未安裝"}
        </span>
      </div>
      <div class="hw-item">
        <span class="hw-label">Whisper</span>
        <span class="hw-value">
          <span class="status-dot ${data.components.whisper ? "status-ok" : "status-no"}"></span>
          ${data.components.whisper ? "已安裝" : "未安裝（YouTube 功能需要）"}
        </span>
      </div>
    `;

    // 各區塊獨立判斷（可同時顯示）
    const needRuntimeInstall = !data.components.ffmpeg;
    const needCosyvoice = !data.components.cosyvoice;  // 任何一個環節缺失都算需要
    const needWhisper   = !data.components.whisper;

    // CosyVoice 按鈕文字依狀態調整
    const cvBtn = document.getElementById("downloadCosyvoiceBtn");
    if (!data.components.cosyvoice_code) {
      cvBtn.textContent = "⬇️ 安裝語音引擎 CosyVoice2（程式碼 + 模型，首次約 20 分鐘）";
    } else if (!data.components.cosyvoice_model) {
      cvBtn.textContent = "⬇️ 下載語音模型 CosyVoice2（1.5GB）";
    } else {
      cvBtn.textContent = "⬇️ 重新安裝語音引擎 CosyVoice2";
    }

    // 顯示「補裝套件」區塊：已有 code + model 但 marker 不存在（依賴不完整）
    const needRepair = data.components.cosyvoice_code
                    && data.components.cosyvoice_model
                    && !data.components.cosyvoice;

    document.getElementById("installSection").classList.toggle("hidden", !needRuntimeInstall);
    document.getElementById("downloadModelsSection").classList.toggle("hidden", !needCosyvoice && !needWhisper);
    document.getElementById("downloadCosyvoiceBtn").classList.toggle("hidden", !needCosyvoice);
    document.getElementById("downloadWhisperBtn").classList.toggle("hidden", !needWhisper);
    document.getElementById("repairSection").classList.toggle("hidden", !needRepair);

  } catch {
    // 後端尚未啟動，等待
    setTimeout(loadSystemInfo, 3000);
  }
}

function toggleSystemInfo() {
  const body = document.getElementById("systemInfoBody");
  const arrow = document.getElementById("systemToggleArrow");
  const isHidden = body.classList.toggle("hidden");
  arrow.textContent = isHidden ? "▼" : "▲";
  if (!isHidden) loadSystemInfo();
}

// ── 環境安裝 ─────────────────────────────────────────────
async function startInstall() {
  const btn = document.getElementById("installBtn");
  btn.disabled = true; btn.textContent = "安裝中...";

  document.getElementById("installProgressWrap").classList.remove("hidden");
  document.getElementById("installProgressMsg").classList.remove("hidden");

  try {
    await fetch(`${API}/setup/install`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile: "auto" }),
    });
    pollInstallProgress();
  } catch (e) {
    showToast("安裝失敗：" + e.message, "error");
    btn.disabled = false; btn.textContent = "🛠️ 自動安裝環境";
  }
}

function pollInstallProgress() {
  const timer = setInterval(async () => {
    try {
      const res = await fetch(`${API}/setup/progress/once`);
      const data = await res.json();
      document.getElementById("installProgressBar").style.width = data.percent + "%";
      document.getElementById("installProgressMsg").textContent = data.step;
      if (data.stage === "complete") {
        clearInterval(timer);
        showToast("✓ 環境安裝完成！", "success");
        loadSystemInfo();
      } else if (data.stage === "error") {
        clearInterval(timer);
        showToast("❌ 安裝失敗：" + data.error, "error");
        document.getElementById("installBtn").disabled = false;
        document.getElementById("installBtn").textContent = "🛠️ 重試安裝";
      }
    } catch {}
  }, 1000);
}

async function repairCosyvoice() {
  const btn = document.getElementById("repairCosyvoiceBtn");
  btn.disabled = true; btn.textContent = "補裝中...";

  await fetch(`${API}/setup/repair-cosyvoice`, { method: "POST" });

  const timer = setInterval(async () => {
    try {
      const res = await fetch(`${API}/setup/progress/once`);
      const data = await res.json();
      btn.textContent = `補裝中 ${data.percent}%... ${data.step}`;
      if (data.stage === "complete") {
        clearInterval(timer);
        showToast("✓ 套件補裝完成！請重試語音合成", "success");
        btn.textContent = "✓ 補裝完成";
        loadSystemInfo();
      } else if (data.stage === "error") {
        clearInterval(timer);
        showToast("❌ 補裝失敗：" + data.error, "error");
        btn.disabled = false; btn.textContent = "🔧 補裝 CosyVoice2 缺失套件";
      }
    } catch {}
  }, 1200);
}

async function downloadModel(modelId) {
  const btnId = modelId === "cosyvoice2-0.5b" ? "downloadCosyvoiceBtn" : "downloadWhisperBtn";
  const btn = document.getElementById(btnId);
  btn.disabled = true; btn.textContent = "下載中...";

  await fetch(`${API}/models/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId }),
  });

  const timer = setInterval(async () => {
    try {
      const res = await fetch(`${API}/setup/progress/once`);
      const data = await res.json();
      btn.textContent = `下載中 ${data.percent}%...`;
      if (data.stage === "complete") {
        clearInterval(timer);
        btn.textContent = "✓ 下載完成";
        loadSystemInfo();
      } else if (data.stage === "error") {
        clearInterval(timer);
        showToast("❌ " + data.error, "error");
        btn.disabled = false; btn.textContent = "⬇️ 重試下載";
      }
    } catch {}
  }, 1200);
}

// ── LLM 設定面板 ─────────────────────────────────────────

function toggleLlmSettings() {
  const body  = document.getElementById("llmSettingsBody");
  const arrow = document.getElementById("llmToggleArrow");
  const isHidden = body.classList.toggle("hidden");
  arrow.textContent = isHidden ? "▼" : "▲";
  if (!isHidden) loadLlmSettings();
}

async function initLlmSettings() {
  // Provider 按鈕切換
  document.querySelectorAll(".llm-provider-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".llm-provider-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const p = btn.dataset.provider;
      document.querySelectorAll(".llm-section").forEach(s => s.classList.add("hidden"));
      document.getElementById("llm" + p.charAt(0).toUpperCase() + p.slice(1))?.classList.remove("hidden");
      // 切到 LMStudio 時自動嘗試載入模型清單
      if (p === "lmstudio") loadLmstudioModels();
    });
  });

  // 儲存按鈕
  document.getElementById("saveLlmBtn").addEventListener("click", saveLlmSettings);

  // 測試按鈕
  document.getElementById("testLlmBtn").addEventListener("click", testLlmConnection);

  // LMStudio：重新整理模型清單按鈕
  document.getElementById("refreshLmstudioBtn")?.addEventListener("click", () => loadLmstudioModels(true));

  // LMStudio：位址變更時自動重新載入清單
  document.getElementById("lmstudioBaseUrl")?.addEventListener("change", () => loadLmstudioModels());

  // 載入設定後顯示狀態提示
  await loadLlmSettings();
  await refreshLlmStatusHint();
}

async function refreshLlmStatusHint() {
  const hint = document.getElementById("llmStatusHint");
  if (!hint) return;
  try {
    const res  = await fetch(`${API}/settings/llm`);
    const data = await res.json();
    const p = data.provider || "ollama";

    // 判斷是否有可用設定
    let ready = false;
    if (p === "ollama" || p === "lmstudio") {
      // 本地模型：顯示偵測結果
      const sysRes = await fetch(`${API}/system/check`);
      const sys = await sysRes.json();
      ready = (p === "ollama" && sys.ollama_available)
           || (p === "lmstudio");  // LMStudio 無法自動偵測，假設就緒
    } else if (p === "openai") {
      ready = !!data.openai_api_key;
    } else if (p === "anthropic") {
      ready = !!data.anthropic_api_key;
    }

    const providerLabel = { ollama:"Ollama", lmstudio:"LMStudio", openai:"OpenAI", anthropic:"Anthropic" }[p] || p;
    if (ready) {
      hint.className = "llm-status-hint ok";
      hint.innerHTML = `✅ 腳本生成：使用 <b>${providerLabel}</b>`;
    } else {
      hint.className = "llm-status-hint warn";
      hint.innerHTML = `⚠️ 未設定語言模型，將使用內建模板（內容較簡略）。
        <a href="#llmSettingsCard" onclick="document.getElementById('llmSettingsBody').classList.remove('hidden');document.getElementById('llmToggleArrow').textContent='▲'">
          點此設定 LLM →
        </a>`;
    }
    hint.classList.remove("hidden");
  } catch {
    hint.classList.add("hidden");
  }
}

async function loadLlmSettings() {
  try {
    const res  = await fetch(`${API}/settings/llm`);
    if (!res.ok) return;
    const data = await res.json();

    // 設定 provider 按鈕 active 狀態
    const p = data.provider || "ollama";
    document.querySelectorAll(".llm-provider-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.provider === p);
    });
    // 顯示對應設定區塊
    document.querySelectorAll(".llm-section").forEach(s => s.classList.add("hidden"));
    document.getElementById("llm" + p.charAt(0).toUpperCase() + p.slice(1))?.classList.remove("hidden");

    // 填入欄位值
    _setVal("ollamaBaseUrl",   data.ollama_base_url   || "http://localhost:11434");
    _setVal("ollamaModel",     data.ollama_model      || "qwen3:8b");
    _setVal("lmstudioBaseUrl", data.lmstudio_base_url || "http://localhost:1234");
    // lmstudio 模型保留在 data attribute，待清單載入後再選中
    const lmsSel = document.getElementById("lmstudioModel");
    if (lmsSel) lmsSel.dataset.savedValue = data.lmstudio_model || "";
    // 若目前 provider 是 lmstudio，立即載入清單
    if (p === "lmstudio") loadLmstudioModels();
    _setVal("openaiModel",     data.openai_model      || "gpt-4o-mini");
    _setVal("anthropicModel",  data.anthropic_model   || "claude-haiku-4-5-20251001");
    // API Key 顯示佔位（後端遮蔽實際 key）
    if (data.openai_api_key)    _setVal("openaiApiKey",    "••••••••");
    if (data.anthropic_api_key) _setVal("anthropicApiKey", "••••••••");
  } catch (e) {
    // 後端尚未就緒，靜默忽略
  }
}

async function saveLlmSettings() {
  const btn = document.getElementById("saveLlmBtn");
  btn.disabled = true; btn.textContent = "儲存中...";

  // 取得目前選中的 provider
  const activeBtn = document.querySelector(".llm-provider-btn.active");
  const provider  = activeBtn?.dataset.provider || "ollama";

  const body = {
    provider,
    ollama_base_url:   _getVal("ollamaBaseUrl"),
    ollama_model:      _getVal("ollamaModel"),
    lmstudio_base_url: _getVal("lmstudioBaseUrl"),
    lmstudio_model:    _getVal("lmstudioModel"),
    openai_model:      _getVal("openaiModel"),
    anthropic_model:   _getVal("anthropicModel"),
  };

  // 只在非佔位時才送 key（避免用「••••」覆蓋真實 key）
  const oKey = _getVal("openaiApiKey");
  const aKey = _getVal("anthropicApiKey");
  if (oKey && oKey !== "••••••••") body.openai_api_key    = oKey;
  if (aKey && aKey !== "••••••••") body.anthropic_api_key = aKey;

  try {
    const res = await fetch(`${API}/settings/llm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      showToast("✓ LLM 設定已儲存", "success");
      setLlmResult("✓ 設定已儲存", "ok");
    } else {
      const d = await res.json();
      showToast("❌ 儲存失敗：" + (d.detail || "未知錯誤"), "error");
    }
  } catch (e) {
    showToast("❌ 無法連線後端", "error");
  } finally {
    btn.disabled = false; btn.textContent = "💾 儲存設定";
  }
}

async function testLlmConnection() {
  const btn = document.getElementById("testLlmBtn");
  btn.disabled = true; btn.textContent = "測試中...";
  setLlmResult("連線測試中...", "");

  // 先儲存再測試
  await saveLlmSettings();

  try {
    const res  = await fetch(`${API}/settings/llm/test`, { method: "POST" });
    const data = await res.json();
    if (data.status === "ok") {
      setLlmResult(`✓ 連線成功！模型回應：「${data.response}」`, "ok");
      showToast("✓ LLM 連線正常", "success");
    } else {
      setLlmResult(`✗ 失敗：${data.response}`, "error");
      showToast("❌ LLM 連線失敗", "error");
    }
  } catch (e) {
    setLlmResult("✗ 無法連線後端", "error");
  } finally {
    btn.disabled = false; btn.textContent = "🔌 測試連線";
  }
}

async function loadLmstudioModels(userTriggered = false) {
  const sel  = document.getElementById("lmstudioModel");
  const hint = document.getElementById("lmstudioModelHint");
  const btn  = document.getElementById("refreshLmstudioBtn");
  if (!sel) return;
  const baseUrl = _getVal("lmstudioBaseUrl") || "http://localhost:1234";
  const prevValue = sel.value || sel.dataset.savedValue || "";

  if (btn) btn.disabled = true;
  if (hint) { hint.textContent = "載入模型清單中..."; hint.style.color = "var(--muted)"; }

  try {
    const res = await fetch(`${API}/settings/llm/lmstudio/models?base_url=${encodeURIComponent(baseUrl)}`);
    const data = await res.json();
    if (data.status === "ok" && Array.isArray(data.models) && data.models.length > 0) {
      sel.innerHTML = data.models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join("");
      // 還原舊選擇（若仍存在於清單中）
      if (prevValue && data.models.includes(prevValue)) sel.value = prevValue;
      if (hint) { hint.textContent = `✓ 取得 ${data.models.length} 個模型`; hint.style.color = "#22c55e"; }
    } else {
      sel.innerHTML = `<option value="">（無法取得清單）</option>`;
      const msg = data.message || "請確認 LMStudio 已啟動並已載入至少一個模型";
      if (hint) { hint.textContent = `✗ ${msg}`; hint.style.color = "#ef4444"; }
      if (userTriggered) showToast("❌ LMStudio 無法連線：" + msg, "error");
    }
  } catch (e) {
    sel.innerHTML = `<option value="">（連線錯誤）</option>`;
    if (hint) { hint.textContent = "✗ 無法連線後端"; hint.style.color = "#ef4444"; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

function setLlmResult(msg, type) {
  const el = document.getElementById("llmTestResult");
  if (!el) return;
  el.textContent = msg;
  el.style.color = type === "ok" ? "#22c55e" : type === "error" ? "#ef4444" : "var(--muted)";
}

// 小工具：安全取/設 input 值
function _getVal(id) {
  return document.getElementById(id)?.value?.trim() || "";
}
function _setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

// ── 彩帶特效 ─────────────────────────────────────────────
function launchConfetti() {
  const wrap = document.getElementById("confettiWrap");
  wrap.classList.remove("hidden");
  wrap.innerHTML = "";
  const colors = ["#7c4dff","#f857a6","#ff6b35","#ffd93d","#6bcb77","#4d96ff"];
  for (let i = 0; i < 60; i++) {
    const el = document.createElement("div");
    el.className = "confetti-piece";
    el.style.cssText = `
      left: ${Math.random()*100}%;
      background: ${colors[Math.floor(Math.random()*colors.length)]};
      width: ${6+Math.random()*8}px;
      height: ${6+Math.random()*8}px;
      animation-duration: ${1.5+Math.random()*2}s;
      animation-delay: ${Math.random()*0.8}s;
      border-radius: ${Math.random()>0.5?"50%":"2px"};
    `;
    wrap.appendChild(el);
  }
  setTimeout(() => { wrap.classList.add("hidden"); wrap.innerHTML = ""; }, 4000);
}

// ── 工具函式 ─────────────────────────────────────────────
function esc(str) {
  return String(str ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

let toastTimer = null;
function showToast(msg, type = "") {
  clearTimeout(toastTimer);
  let el = document.getElementById("_toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "_toast";
    document.body.appendChild(el);
  }
  el.className = `toast ${type}`;
  el.textContent = msg;
  el.style.display = "block";
  toastTimer = setTimeout(() => { el.style.display = "none"; }, 3500);
}
