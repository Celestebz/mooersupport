"""
一次性批量提取所有MOOER产品说明书的文本缓存。
后续新增PDF时，再跑一次即可增量更新。
"""
import os
import json
import sys
import time

# 使用项目已有的 pdf_reader 模块的提取逻辑
sys.path.insert(0, os.path.dirname(__file__))

PDF_DIR = r"E:\My Docment\Celeste\客服\MOOER产品说明书"
CACHE_DIR = r"E:\My Docment\Celeste\客服\manuals_cache"
INDEX_FILE = os.path.join(CACHE_DIR, "index.json")
FAIL_LOG = os.path.join(CACHE_DIR, "extract_failures.log")


def extract_text(pdf_path, timeout=30):
    """直接调用 _actual_extraction_logic，不经过子进程"""
    from pdf_reader import _actual_extraction_logic
    return _actual_extraction_logic(pdf_path)


def sanitize_filename(name):
    """把产品名做成安全的缓存文件名"""
    name = os.path.splitext(name)[0]  # 去 .pdf
    # 去特殊字符
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
    safe = safe.strip().replace(" ", "_")
    return safe


def build_cache():
    pdf_files = [f for f in os.listdir(PDF_DIR) if f.lower().endswith(".pdf")]
    total = len(pdf_files)
    print(f"找到 {total} 个PDF\n")

    # 加载已有索引
    existing_index = {}
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                existing_index = json.load(f)
        except:
            pass

    failures = []
    updated = False

    for i, pdf_name in enumerate(sorted(pdf_files), 1):
        pdf_path = os.path.join(PDF_DIR, pdf_name)
        cache_name = sanitize_filename(pdf_name) + ".txt"
        cache_path = os.path.join(CACHE_DIR, cache_name)

        pdf_mtime = os.path.getmtime(pdf_path)

        # 检查缓存是否有效：缓存存在且比PDF新
        if os.path.exists(cache_path) and os.path.getmtime(cache_path) >= pdf_mtime:
            print(f"[{i}/{total}] SKIP {pdf_name} (缓存有效)")
            continue

        # 提取
        print(f"[{i}/{total}] EXTRACT {pdf_name} ...", end=" ", flush=True)
        start = time.time()
        text = extract_text(pdf_path, timeout=30)
        elapsed = time.time() - start

        if text and text.strip():
            size_kb = len(text) / 1024
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(text)
            product_key = pdf_name
            existing_index[product_key] = {
                "pdf_name": pdf_name,
                "cache_file": cache_name,
                "text_chars": len(text),
                "text_kb": round(size_kb, 1),
                "pdf_mtime": pdf_mtime,
            }
            updated = True
            print(f"OK ({size_kb:.0f}KB, {elapsed:.1f}s)")
        else:
            print(f"FAIL (空白或提取失败)")
            failures.append({"pdf_name": pdf_name, "error": "empty extraction"})

    # 清理：删除无对应PDF的旧缓存
    valid_cache_names = {sanitize_filename(f) + ".txt" for f in pdf_files}
    for cache_file in os.listdir(CACHE_DIR):
        if cache_file.endswith(".txt") and cache_file not in valid_cache_names:
            os.remove(os.path.join(CACHE_DIR, cache_file))
            print(f"CLEANUP: 删除过期缓存 {cache_file}")

    # 写索引
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_index, f, ensure_ascii=False, indent=2)

    # 写失败日志
    if failures:
        with open(FAIL_LOG, "w", encoding="utf-8") as f:
            for item in failures:
                f.write(f"{item['pdf_name']}: {item['error']}\n")

    print(f"\n=== 完成 ===")
    print(f"成功: {len(existing_index)} 个产品")
    print(f"失败: {len(failures)} 个")
    if updated:
        print(f"索引已更新: {INDEX_FILE}")
    if failures:
        print(f"失败日志: {FAIL_LOG}")


if __name__ == "__main__":
    build_cache()
