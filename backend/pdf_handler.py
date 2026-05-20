"""
pdf_handler.py — PDF 文字擷取（v2）

升級重點：
1. 使用 blocks 抽取 + 欄位偵測，解決雙欄/表格排版錯亂
2. 去除重複出現的頁眉頁腳
3. 文字過少時自動嘗試 OCR（需 Tesseract，沒裝就明確告知）
4. 提供品質報告，前端可顯示
"""

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── 主入口 ──────────────────────────────────────────────
def extract(pdf_path: Path, enable_ocr: bool = True) -> str:
    """擷取 PDF 全文（向後相容介面）"""
    result = extract_with_report(pdf_path, enable_ocr=enable_ocr)
    return result["text"]


def extract_with_report(pdf_path: Path, enable_ocr: bool = True) -> dict:
    """
    擷取 PDF 並回傳品質報告。
    回傳：{
        "text": str,
        "pages": int,
        "ocr_pages": int,           # 用 OCR 抽出的頁數
        "low_quality": bool,        # 文字過短/抽出失敗
        "warnings": list[str],
    }
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise RuntimeError("請先安裝 PyMuPDF：pip install pymupdf")

    doc = fitz.open(str(pdf_path))
    n_pages = len(doc)
    pages_text: list[str] = []
    ocr_pages = 0
    warnings: list[str] = []

    for page_idx, page in enumerate(doc):
        page_text = _extract_page_smart(page)

        # 若文字過少且啟用 OCR，嘗試 OCR
        if len(page_text.strip()) < 30 and enable_ocr:
            ocr_text = _ocr_page(page)
            if ocr_text:
                page_text = ocr_text
                ocr_pages += 1
                logger.info(f"第 {page_idx+1} 頁使用 OCR 抽取")

        pages_text.append(page_text)

    doc.close()

    # 去除重複出現的頁眉/頁腳
    cleaned_pages = _strip_headers_footers(pages_text)
    combined = "\n\n".join(p for p in cleaned_pages if p.strip())

    # 清理排版噪音
    combined = _clean_layout_noise(combined)

    # 品質檢查
    total_chars = len(combined.strip())
    low_quality = total_chars < n_pages * 50  # 平均每頁少於 50 字就算低品質

    if ocr_pages > 0 and ocr_pages == n_pages:
        warnings.append(f"全部 {n_pages} 頁皆透過 OCR 抽取，文字可能有辨識誤差")
    elif ocr_pages > 0:
        warnings.append(f"{ocr_pages}/{n_pages} 頁使用 OCR 抽取，請檢查內容")

    if low_quality:
        warnings.append(
            f"抽取文字過少（共 {total_chars} 字 / {n_pages} 頁）。"
            "若為掃描版 PDF，請安裝 Tesseract 啟用 OCR；"
            "或先用其他工具（如 Adobe Acrobat / ChatGPT）轉成文字後貼上。"
        )

    return {
        "text": combined.strip(),
        "pages": n_pages,
        "ocr_pages": ocr_pages,
        "low_quality": low_quality,
        "warnings": warnings,
    }


# ── 單頁智慧抽取（欄位偵測） ─────────────────────────
def _extract_page_smart(page) -> str:
    """
    用 blocks 抽取並依「欄 → y 座標」排序。
    自動偵測雙欄版型，避免左右欄文字交錯。
    """
    # blocks: (x0, y0, x1, y1, text, block_no, block_type)
    blocks = page.get_text("blocks", sort=False)
    text_blocks = [b for b in blocks if len(b) >= 7 and b[6] == 0 and b[4].strip()]

    if not text_blocks:
        # 退回最簡單模式
        return page.get_text("text").strip()

    page_width = page.rect.width
    mid_x = page_width / 2

    # 計算每個 block 的中心 x，判斷是否雙欄
    left_blocks = []
    right_blocks = []
    for b in text_blocks:
        x_center = (b[0] + b[2]) / 2
        block_width = b[2] - b[0]
        # block 跨越中線 → 視為全寬（標題/段落）
        if b[0] < mid_x - 20 and b[2] > mid_x + 20 and block_width > page_width * 0.5:
            # 全寬 block：用特殊標記放在中間
            left_blocks.append(("full", b))
            right_blocks.append(("full", b))
        elif x_center < mid_x:
            left_blocks.append(("left", b))
        else:
            right_blocks.append(("right", b))

    # 判斷是否為雙欄：左右兩邊都有「夠多」內容才算
    left_only = [b for tag, b in left_blocks if tag == "left"]
    right_only = [b for tag, b in right_blocks if tag == "right"]

    if len(left_only) >= 3 and len(right_only) >= 3:
        # 雙欄：左欄整段 → 右欄整段
        left_only.sort(key=lambda b: b[1])
        right_only.sort(key=lambda b: b[1])
        ordered = left_only + right_only
    else:
        # 單欄：依 y 座標排序
        ordered = sorted(text_blocks, key=lambda b: (b[1], b[0]))

    return "\n".join(b[4].strip() for b in ordered if b[4].strip())


# ── OCR fallback ───────────────────────────────────────
def _ocr_page(page) -> str:
    """
    用 pytesseract + PyMuPDF render 對單頁做 OCR。
    Tesseract 未安裝時靜默回傳空字串。
    """
    try:
        import pytesseract
        from PIL import Image
        import io
    except ImportError:
        return ""

    # 確認 tesseract binary 在 PATH（或前面已設定 pytesseract.tesseract_cmd）
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return ""

    try:
        # 200 DPI 對中文夠用，太高會慢
        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        # 繁中 + 簡中 + 英；缺哪個 lang pack 會自動略過
        for lang in ("chi_tra+chi_sim+eng", "chi_tra+eng", "chi_sim+eng", "eng"):
            try:
                text = pytesseract.image_to_string(img, lang=lang)
                if text.strip():
                    return text.strip()
            except pytesseract.TesseractError:
                continue
        return ""
    except Exception as e:
        logger.warning(f"OCR 失敗：{e}")
        return ""


# ── 頁眉頁腳清理 ────────────────────────────────────────
def _strip_headers_footers(pages_text: list[str]) -> list[str]:
    """
    偵測在 >=50% 頁面重複出現的短行，移除（通常是頁眉/頁腳）。
    """
    if len(pages_text) < 3:
        return pages_text  # 頁數太少無法統計

    # 每頁取「前2行 + 後2行」當候選
    candidate_counter: Counter = Counter()
    for pt in pages_text:
        lines = [l.strip() for l in pt.split("\n") if l.strip()]
        if not lines:
            continue
        for line in lines[:2] + lines[-2:]:
            # 排除太短/太長的行（內文段落通常很長，頁眉頁腳通常短）
            if 1 < len(line) < 60:
                candidate_counter[line] += 1

    threshold = max(2, len(pages_text) // 2)
    repeating = {line for line, cnt in candidate_counter.items() if cnt >= threshold}

    if not repeating:
        return pages_text

    cleaned = []
    for pt in pages_text:
        lines = pt.split("\n")
        kept = [l for l in lines if l.strip() not in repeating]
        cleaned.append("\n".join(kept))
    return cleaned


# ── 排版噪音清理 ────────────────────────────────────────
def _clean_layout_noise(text: str) -> str:
    # 連續空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 連續空白
    text = re.sub(r"[ \t]{2,}", " ", text)
    # 單獨一行只有頁碼數字
    text = re.sub(r"(?m)^\s*\d{1,4}\s*$", "", text)
    # 連字符斷行（PDF 英文常見）：word-\nword → wordword
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # 中文字後的單一換行 → 空格（PDF 常常每行斷句）
    # 但要保留段落（雙換行）
    text = re.sub(r"([\u4e00-\u9fff])\n([\u4e00-\u9fff])", r"\1\2", text)
    return text
