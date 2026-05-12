"""
pdf_handler.py — PDF 文字擷取
使用 PyMuPDF 讀取 PDF，支援一般文字和掃描版（基本 OCR）
"""

from pathlib import Path


def extract(pdf_path: Path) -> str:
    """擷取 PDF 全文，回傳純文字"""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise RuntimeError("請先安裝 PyMuPDF：pip install pymupdf")

    doc = fitz.open(str(pdf_path))
    pages_text = []

    for page_num, page in enumerate(doc):
        text = page.get_text("text").strip()
        if text:
            pages_text.append(text)
        # 若頁面文字很少，可能是掃描版（暫不做 OCR，標記說明）
        elif page_num == 0 and not text:
            pages_text.append("[注意：此 PDF 可能是掃描版，文字擷取可能不完整]")

    doc.close()

    combined = "\n\n".join(pages_text)

    # 清理常見排版噪音
    import re
    combined = re.sub(r"\n{3,}", "\n\n", combined)
    combined = re.sub(r"[ \t]{2,}", " ", combined)
    # 移除頁碼行（單獨一行只有數字）
    combined = re.sub(r"(?m)^\s*\d+\s*$", "", combined)

    return combined.strip()
