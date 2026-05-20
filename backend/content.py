"""
content.py — 腳本生成
將主題/文字轉換成適合聆聽的口語腳本

支援輸出模式：
  single      — 單人解說（摘要導讀）
  duo         — 雙人 Podcast（探究式對話）
  short_video — 短影音腳本

支援 LLM 後端：
  ollama    — 本地 Ollama（預設）
  lmstudio  — 本地 LMStudio（OpenAI 相容）
  openai    — OpenAI API
  anthropic — Anthropic Claude API
  google    — Google AI Studio（Gemini API，免費額度大）
"""

import json
import re
import textwrap
from pathlib import Path
from typing import Optional

import config


# ── LLM 設定讀寫 ──────────────────────────────────────────

_DEFAULT_SETTINGS = {
    "provider":            "ollama",
    "ollama_model":        "qwen3:8b",
    "ollama_base_url":     "http://localhost:11434",
    "lmstudio_base_url":   "http://localhost:1234",
    "lmstudio_model":      "",
    "openai_api_key":      "",
    "openai_model":        "gpt-4o-mini",
    "anthropic_api_key":   "",
    "anthropic_model":     "claude-haiku-4-5-20251001",
    "google_api_key":      "",
    "google_model":        "gemini-2.5-flash",
}


def load_llm_settings() -> dict:
    f = config.LLM_SETTINGS_FILE
    if f.exists():
        try:
            saved = json.loads(f.read_text(encoding="utf-8"))
            return {**_DEFAULT_SETTINGS, **saved}
        except Exception:
            pass
    return dict(_DEFAULT_SETTINGS)


def save_llm_settings(data: dict) -> dict:
    merged = {**_DEFAULT_SETTINGS, **data}
    config.LLM_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.LLM_SETTINGS_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return merged


# ── 角色 System Prompt ─────────────────────────────────────

_SYSTEM_SINGLE = """你是一位台灣國中小學的教學助手，用親切溫暖的口吻為學生做「預習導讀」。

你的任務：
- 把即將上課的主題，用口語化、生活化的方式做「深度摘要說明」
- 讓學生在正式上課前，先有完整的概念框架，降低學習焦慮
- 語氣像朋友在聊天，不像教科書在念稿

內容要求（每一項都要做到）：
1. 開場：用一個讓人有共鳴或驚訝的問題/故事吸引注意
2. 背景：說明這個主題的來源或重要性（為什麼要學它？）
3. 核心概念：用比喻把最重要的觀念說清楚，至少兩個不同角度
4. 生活例子：至少舉兩個具體的日常生活情境
5. 常見迷思：說出學生最常搞錯的一個觀念，並糾正它
6. 記憶鉤子：提供一個讓學生記住核心概念的方法或口訣
7. 收尾：呼應開場，帶著期待感結束

說話風格：
- 台灣國語，自然口語（欸、對啊、其實、你知道嗎、說穿了就是...）
- 多用比喻、故事、生活情境
- 不說教，不用艱深術語（若要用，立刻解釋）
- 節奏輕快，有起有落，段落之間有自然的轉折語"""

_SYSTEM_DUO_A = """你是「主持A（小艾）」，一個代表學生視角的共學主持人。

性格特質：
- 充滿好奇心，不怕問「笨問題」，反而因此挖出很多有趣的東西
- 會說出學生心裡真正想問但不好意思問的話
- 聽到有趣的點會自然反應（哦！、等等、那這樣的話...、你是說...？）
- 偶爾會用自己的生活經驗引入新話題
- 有時候會說出「錯的理解」，讓大維來修正，這樣聽眾也能學到東西

說話習慣：台灣口語，自然、不做作，語速稍快"""

_SYSTEM_DUO_B = """你是「主持B（大維）」，一個知識豐富但說話輕鬆的領域達人。

性格特質：
- 擅長用比喻和故事解釋抽象概念，從不直接背定義
- 不說教，而是「帶著對方一起發現」
- 會對主持A的問題產生真實的共鳴（對，我第一次也這樣想！）
- 喜歡分享自己踩過的坑、反直覺的事實、冷知識
- 說話有層次：先給大圖，再挖細節，讓對方跟得上

說話習慣：台灣口語，有溫度，像在咖啡廳聊天，偶爾用「你想想看」帶動思考"""

_SYSTEM_SHORT = """你是一位充滿活力的台灣教育 YouTuber，專門製作30-90秒的知識短影音腳本。

你的任務：
- 開頭5秒必須讓人停止滑動（強力鉤子）
- 用最精煉的語言傳達最核心的概念
- 節奏快、有能量、口語化
- 結尾要有行動呼籲（上課見！去查一下！）"""


# 嚴格模式：用於 from_text（PDF / SRT / YouTube 等有原文時），避免幻覺
_SYSTEM_SINGLE_STRICT = """你是一位台灣國中小學的教學助手，會根據老師提供的「參考內容」做口語化導讀。

核心原則（最重要）：
- 你的任務是「忠實轉述 + 口語化包裝」，不是「自由創作」
- 只能用參考內容裡實際提到的事實、定義、例子、數字
- 參考內容沒寫的，就不要寫。寧可短，也不要編

說話風格：
- 台灣口語化（欸、對啊、其實、你知道嗎）
- 像朋友在聊天，不像教科書
- 段落自然流暢，有起有落

可以做的事：
- 用比喻幫助理解參考內容裡的概念
- 把生硬的書面語改成自然口語
- 用「我們來想想看」「重點是」這類連接語讓內容更好聽
- 若參考內容有提到例子/數字/人名，照實引用

不可以做的事：
- 不要自己編造參考內容裡沒有的「冷知識」「歷史故事」「研究數據」
- 不要捏造學者名字、年份、地點
- 不要硬塞「常見迷思」如果參考內容沒提到
- 不要為了湊字數而重複或灌水"""


_SYSTEM_DUO_STRICT_NOTE = """

═══ 嚴格模式 ═══
本次對話必須完全基於老師提供的「參考內容」展開。
- 兩位主持人只能討論參考內容裡真實存在的事實/例子/數字
- 不可編造參考內容沒有的背景故事、研究、案例、人名
- 小艾的問題要圍繞參考內容；大維的解釋只能根據參考內容
- 若參考內容篇幅不足，寧可對話短一點，不要瞎掰補字數"""


def _make_duo_system() -> str:
    """雙人 Podcast 的合體 system prompt（單次呼叫，LLM 扮演兩個角色）"""
    return f"""{_SYSTEM_DUO_A}

---

{_SYSTEM_DUO_B}

---

你的任務：同時扮演主持A和主持B，寫出一段有深度的雙人探究式對話。

格式規定：每行開頭必須是「主持A：」或「主持B：」，每行台詞至少20字，不要寫過短的回應。

對話結構（按順序展開）：
1. 【開場鉤子】從一個日常情境或反直覺的事實切入，不要直接說「今天來聊XXX」
2. 【概念建構】大維用比喻解釋核心概念，小艾追問細節，至少來回3輪
3. 【舉例深挖】至少兩個具體生活例子，每個例子都要讓小艾說出「原來如此」
4. 【常見誤區】小艾說出一個常見的錯誤理解，大維耐心解釋差異
5. 【冷知識/延伸】大維分享一個相關的有趣事實或延伸思考
6. 【回顧收尾】兩人一起整理3個重點，結尾留一個值得思考的問題

對話品質要求：
- 不是單純一問一答，要有接話、驚訝、反應、追問
- 台詞要有個性：小艾語氣活潑跳脫，大維穩重但有趣
- 避免「好的」「沒錯」等空洞回應，每句話都要有資訊量"""


# ── Prompt 建構 ────────────────────────────────────────────

_MODE_LABELS = {
    "single":      "單人解說",
    "duo":         "雙人 Podcast",
    "short_video": "短影音",
}

_MODE_FORMAT = {
    "single": """輸出格式：連續口語段落，每段 4-6 句，段落間空一行。
不要加說話者標記，直接寫成旁白敘述（第一人稱「你」稱呼聽眾）。

結構要求（依序呈現，自然過渡）：
▸ 開場：反直覺問句或驚喜事實，讓聽眾想繼續聽
▸ 背景：這個主題的來源／重要性（1段）
▸ 核心概念一：用比喻A解釋（1-2段）
▸ 核心概念二：用生活例子B說明（1-2段）
▸ 常見迷思：學生最常搞錯的地方，以「很多人以為...但其實...」格式
▸ 記憶方法：一個讓概念好記的技巧
▸ 收尾：呼應開場，帶著期待感邀請聽眾去上課""",

    "duo": """輸出格式：對話腳本，每行格式固定為：
主持A：（台詞，至少20字）
主持B：（台詞，至少20字）

每輪對話必須推進劇情或增加資訊量，禁止空洞的「好的」「是喔」等回應。
每個觀點至少來回2-3輪對話再往下走，不能點到為止。""",

    "short_video": """輸出格式：每行前加時間戳 [MM:SS]，總長度 60-90 秒。
[00:00] 超強鉤子（讓人停止滑動的衝擊性開場）
[00:05] 放大痛點或好奇心
[00:12] 核心概念（用最簡潔的話說清楚）
[00:25] 一個具體的生活例子
[00:40] 反轉或驚喜資訊
[00:55] 行動呼籲（去上課！去查！）""",
}


def _build_prompt(
    content: str,
    output_mode: str,
    target_minutes: float,
    instruction: str,
    strict_source: bool = False,
) -> tuple[str, str, int, int]:
    """回傳 (system_prompt, user_prompt, target_chars, min_chars)"""
    mode_label  = _MODE_LABELS.get(output_mode, "單人解說")
    mode_format = _MODE_FORMAT.get(output_mode, _MODE_FORMAT["single"])

    # 語速：中文口語約 260 字/分鐘（保守估計確保夠長）
    CHARS_PER_MIN = 260

    # 嚴格模式下單人 system 換成 strict 版；雙人在原 system 末尾追加嚴格注意
    def _pick_single_system():
        return _SYSTEM_SINGLE_STRICT if strict_source else _SYSTEM_SINGLE

    def _pick_duo_system():
        base = _make_duo_system()
        return (base + _SYSTEM_DUO_STRICT_NOTE) if strict_source else base

    if output_mode == "short_video":
        target_chars  = 300
        min_chars     = 240
        duration_note = "總長度嚴格 60-90 秒（約 240-360 字）"
        system_prompt = _SYSTEM_SHORT + (_SYSTEM_DUO_STRICT_NOTE if strict_source else "")
    elif target_minutes <= 1:
        target_chars  = max(100, int(target_minutes * 60 * (CHARS_PER_MIN / 60)))
        min_chars     = int(target_chars * 0.85)
        duration_note = (
            f"目標時長：約 {int(target_minutes * 60)} 秒"
            f"（請寫 {min_chars}～{target_chars + 50} 個中文字）"
        )
        system_prompt = _pick_duo_system() if output_mode == "duo" else _pick_single_system()
    else:
        target_chars  = int(target_minutes * CHARS_PER_MIN)
        min_chars     = int(target_chars * 0.85)
        # 計算大約需要幾段（單人）或幾輪（雙人）
        if output_mode == "duo":
            n_turns = max(10, int(target_minutes * 12))  # 每分鐘約 12 輪對話
            size_hint = f"約 {n_turns} 輪以上的對話（每輪含A和B各一句）"
        else:
            n_paras = max(4, int(target_minutes * 3))    # 每分鐘約 3 段
            size_hint = f"約 {n_paras} 個以上的段落"
        # 嚴格模式下取消「低於 X 字 = 不合格」的硬要求，避免逼 LLM 編造
        length_warning = (
            f"\n   ⚠️ 低於 {min_chars} 字 = 不合格，必須持續寫到足夠長度"
            if not strict_source else
            "\n   💡 若參考內容不足以撐到此長度，寧可寫短，也不要編造"
        )
        duration_note = (
            f"目標時長：約 {target_minutes} 分鐘"
            f"（請寫 {min_chars}～{target_chars + 200} 個中文字，{size_hint}）"
            f"{length_warning}"
        )
        system_prompt = _pick_duo_system() if output_mode == "duo" else _pick_single_system()

    user_prompt = textwrap.dedent(f"""
{instruction}

{content}

請輸出一份「{mode_label}」腳本。

═══ 內容要求（最重要）═══
本腳本必須涵蓋上方主題的「真實知識內容」：
• 這個主題的核心定義和原理（用自己的話解釋，不要只是列標題）
• 這個主題在真實世界如何運作的具體說明
• 至少 3 個和主題直接相關的具體例子（要有細節，不能只說「例如...」帶過）
• 這個主題的背景脈絡：為什麼重要、從哪裡來、和什麼事有關
• 學習者常見的誤解或難以理解的部分，並提供清楚的解釋

═══ 長度要求（硬性）═══
{duration_note}

═══ 語言與風格 ═══
• 台灣口語化繁體中文，像說話一樣自然（不是念稿）
• 每個概念說完整、說清楚，不要點到為止
• 轉折自然，段落之間有銜接語

═══ 格式 ═══
{mode_format}

直接輸出腳本正文，不要加標題、不要加「好的以下是」等前言。
    """).strip()

    return system_prompt, user_prompt, target_chars, min_chars


# ── LLM 呼叫（多後端）────────────────────────────────────

def _call_llm(
    system: str,
    user: str,
    target_chars: int = 600,
    min_chars: int = 0,
    strict_source: bool = False,
) -> str:
    """
    依設定呼叫對應 LLM；若回傳太短，自動補寫一次後合併。
    失敗時拋出例外（讓呼叫端可以顯示明確錯誤訊息），不靜默回空字串。

    strict_source=True：用低 temperature（0.4）且不自動補寫（避免逼 LLM 編造）。
    """
    import logging
    logger = logging.getLogger(__name__)

    settings   = load_llm_settings()
    provider   = settings.get("provider", "ollama")
    min_chars  = min_chars or int(target_chars * 0.85)
    temperature = 0.4 if strict_source else 0.8

    # 中文 token 大約 1.5 token/字，給足緩衝避免截斷
    num_tokens = max(1500, int(target_chars * 3))

    logger.info(
        f"呼叫 LLM provider={provider}，目標 {target_chars} 字，"
        f"token budget={num_tokens}，strict={strict_source}，temp={temperature}"
    )

    def _dispatch(sys_p, usr_p, toks):
        if provider == "ollama":
            return _call_ollama(settings, sys_p, usr_p, toks, temperature)
        elif provider == "lmstudio":
            return _call_openai_compat(
                base_url=settings.get("lmstudio_base_url", "http://localhost:1234"),
                api_key="lmstudio",
                model=settings.get("lmstudio_model", ""),
                system=sys_p, user=usr_p, num_tokens=toks, temperature=temperature,
            )
        elif provider == "openai":
            return _call_openai_compat(
                base_url="https://api.openai.com",
                api_key=settings.get("openai_api_key", ""),
                model=settings.get("openai_model", "gpt-4o-mini"),
                system=sys_p, user=usr_p, num_tokens=toks, temperature=temperature,
            )
        elif provider == "anthropic":
            return _call_anthropic(settings, sys_p, usr_p, toks, temperature)
        elif provider == "google":
            return _call_google(settings, sys_p, usr_p, toks, temperature)
        return ""

    result = _dispatch(system, user, num_tokens)

    if not result:
        # LLM 完全沒回應：拋出有用的錯誤訊息
        hints = {
            "ollama":    "請確認 Ollama 已啟動（ollama serve），並已下載模型（ollama pull qwen3:8b）",
            "lmstudio":  "請確認 LMStudio 已啟動並載入模型",
            "openai":    "請確認 OpenAI API Key 正確",
            "anthropic": "請確認 Anthropic API Key 正確",
            "google":    "請確認 Google AI Studio API Key 正確（從 aistudio.google.com 取得）",
        }
        raise RuntimeError(
            f"LLM（{provider}）未回應或呼叫失敗。\n{hints.get(provider, '')}"
        )

    actual = len(result.replace(" ", "").replace("\n", ""))
    logger.info(f"LLM 回傳 {actual} 字（目標 {target_chars}，最低 {min_chars}）")

    # 嚴格模式下不自動補寫（補寫會逼 LLM 編造原文沒有的內容）
    if strict_source:
        return result

    # 若太短，發出「繼續寫」請求並合併
    if actual < min_chars:
        shortage = target_chars - actual
        logger.info(f"內容不足 {shortage} 字，發出補寫請求...")
        continue_prompt = (
            f"以下是你剛才寫的腳本（共約 {actual} 字），"
            f"但目標是 {target_chars} 字，還差約 {shortage} 字。\n"
            f"請直接繼續接著寫，不要重複已有內容，"
            f"繼續深入說明或補充更多具體例子，直到補足差距為止。\n\n"
            f"【已有內容結尾】\n{result[-300:]}\n\n【請從這裡繼續接寫】"
        )
        extra = _dispatch(system, continue_prompt, max(800, int(shortage * 3)))
        if extra:
            result = result.rstrip() + "\n\n" + extra.lstrip()
            logger.info(f"補寫後共 {len(result.replace(' ', '').replace(chr(10), ''))} 字")

    return result


def _call_ollama(
    settings: dict, system: str, user: str, num_tokens: int,
    temperature: float = 0.8,
) -> str:
    """Ollama chat API（加入完整錯誤記錄）"""
    import logging, httpx
    logger   = logging.getLogger(__name__)
    base_url = settings.get("ollama_base_url", "http://localhost:11434").rstrip("/")
    model    = settings.get("ollama_model", "qwen3:8b")

    # 先確認 Ollama 是否在線
    try:
        ping = httpx.get(f"{base_url}/api/tags", timeout=5.0)
        if ping.status_code != 200:
            raise RuntimeError(f"Ollama 回應異常（HTTP {ping.status_code}）")
        available_models = [m["name"] for m in ping.json().get("models", [])]
        logger.info(f"Ollama 已連線，可用模型：{available_models}")
    except httpx.ConnectError:
        raise RuntimeError(
            f"無法連線 Ollama（{base_url}）。請確認 Ollama 已啟動（在終端機執行 ollama serve）"
        )
    except Exception as e:
        raise RuntimeError(f"Ollama 連線失敗：{e}")

    # 選擇模型（優先用設定的，再從已安裝清單挑）
    chosen = None
    if model in available_models or any(model in m for m in available_models):
        chosen = model
    elif available_models:
        chosen = available_models[0]
        logger.warning(f"設定模型 {model!r} 未找到，改用 {chosen!r}")
    else:
        raise RuntimeError(
            f"Ollama 中沒有任何已安裝的模型。請先執行：ollama pull {model}"
        )

    logger.info(f"Ollama 使用模型：{chosen}，num_predict={num_tokens}")

    try:
        resp = httpx.post(
            f"{base_url}/api/chat",
            json={
                "model": chosen,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": num_tokens,
                    "num_gpu": 99,       # 讓 Ollama 盡量使用 GPU（有 GPU 時生效）
                    "num_ctx": max(4096, num_tokens + 2048),  # 確保 context window 夠大
                },
            },
            timeout=600.0,
        )
    except httpx.ReadTimeout:
        raise RuntimeError(f"Ollama 回應超時（模型 {chosen} 可能太慢或卡住）")
    except Exception as e:
        raise RuntimeError(f"Ollama 請求失敗：{e}")

    if resp.status_code != 200:
        raise RuntimeError(f"Ollama 回傳錯誤 HTTP {resp.status_code}：{resp.text[:200]}")

    text = resp.json().get("message", {}).get("content", "").strip()
    if not text:
        raise RuntimeError("Ollama 回傳空內容")

    # 移除 Qwen3 的 <think> 推理標籤
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    logger.info(f"Ollama 回傳 {len(text)} 字")
    return text


def _call_openai_compat(
    base_url: str, api_key: str, model: str,
    system: str, user: str, num_tokens: int,
    temperature: float = 0.8,
) -> str:
    """OpenAI 相容 API（也適用 LMStudio）"""
    import httpx
    if not api_key or (base_url == "https://api.openai.com" and not api_key):
        return ""
    base_url = base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens": num_tokens,
        "temperature": temperature,
    }
    if model:
        body["model"] = model
    try:
        resp = httpx.post(
            f"{base_url}/v1/chat/completions",
            headers=headers, json=body, timeout=300.0,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return ""


def _call_anthropic(
    settings: dict, system: str, user: str, num_tokens: int,
    temperature: float = 0.8,
) -> str:
    """Anthropic Claude API"""
    import httpx
    api_key = settings.get("anthropic_api_key", "")
    if not api_key:
        return ""
    model = settings.get("anthropic_model", "claude-haiku-4-5-20251001")
    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type":      "application/json",
            },
            json={
                "model": model,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "max_tokens": num_tokens,
                "temperature": temperature,
            },
            timeout=300.0,
        )
        if resp.status_code == 200:
            return resp.json()["content"][0]["text"].strip()
    except Exception:
        pass
    return ""


def _call_google(
    settings: dict, system: str, user: str, num_tokens: int,
    temperature: float = 0.8,
) -> str:
    """Google AI Studio Gemini API（免費額度：gemini-2.0-flash 等）"""
    import httpx
    api_key = settings.get("google_api_key", "")
    if not api_key:
        return ""
    model = settings.get("google_model", "gemini-2.5-flash")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    try:
        resp = httpx.post(
            url,
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [
                    {"role": "user", "parts": [{"text": user}]}
                ],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": num_tokens,
                },
            },
            timeout=300.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                return "".join(p.get("text", "") for p in parts).strip()
    except Exception:
        pass
    return ""


# ── Gemini 直讀 PDF（多模態，免抽取） ───────────────────
def from_pdf_via_gemini(
    pdf_path: Path,
    output_mode: str,
    target_minutes: float,
) -> str:
    """
    直接把 PDF 丟給 Gemini 多模態模型，由 Gemini 看版面+文字。
    解決掃描版/雙欄/表格 PDF 的解析問題。
    需要設定好 Google AI Studio API Key。
    """
    import base64
    import httpx
    import logging

    logger = logging.getLogger(__name__)
    settings = load_llm_settings()
    api_key = settings.get("google_api_key", "")
    if not api_key:
        raise RuntimeError(
            "Gemini 直讀 PDF 需要 Google AI Studio API Key。\n"
            "請到 LLM 設定 → 雲端 Google AI → 填入 API Key。"
        )

    model = settings.get("google_model", "gemini-2.5-flash")
    pdf_bytes = Path(pdf_path).read_bytes()
    pdf_size_mb = len(pdf_bytes) / 1024 / 1024
    if pdf_size_mb > 20:
        raise RuntimeError(
            f"PDF 太大（{pdf_size_mb:.1f}MB），Gemini 限制 20MB。"
            "請壓縮或分割後再試。"
        )

    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")

    # 共用 prompt 結構，但用 strict_source=True
    system, user_text, target_chars, min_chars = _build_prompt(
        content="（PDF 內容如上方檔案所示，請直接讀取）",
        output_mode=output_mode,
        target_minutes=target_minutes,
        instruction=(
            "請直接讀取上方附上的 PDF 檔案，根據 PDF 真實內容寫一份口語腳本。\n"
            "\n"
            "⚠️ 重要約束：\n"
            "1. 只能根據 PDF 裡實際存在的事實、定義、例子、數字、圖表來寫\n"
            "2. 不可編造 PDF 裡沒有的背景知識、案例、研究、人名\n"
            "3. 若 PDF 內容不足以撐到指定長度，寧可寫短，不要瞎掰\n"
            "4. 引用具體數字/名稱時必須與 PDF 完全一致"
        ),
        strict_source=True,
    )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    num_tokens = max(1500, int(target_chars * 3))

    logger.info(f"Gemini 直讀 PDF：{pdf_size_mb:.1f}MB，model={model}")

    try:
        resp = httpx.post(
            url,
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{
                    "role": "user",
                    "parts": [
                        {"inline_data": {"mime_type": "application/pdf", "data": pdf_b64}},
                        {"text": user_text},
                    ],
                }],
                "generationConfig": {
                    "temperature": 0.4,
                    "maxOutputTokens": num_tokens,
                },
            },
            timeout=600.0,
        )
    except Exception as e:
        raise RuntimeError(f"Gemini 連線失敗：{e}")

    if resp.status_code != 200:
        raise RuntimeError(f"Gemini 回傳錯誤 HTTP {resp.status_code}：{resp.text[:300]}")

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini 沒有回傳內容：{resp.text[:300]}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError("Gemini 回傳空內容")
    logger.info(f"Gemini 直讀 PDF 完成：{len(text)} 字")
    return text


# ── 公開介面 ───────────────────────────────────────────────

def from_topic(topic: str, output_mode: str, target_minutes: float) -> str:
    """從主題生成腳本（LLM 失敗時直接拋出例外，讓使用者看到原因）"""
    system, user, target_chars, min_chars = _build_prompt(
        content=f"主題：{topic}",
        output_mode=output_mode,
        target_minutes=target_minutes,
        instruction=(
            "請根據此主題，從零開始創作一個深度豐富的腳本。"
            "必須包含這個主題的真實知識內容：定義、原理、背景、應用場景、"
            "具體例子、常見誤解——所有說明都要有實質內容，不能只是泛泛而談。"
        ),
    )
    # 不使用 fallback：失敗讓使用者知道，而不是生成無關內容
    return _call_llm(system, user, target_chars, min_chars)


def from_topic_fallback(topic: str, output_mode: str, target_minutes: float) -> str:
    """備用：無 LLM 時的模板（僅供使用者主動選擇時使用）"""
    return _fallback_template(topic, output_mode, target_minutes)


def from_text(
    text: str,
    output_mode: str,
    target_minutes: float,
    rewrite: bool = True,
) -> str:
    """從已有文字改寫成口語腳本（LLM 失敗時直接拋出例外）"""
    if not rewrite:
        return _clean_script(text, output_mode)

    text = _trim_text(text, max_chars=30000)

    system, user, target_chars, min_chars = _build_prompt(
        content=f"參考內容：\n{text}",
        output_mode=output_mode,
        target_minutes=target_minutes,
        instruction=(
            "請根據以上參考內容，改寫成適合「預習聆聽」的深度口語腳本。\n"
            "\n"
            "⚠️ 重要約束（必須嚴格遵守）：\n"
            "1. 只能根據「參考內容」中真實存在的事實、定義、例子、數字、人名來寫。\n"
            "2. 不可自行編造參考內容沒有提到的背景知識、歷史、科學原理、具體案例。\n"
            "3. 若參考內容不足以撐到指定長度，寧可寫短一點，也不要瞎掰補字數。\n"
            "4. 引用具體數字/名稱時必須與參考內容完全一致，禁止「大概」「差不多」。\n"
            "5. 比喻可以用，但比喻所要解釋的「概念」必須是參考內容明確提到的。\n"
            "6. 若參考內容看起來雜亂、不連貫（如 PDF 抽取錯亂），請以你能辨識的部分為主，"
            "不要硬把斷裂處想像補全。\n"
            "\n"
            "在以上約束下：提煉要點、用口語化方式表達、必要時用比喻幫助理解、"
            "若參考內容有提到爭議或誤解才指出之。"
        ),
        strict_source=True,
    )
    # 不使用 fallback：失敗讓使用者知道，而不是生成無關內容
    return _call_llm(system, user, target_chars, min_chars, strict_source=True)


# ── Fallback 模板（無 LLM 時使用）────────────────────────

def _fallback_template(topic: str, output_mode: str, target_minutes: float) -> str:
    target_chars = max(60, int(target_minutes * 240))
    extra_blocks = max(0, int((target_chars - 300) / 120))

    _single_extras = [
        f"說到「{topic}」，有一個常見的迷思是覺得它很抽象、跟生活沒關係。但其實你每天都在不知不覺中跟它打交道。就好像你早上起床決定要穿什麼衣服，背後其實就有「{topic}」的影子在裡面。",
        f"學習「{topic}」最有效的方式，是先從「問問題」開始。你可以問自己：我在什麼時候會遇到這個？它的運作邏輯是什麼？帶著好奇心去上課，收穫會完全不一樣。",
        f"很多同學一開始學「{topic}」的時候，都覺得頭很痛。但這其實是正常的！任何新知識在最開始都會有一段「混沌期」。重要的是不要放棄，繼續往下走，你會突然「啊哈！」一聲就通了。",
        f"「{topic}」跟我們熟悉的很多事情其實都有連結。你可以試著想想看，在你的日常生活裡，有沒有哪些場景讓你想到今天要學的內容？把自己的例子帶進去，理解會快很多。",
        f"上課前先了解「{topic}」的好處是：你的大腦已經有了一個「鉤子」，新的知識可以很自然地掛上去。就像你整理房間之前先把架子擺好，東西才放得整齊。",
    ]
    _duo_extras = [
        (f"主持A：等等，我有個問題。「{topic}」到底是從哪裡來的？有什麼背景故事嗎？",
         f"主持B：哦這個問題問得好！其實「{topic}」是有它發展脈絡的。就是因為我們在某些情況下需要解決一個很具體的問題，所以才慢慢形成了這套概念。你可以把它理解成一種「人類集體智慧的結晶」。"),
        (f"主持A：那學「{topic}」最常踩的坑是什麼？",
         f"主持B：最常見的就是「以為自己懂了，但其實沒懂」。很多人看一遍就覺得沒問題，結果一用就錯了。所以最好的方法是馬上找個例子試試看，確認自己真的理解了。"),
        (f"主持A：如果要記住「{topic}」，有什麼好的方法嗎？",
         f"主持B：我自己的方法是「說給別人聽」。你如果能用自己的話，不看筆記地把「{topic}」解釋給朋友聽，那就代表你真的懂了。這個方法百試百靈！"),
    ]

    if output_mode == "duo":
        lines = [
            f"主持A：欸大維，今天我在預習，看到「{topic}」這個主題，說真的我有點摸不著頭緒，你可以幫我理解一下嗎？",
            f"主持B：當然可以！其實「{topic}」這個概念，說穿了就是要幫我們解決一個很常見的問題。你有沒有過這樣的經驗——",
            f"主持A：有有有！你說說看。",
            f"主持B：就是當你面對一個複雜的情況，你不知道從哪裡下手，對吧？「{topic}」提供的就是一個思考的切入點。",
            f"主持A：喔！所以它像是一把鑰匙？",
            f"主持B：對！就是這樣。而且這把鑰匙在生活裡超常用的，只是你可能沒有意識到它有個正式的名字。",
        ]
        for i in range(min(extra_blocks, len(_duo_extras))):
            a, b = _duo_extras[i]
            lines += [a, b]
        lines += [
            f"主持A：好，我現在感覺對「{topic}」有一點點概念了！",
            f"主持B：很好！帶著這個感覺去上課，你會發現老師說的話突然都變得很好懂。",
            f"主持A：期待！那我們上課見！",
            f"主持B：上課見，加油！",
        ]
        return "\n\n".join(lines)

    elif output_mode == "short_video":
        return textwrap.dedent(f"""
[00:00] 你知道嗎？「{topic}」這件事，其實跟你的日常生活超有關係！
[00:06] 很多人第一次聽到這個詞，都覺得很複雜、很難懂。
[00:12] 但其實，只要用對方法，三分鐘就能搞懂基本概念！
[00:18] 「{topic}」的核心就是——讓你用不同的角度看同一件事。
[00:25] 等等上課，老師會帶你深入探索！
[00:30] 帶著好奇心來，保證收穫滿滿！
        """).strip()

    else:  # single
        paras = [
            f"嗨，在正式上課之前，我想先跟你聊聊今天的主題——「{topic}」。",
            f"你有沒有曾經遇過一個狀況，就是老師在台上解釋某個概念，你聽了半天還是霧煞煞？其實這很正常，因為有些知識需要先有一點點背景框架，才能順利吸收。「{topic}」就是這樣一個值得先認識的主題。",
            f"「{topic}」說穿了其實不難理解。你可以把它想成是一個幫助我們看懂某件事情的工具。如果用生活中的例子來說，就好比你拿到一張地圖，有了這張地圖你才能在陌生的城市找到方向——「{topic}」就是那張地圖。",
        ]
        for i in range(min(extra_blocks, len(_single_extras))):
            paras.append(_single_extras[i])
        paras.append(
            f"你不需要現在就完全搞懂，只要帶著「哦，原來是這樣」的感覺去上課，"
            f"你就會發現吸收速度快很多！好，做好準備了嗎？我們等等上課見！"
        )
        return "\n\n".join(paras)


# ── 工具函式 ───────────────────────────────────────────────

def _trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars]
    last_end = max(
        trimmed.rfind("。"), trimmed.rfind("！"), trimmed.rfind("？"),
        trimmed.rfind("."), trimmed.rfind("!"), trimmed.rfind("?"),
    )
    if last_end > max_chars // 2:
        return trimmed[:last_end + 1]
    return trimmed


def _clean_script(text: str, output_mode: str) -> str:
    text = re.sub(r"\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}", "", text)
    text = re.sub(r"^\d+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
