"""
对扫描版PDF做OCR，用PyMuPDF渲染页面 + Tesseract识别文本。
处理 build_manual_cache.py 失败的3个PDF。
"""
import os
import sys

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io

# Tesseract 安装路径
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

PDF_DIR = r"E:\My Docment\Celeste\客服\MOOER产品说明书"
CACHE_DIR = r"E:\My Docment\Celeste\客服\manuals_cache"

# 失败的3个
FAILED_PDFS = [
    "(MDM1)Micro Drummer_Manual_CN&EN_V01_转曲.pdf",
    "Audiofile_Manual_EN&POR(1).pdf",
    "GE100_Manual_EN_V021531310920146(1).pdf",
]


def ocr_pdf(pdf_path, dpi=300, lang="eng"):
    """用PyMuPDF把每页渲染成图像，再OCR"""
    doc = fitz.open(pdf_path)
    full_text = []

    for page_num in range(doc.page_count):
        page = doc[page_num]
        # 渲染页面为图像
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))

        # OCR
        text = pytesseract.image_to_string(img, lang=lang)
        full_text.append(f"--- Page {page_num + 1} ---\n{text}")
        print(f"  Page {page_num + 1}/{doc.page_count} done ({len(text)} chars)")

    doc.close()
    return "\n\n".join(full_text)


def sanitize_filename(name):
    name = os.path.splitext(name)[0]
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
    safe = safe.strip().replace(" ", "_")
    return safe


def main():
    import json

    # 加载索引
    index_path = os.path.join(CACHE_DIR, "index.json")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    else:
        index = {}

    for pdf_name in FAILED_PDFS:
        pdf_path = os.path.join(PDF_DIR, pdf_name)
        if not os.path.exists(pdf_path):
            print(f"SKIP {pdf_name} (文件不存在)")
            continue

        print(f"\n=== OCR: {pdf_name} ===")
        # 判断语言：Micro Drummer是CN&EN，用 chi_sim+eng；其他用 eng
        lang = "eng+chi_sim" if "CN" in pdf_name else "eng"

        text = ocr_pdf(pdf_path, dpi=300, lang=lang)

        if text.strip():
            cache_name = sanitize_filename(pdf_name) + ".txt"
            cache_path = os.path.join(CACHE_DIR, cache_name)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(text)

            size_kb = len(text) / 1024
            pdf_mtime = os.path.getmtime(pdf_path)
            index[pdf_name] = {
                "pdf_name": pdf_name,
                "cache_file": cache_name,
                "text_chars": len(text),
                "text_kb": round(size_kb, 1),
                "pdf_mtime": pdf_mtime,
                "ocr": True,  # 标记为OCR提取
            }
            print(f"  -> 缓存写入: {cache_name} ({size_kb:.0f}KB)")
        else:
            print(f"  -> FAIL: OCR结果为空")

    # 更新索引
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"\n=== 完成，索引已更新 ===")


if __name__ == "__main__":
    main()
