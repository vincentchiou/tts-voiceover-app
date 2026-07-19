/* ========================================
   app.js — 文生語音 APP 前端邏輯
   純原生 JS，無框架依賴
   ======================================== */

const API = "";
const MAX_TEXT_UPLOAD_BYTES = 5 * 1024 * 1024;
const MAX_PDF_UPLOAD_BYTES = 20 * 1024 * 1024;
const MAX_AUDIO_UPLOAD_BYTES = 50 * 1024 * 1024;

function logClientEvent(event, message = "", detail = {}) {
  const payload = JSON.stringify({
    event,
    message,
    detail: {
      ...detail,
      href: window.location.href,
      origin: window.location.origin,
      userAgent: navigator.userAgent,
      ts: new Date().toISOString(),
    },
  });
  try {
    if (navigator.sendBeacon) {
      const blob = new Blob([payload], { type: "application/json" });
      if (navigator.sendBeacon("/client-log", blob)) return;
    }
  } catch (_) {}
  fetch("/client-log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: payload,
    keepalive: true,
  }).catch(() => {});
}

window.addEventListener("error", (event) => {
  logClientEvent("window_error", event.message || "", {
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno,
  });
});

window.addEventListener("unhandledrejection", (event) => {
  logClientEvent("unhandled_rejection", String(event.reason || ""));
});

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
  ttsProvider: "gptsovits",
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
  initPdfModeToggle();
  initLlmSettings();
  initTtsSettings();
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
    if (file.size > MAX_TEXT_UPLOAD_BYTES) {
      showToast("字幕/文字檔需小於 5MB", "error");
      e.target.value = "";
      return;
    }
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

  document.getElementById("doCloneVoice").addEventListener("click", async (event) => {
    event.preventDefault();
    const file = cloneFile.files[0];
    const label = document.getElementById("voiceCloneLabel").value.trim() || "自訂音色";
    const refText = document.getElementById("voiceCloneRefText").value.trim();
    if (!file) return showToast("請先選擇音檔", "error");
    logClientEvent("clone_click", "voice clone button clicked", {
      fileName: file.name,
      fileSize: file.size,
      fileType: file.type,
      label,
      hasReferenceText: Boolean(refText),
    });
    if (file.size > MAX_AUDIO_UPLOAD_BYTES) return showToast("參考音檔需小於 50MB", "error");

    const btn = document.getElementById("doCloneVoice");
    btn.disabled = true; btn.textContent = "上傳中...";

    const form = new FormData();
    form.append("file", file);
    form.append("voice_name", label);
    form.append("reference_text", refText);

    try {
      const uploadUrl = `${API}/voices/clone`;
      logClientEvent("clone_fetch_start", "starting voice clone fetch", { uploadUrl });
      const res = await fetch(uploadUrl, { method: "POST", body: form });
      const raw = await res.text();
      let data = {};
      try { data = raw ? JSON.parse(raw) : {}; } catch { data = { detail: raw }; }
      if (!res.ok) {
        logClientEvent("clone_http_error", "voice clone HTTP error", { status: res.status, body: raw });
        throw new Error(data.detail || `上傳失敗（HTTP ${res.status}）`);
      }
      logClientEvent("clone_success", "voice clone succeeded", { voiceId: data.voice_id, label });
      showToast(`✓ 音色「${label}」已建立！`, "success");
      state.customVoiceA = data.voice_id;
      cloneForm.classList.add("hidden");
      loadVoices();
    } catch (e) {
      logClientEvent("clone_fetch_error", e.message || String(e), {
        name: e.name,
        stack: e.stack,
        api: API,
      });
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
  if (file.size > MAX_PDF_UPLOAD_BYTES) {
    document.getElementById("pdfFileName").textContent = "";
    showToast("PDF 需小於 20MB，請壓縮或分割後再上傳", "error");
    return;
  }
  document.getElementById("pdfFileName").textContent = "上傳中... " + file.name;
  // 重置狀態
  state.pdfExtractedText = "";
  document.getElementById("pdfPreviewSection").classList.add("hidden");
  document.getElementById("pdfModeSection").classList.add("hidden");

  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch(`${API}/upload`, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);
    state.pdfUploadPath = data.path;
    document.getElementById("pdfFileName").textContent = "✓ " + file.name;
    document.getElementById("pdfModeSection").classList.remove("hidden");

    // 預設「抽取文字」模式：自動執行一次抽取並顯示預覽
    await extractAndPreviewPdf();
  } catch (e) {
    document.getElementById("pdfFileName").textContent = "✗ 上傳失敗：" + e.message;
  }
}

async function extractAndPreviewPdf() {
  if (!state.pdfUploadPath) return;
  const previewSection = document.getElementById("pdfPreviewSection");
  const textArea = document.getElementById("pdfPreviewText");
  const stats = document.getElementById("pdfPreviewStats");
  const warnings = document.getElementById("pdfPreviewWarnings");

  previewSection.classList.remove("hidden");
  textArea.value = "";
  textArea.placeholder = "抽取中，請稍候...";
  stats.textContent = "";
  warnings.classList.add("hidden");

  try {
    const res = await fetch(`${API}/extract-pdf`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.pdfUploadPath, enable_ocr: true }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "抽取失敗");

    textArea.value = data.text || "";
    textArea.placeholder = "";
    const charCount = (data.text || "").length;
    stats.textContent = `${data.pages} 頁，${charCount} 字${data.ocr_pages ? `，含 ${data.ocr_pages} 頁 OCR` : ""}`;

    if (data.warnings && data.warnings.length) {
      warnings.innerHTML = "⚠️ " + data.warnings.map(w => escapeHtml(w)).join("<br>⚠️ ");
      warnings.classList.remove("hidden");
    }
  } catch (e) {
    textArea.placeholder = "✗ 抽取失敗：" + e.message;
    showToast("PDF 抽取失敗：" + e.message, "error");
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

// 監聽 PDF 模式切換
function initPdfModeToggle() {
  document.addEventListener("change", (e) => {
    if (e.target.name !== "pdfMode") return;
    const mode = e.target.value;
    const previewSection = document.getElementById("pdfPreviewSection");
    if (mode === "gemini") {
      previewSection.classList.add("hidden");
    } else {
      // 回到抽取模式：若還沒抽取就現在抽
      if (state.pdfUploadPath && !document.getElementById("pdfPreviewText").value) {
        extractAndPreviewPdf();
      } else {
        previewSection.classList.remove("hidden");
      }
    }
  });
}

// ── 按鈕初始化 ───────────────────────────────────────────
function initButtons() {
  // Step 1 → 2
  document.getElementById("nextToStep2").addEventListener("click", () => {
    if (!validateStep1()) return;
    goToStep(2);
    refreshLlmStatusHint();  // 進入 step2 時更新 LLM 狀態提示
    refreshTtsStatusHint();
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
  document.getElementById("downloadWhisperBtn").addEventListener("click", () => downloadModel("faster-whisper-medium"));
  document.getElementById("saveTtsBtn")?.addEventListener("click", saveTtsSettings);
  document.getElementById("testTtsBtn")?.addEventListener("click", testTtsSettings);
}

// ── 表單驗證 ─────────────────────────────────────────────
function validateStep1() {
  if (state.inputType === "topic") {
    const v = document.getElementById("topicText").value.trim();
    if (!v) return showToast("請輸入教學主題", "error"), false;
  } else if (state.inputType === "pdf") {
    if (!state.pdfUploadPath) return showToast("請先上傳 PDF 檔案", "error"), false;
    const mode = (document.querySelector('input[name="pdfMode"]:checked') || {}).value || "extract";
    if (mode === "extract") {
      const text = document.getElementById("pdfPreviewText").value.trim();
      if (!text) return showToast("PDF 抽取結果為空，請改用「Gemini 直讀」模式或檢查檔案", "error"), false;
    }
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
    case "pdf": {
      // 「抽取模式」送已預覽/編輯的文字；「Gemini 直讀」送 PDF 路徑
      const mode = (document.querySelector('input[name="pdfMode"]:checked') || {}).value || "extract";
      if (mode === "extract") {
        return document.getElementById("pdfPreviewText").value.trim();
      }
      return state.pdfUploadPath;
    }
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
  if (state.inputType === "pdf") {
    const mode = (document.querySelector('input[name="pdfMode"]:checked') || {}).value || "extract";
    return mode === "gemini" ? "pdf_gemini" : "text";  // text = 已抽取文字走嚴格 LLM 改寫
  }
  return state.inputType;
}

// ── 開始生成腳本 ─────────────────────────────────────────
async function startGenerate() {
  const content = getInputContent();
  const inputType = getActualInputType();

  await saveTtsSettings({ silent: true });

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
    if (!sysData.components.gptsovits_code || !sysData.components.gptsovits_model) {
      showToast("⚠️ 尚未安裝 GPT-SoVITS，請先執行 setup_gptsovits.ps1", "error");
      btn.disabled = false; btn.textContent = "✅ 確認，開始合成語音";
      // 自動展開系統資訊區塊提示使用者
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
  document.getElementById("pdfPreviewText").value = "";
  document.getElementById("pdfPreviewSection").classList.add("hidden");
  document.getElementById("pdfModeSection").classList.add("hidden");
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
        <span class="hw-label">GPT-SoVITS v4</span>
        <span class="hw-value">
          <span class="status-dot ${data.components.gptsovits ? "status-ok" : "status-warn"}"></span>
          ${data.components.gptsovits ? "已安裝" : "未安裝"}
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
    const needGptsovits = !data.components.gptsovits;  // 程式碼或模型或 marker 任一缺失
    const needWhisper   = !data.components.whisper;

    document.getElementById("installSection").classList.toggle("hidden", !needRuntimeInstall);
    document.getElementById("gptsovitsHintSection").classList.toggle("hidden", !needGptsovits);
    document.getElementById("downloadModelsSection").classList.toggle("hidden", !needWhisper);
    document.getElementById("downloadWhisperBtn").classList.toggle("hidden", !needWhisper);

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

async function downloadModel(modelId) {
  const btn = document.getElementById("downloadWhisperBtn");
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


// ── TTS 設定面板 ─────────────────────────────────────────

function initTtsSettings() {
  document.querySelectorAll(".tts-provider-card").forEach(btn => {
    btn.addEventListener("click", async () => {
      state.ttsProvider = btn.dataset.ttsProvider;
      syncTtsProviderUi(state.ttsProvider);
      await saveTtsSettings({ silent: true });
      refreshTtsStatusHint();
    });
  });
  document.getElementById("ttsProviderSelect")?.addEventListener("change", (e) => {
    state.ttsProvider = e.target.value;
    syncTtsProviderUi(state.ttsProvider);
  });
  loadTtsSettings();
}

function toggleTtsSettings() {
  const body = document.getElementById("ttsSettingsBody");
  const arrow = document.getElementById("ttsToggleArrow");
  const isHidden = body.classList.toggle("hidden");
  arrow.textContent = isHidden ? "▼" : "▲";
  if (!isHidden) loadTtsSettings();
}

function syncTtsProviderUi(provider) {
  state.ttsProvider = provider || "gptsovits";
  document.querySelectorAll(".tts-provider-card").forEach(b => {
    b.classList.toggle("active", b.dataset.ttsProvider === state.ttsProvider);
  });
  _setVal("ttsProviderSelect", state.ttsProvider);
  document.querySelectorAll(".tts-section").forEach(s => s.classList.add("hidden"));
  document.getElementById("ttsIndextts2")?.classList.toggle("hidden", state.ttsProvider !== "indextts2");
  document.getElementById("ttsQwen")?.classList.toggle("hidden", state.ttsProvider !== "qwen");
}

async function loadTtsSettings() {
  try {
    const res = await fetch(`${API}/settings/tts`);
    if (!res.ok) return;
    const data = await res.json();
    syncTtsProviderUi(data.provider || "gptsovits");
    _setVal("indextts2Python", data.indextts2_python || "");
    _setVal("indextts2ModelDir", data.indextts2_model_dir || "");
    _setVal("indextts2ConfigPath", data.indextts2_config_path || "");
    _setVal("indextts2Emotion", data.indextts2_emotion || "");
    const fp16 = document.getElementById("indextts2UseFp16");
    if (fp16) fp16.checked = data.indextts2_use_fp16 !== false;
    if (data.qwen_api_key) _setVal("qwenApiKey", "••••••••");
    _setVal("qwenBaseHttpUrl", data.qwen_base_http_url || "https://dashscope-intl.aliyuncs.com/api/v1");
    _setVal("qwenModel", data.qwen_model || "qwen3-tts-instruct-flash");
    _setVal("qwenVoiceA", data.qwen_voice_a || "Cherry");
    _setVal("qwenVoiceB", data.qwen_voice_b || "Ethan");
    _setVal("qwenInstructions", data.qwen_instructions || "");
    const opt = document.getElementById("qwenOptimizeInstructions");
    if (opt) opt.checked = data.qwen_optimize_instructions !== false;
    refreshTtsStatusHint();
  } catch {}
}

async function saveTtsSettings(options = {}) {
  const body = {
    provider: state.ttsProvider || _getVal("ttsProviderSelect") || "gptsovits",
    indextts2_python: _getVal("indextts2Python"),
    indextts2_model_dir: _getVal("indextts2ModelDir"),
    indextts2_config_path: _getVal("indextts2ConfigPath"),
    indextts2_use_fp16: !!document.getElementById("indextts2UseFp16")?.checked,
    indextts2_emotion: _getVal("indextts2Emotion"),
    qwen_base_http_url: _getVal("qwenBaseHttpUrl") || "https://dashscope-intl.aliyuncs.com/api/v1",
    qwen_model: _getVal("qwenModel") || "qwen3-tts-instruct-flash",
    qwen_voice_a: _getVal("qwenVoiceA") || "Cherry",
    qwen_voice_b: _getVal("qwenVoiceB") || "Ethan",
    qwen_instructions: _getVal("qwenInstructions"),
    qwen_optimize_instructions: !!document.getElementById("qwenOptimizeInstructions")?.checked,
  };
  const qKey = _getVal("qwenApiKey");
  if (qKey && qKey !== "••••••••") body.qwen_api_key = qKey;
  try {
    const res = await fetch(`${API}/settings/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).detail || "儲存失敗");
    if (!options.silent) {
      showToast("✓ TTS 設定已儲存", "success");
      setTtsResult("✓ 設定已儲存", "ok");
    }
  } catch (e) {
    if (!options.silent) showToast("❌ TTS 設定儲存失敗：" + e.message, "error");
  }
}

async function testTtsSettings() {
  const btn = document.getElementById("testTtsBtn");
  if (btn) { btn.disabled = true; btn.textContent = "測試中..."; }
  await saveTtsSettings({ silent: true });
  try {
    const res = await fetch(`${API}/settings/tts/test`, { method: "POST" });
    const data = await res.json();
    const ok = data.status === "ok";
    setTtsResult((ok ? "✓ " : "✗ ") + (data.message || ""), ok ? "ok" : "error");
    showToast((ok ? "✓ " : "❌ ") + (data.message || "TTS 測試完成"), ok ? "success" : "error");
    refreshTtsStatusHint();
  } catch (e) {
    setTtsResult("✗ 無法連線後端", "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "🔌 測試引擎"; }
  }
}

async function refreshTtsStatusHint() {
  const hint = document.getElementById("ttsStatusHint");
  if (!hint) return;
  try {
    const res = await fetch(`${API}/settings/tts/status`);
    const data = await res.json();
    const p = data.provider || state.ttsProvider || "gptsovits";
    const labels = { gptsovits: "GPT-SoVITS v4", indextts2: "IndexTTS2", qwen: "Qwen / CosyVoice" };
    let ok = false;
    if (p === "gptsovits") ok = !!data.gptsovits?.ready;
    if (p === "indextts2") ok = !!(data.indextts2?.python_ready && data.indextts2?.package_ready && data.indextts2?.model_dir_ready && data.indextts2?.config_ready);
    if (p === "qwen") ok = !!(data.qwen?.package_ready && data.qwen?.api_key_ready);
    hint.className = ok ? "llm-status-hint ok" : "llm-status-hint warn";
    hint.textContent = ok ? `✅ TTS：使用 ${labels[p]}` : `⚠️ TTS：${labels[p]} 尚未完成設定，合成時會顯示修復提示`;
    hint.classList.remove("hidden");
  } catch {
    hint.classList.add("hidden");
  }
}

function setTtsResult(msg, type) {
  const el = document.getElementById("ttsTestResult");
  if (!el) return;
  el.textContent = msg;
  el.style.color = type === "ok" ? "#22c55e" : type === "error" ? "#ef4444" : "var(--muted)";
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
    } else if (p === "google") {
      ready = !!data.google_api_key;
    }

    const providerLabel = { ollama:"Ollama", lmstudio:"LMStudio", openai:"OpenAI", anthropic:"Anthropic", google:"Google AI" }[p] || p;
    if (ready) {
      hint.className = "llm-status-hint ok";
      hint.innerHTML = `✅ 腳本生成：使用 <b>${providerLabel}</b>`;
    } else {
      hint.className = "llm-status-hint warn";
      hint.innerHTML = `⚠️ 尚未偵測到可用語言模型；腳本生成需要先完成 LLM 設定。
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
    _setVal("googleModel",     data.google_model      || "gemini-2.5-flash");
    // API Key 顯示佔位（後端遮蔽實際 key）
    if (data.openai_api_key)    _setVal("openaiApiKey",    "••••••••");
    if (data.anthropic_api_key) _setVal("anthropicApiKey", "••••••••");
    if (data.google_api_key)    _setVal("googleApiKey",    "••••••••");
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
    google_model:      _getVal("googleModel"),
  };

  // 只在非佔位時才送 key（避免用「••••」覆蓋真實 key）
  const oKey = _getVal("openaiApiKey");
  const aKey = _getVal("anthropicApiKey");
  const gKey = _getVal("googleApiKey");
  if (oKey && oKey !== "••••••••") body.openai_api_key    = oKey;
  if (aKey && aKey !== "••••••••") body.anthropic_api_key = aKey;
  if (gKey && gKey !== "••••••••") body.google_api_key    = gKey;

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
