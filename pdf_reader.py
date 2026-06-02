import sys
import os
import re
import argparse
import subprocess
import time
import sys
import tempfile

# Set stdout to use UTF-8
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def get_pdf_path(product_model, pdf_dir=r"e:\My Docment\Celeste\客服\MOOER产品说明书"):
    """
    根据产品型号查找对应的PDF或Markdown文件路径
    
    Args:
        product_model (str): 产品型号，如 "GE150"
        pdf_dir (str): 文件存放目录
        
    Returns:
        str: 找到的文件路径，若未找到则返回None
    """
    # 产品型号到文件名的映射
    product_pdf_map = {
        "C4 AirSwitch": "C4 AirSwitch_Manual_EN.pdf",
        "DRUMMER X2": "DRUMMER_X2_Manul_EN.pdf",
        "F15i Li": "F15i Li_Manual_EN_V01_2025.06.19.pdf",
        "F40i": "F40i&F40i Li_Manual_EN_V01_2025.12.16.pdf",
        "F40i Li": "F40i&F40i Li_Manual_EN_V01_2025.12.16.pdf",
        "F4": "F4_Manual_EN.pdf",
        "GE1000": "GE1000_Manual_EN.pdf",
        "GE150": "GE150_Manual_EN.pdf",
        "GE150 Plus": "GE150_Plus_Manual_EN_250521(1).pdf",
        "GE150 PRO": "GE150_PRO_Manual_EN.pdf",
        "GE150 MAX": "GE150_MAX_Manual_EN.pdf",
        "GL100": "GL100_Manual_EN.pdf",
        "GS1000": "GS1000_Manual_EN.pdf",
        "Loopation": "Loopation_Manul_EN.pdf",
        "M1": "M1_Manua_EN.pdf",
        "Ocean Machine": "Ocean_Machine_Manual_EN1531311959673.pdf",
        "Preamp Live": "Preamp live_Manual_EN1539920585717.pdf",
        "Prime P1": "Prime P1_Manual_EN.pdf",
        "Prime P2": "Prime P2_Manual_EN.pdf",
        "SD30i": "SD30i_Manual_EN.pdf",
        "TONE CAPTURE": "TONE_CAPTUR_Manual_EN1565769881254.pdf",
        "AIR P05": "AIR P05_Manual_EN.pdf",
        "Audiofile": "Audiofile_Manual_EN&POR(1).pdf",
        "CAB X2": "CAB_X2_Manual_EN.pdf",
        "GE100": "GE100_Manual_EN_V021531310920146(1).pdf",
        "Groove Loop X2": "Groove_Loop_X2_Manual_EN.pdf",
        "HORNET 15i&30i": "HORNET_15i&30i_Manual_EN.pdf",
        "HORNET 30": "HORNET_30_Manual_EN.pdf",
        "M2": "M2_Manual_EN_V02_2025.08.26.pdf",
        "MWV1": "MWV1(Free Step)_Manual_EN1531310902944(1).pdf",
        "Ocean Machine II": "Ocean_Machine II_Manual_EN.pdf",
        "PE100": "PE100 _Manual_EN.pdf",
        "Pitch Step": "Pitch Step_Manual_EN1531311997168(1).pdf",
        "Radar": "Radar_Manual_EN_V011531312026193(1).pdf",
        "Red Truck": "Red Truck_Manual_EN.pdf",
        "S1": "S1_Manual_EN.pdf",
        "GL200": "GL200_Manua_EN_V01_2025.08.05.pdf",
        "GTRS": "GTRS_Manual_EN.pdf",
        "Harmonier": "Harmonier_Manual_EN.pdf",
        "PCL6 MKII": "PCL6 MKII_Manual_EN.pdf"
    }
    
    # 尝试精确匹配
    if product_model in product_pdf_map:
        pdf_filename = product_pdf_map[product_model]
        pdf_path = os.path.join(pdf_dir, pdf_filename)
        if os.path.exists(pdf_path):
            return pdf_path

    # 优先查找 .md 文件（Troubleshooting Guide 通常比手册更新、更针对）
    # 遍历目录查找包含产品型号的 .md 文件
    for filename in os.listdir(pdf_dir):
        if filename.lower().endswith(".md") and product_model.lower() in filename.lower():
            return os.path.join(pdf_dir, filename)
    
    # 尝试模糊匹配 (优先全字匹配或长词匹配)
    # 将字典按键长度降序排序，防止 "GE150" 错误匹配到 "GE150 Pro"
    sorted_models = sorted(product_pdf_map.keys(), key=len, reverse=True)
    
    for model in sorted_models:
        filename = product_pdf_map[model]
        # 只有当产品型号确实包含在映射键中时才匹配
        if product_model.lower() in model.lower() or model.lower() in product_model.lower():
             # 双向检查不够安全，容易误判。
             pass

    # 更安全的模糊匹配：
    # 1. 如果输入是 "GE150"，不应该匹配 "GE150 Pro"
    # 2. 如果输入是 "GE150 Pro"，应该匹配 "GE150 Pro" 而不是 "GE150"
    
    # 使用之前排序过的 keys 进行检查
    product_model_nospaces = product_model.lower().replace(" ", "")
    for model in sorted_models:
        model_nospaces = model.lower().replace(" ", "")
        # 如果输入的型号包含字典中的型号（例如输入 "Mooer GE150 Pedal"，包含 "GE150"）
        # 或者去空格后互相包含（如 "pe 100" 和 "pe100"）
        if model.lower() in product_model.lower() or model_nospaces in product_model_nospaces:
             pdf_path = os.path.join(pdf_dir, product_pdf_map[model])
             if os.path.exists(pdf_path):
                return pdf_path
                
    # 遍历目录查找包含产品型号的PDF文件 (最后的手段)
    for filename in os.listdir(pdf_dir):
        if product_model.lower() in filename.lower() or product_model_nospaces in filename.lower().replace(" ", ""):
            if filename.endswith(".pdf"):
                return os.path.join(pdf_dir, filename)
    
    return None

def _actual_extraction_logic(file_path):
    """
    实际执行PDF提取的核心逻辑
    """
    text = ""
    
    # 0. 尝试使用 PyMuPDF (fitz) - 速度最快且最稳定
    try:
        import fitz
        doc = fitz.open(file_path)
        t = ""
        max_pages = min(len(doc), 50)
        for i in range(max_pages):
            page = doc[i]
            t += page.get_text() + "\n"
        doc.close()
        
        # 验证文本是否有效
        if t and t.strip() and "(cid:" not in t[:500] and len(set(t[:500])) > 10:
            return t
    except ImportError:
        pass
    except Exception as e:
        print(f"PyMuPDF failed: {e}")
    
    # 1. 尝试使用 pypdfium2
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(file_path)
        t = ""
        max_pages = min(len(pdf), 50)
        for i in range(max_pages):
            page = pdf[i]
            textpage = page.get_textpage()
            t += textpage.get_text_range() + "\n"
            textpage.close()
        
        # 验证文本是否有效
        if t and t.strip() and "(cid:" not in t[:500] and len(set(t[:500])) > 10:
            return t
    except Exception as e:
        print(f"pypdfium2 failed: {e}")

    # 2. 尝试使用 pdfplumber
    try:
        import pdfplumber
        t = ""
        with pdfplumber.open(file_path) as pdf:
            max_pages = min(len(pdf.pages), 20)
            for i in range(max_pages):
                page_text = pdf.pages[i].extract_text()
                if page_text:
                    t += page_text + "\n"
        
        if t and t.strip():
            return ''.join(char for char in t if char.isprintable() or char in '\n\t\r\f')
    except Exception as e:
        print(f"pdfplumber failed: {e}")

    # 3. 最后回退到 pypdf
    try:
        from pypdf import PdfReader
        t = ""
        reader = PdfReader(file_path)
        max_pages = min(len(reader.pages), 50)
        for i in range(max_pages):
            page_text = reader.pages[i].extract_text()
            if page_text:
                t += page_text + "\n"
        
        if t and t.strip():
            return ''.join(char for char in t if char.isprintable() or char in '\n\t\r\f')
    except Exception as e:
        print(f"pypdf extraction failed: {e}")
        
    return None

def extract_text_from_pdf(file_path, timeout=15):
    """
    从PDF或Markdown文件中提取文本内容 (基于子进程硬超时保护)
    """
    if not os.path.exists(file_path):
        return None
    
    # 如果是 Markdown 文件，直接读取
    if file_path.lower().endswith('.md'):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except:
            return None

    # 使用独立的子进程提取文本，避免复杂PDF导致原生C扩展死锁或无限占用CPU
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as temp_out:
        temp_out_path = temp_out.name
        
    try:
        # 设置在Windows上不弹出黑框
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        env = os.environ.copy()
        env['PYTHONUTF8'] = "1"
        
        subprocess.run(
            [sys.executable, __file__, "--raw-extract", file_path, temp_out_path],
            timeout=timeout,
            check=False,
            env=env,
            creationflags=creationflags
        )
        
        with open(temp_out_path, 'r', encoding='utf-8') as f:
            result = f.read()
            
        if result.startswith("ERROR:"):
            print(f"Extraction logged error: {result}")
            return None
        elif not result.strip():
            return None
        return result
        
    except subprocess.TimeoutExpired:
        print(f"Extraction timed out after {timeout} seconds on {os.path.basename(file_path)}. Skipped to prevent blocking.")
        return None
    except Exception as e:
        print(f"Subprocess extraction failed: {e}")
        return None
    finally:
        if os.path.exists(temp_out_path):
            try:
                os.remove(temp_out_path)
            except:
                pass

def search_keywords_in_pdf(pdf_text, keywords, context_lines=5):
    """
    在PDF文本中搜索关键词，并返回包含关键词的上下文
    
    Args:
        pdf_text (str): PDF提取的文本内容
        keywords (list): 关键词列表
        context_lines (int): 上下文行数
        
    Returns:
        dict: 关键词到上下文的映射
    """
    results = {}
    
    if not pdf_text or not keywords:
        return results
    
    lines = pdf_text.split("\n")
    
    for keyword in keywords:
        keyword_results = []
        keyword_lower = keyword.lower()
        
        for i, line in enumerate(lines):
            if keyword_lower in line.lower():
                # 获取上下文
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                context = "\n".join(lines[start:end])
                keyword_results.append({
                    "line_number": i + 1,
                    "context": context
                })
        
        if keyword_results:
            results[keyword] = keyword_results
    
    return results

def get_troubleshooting_info(pdf_text, issue):
    """
    从PDF文本中提取与故障相关的信息
    
    Args:
        pdf_text (str): PDF提取的文本内容
        issue (str): 故障描述
        
    Returns:
        str: 提取的故障排除信息
    """
    if not pdf_text:
        return None
    
    # 常见故障排除章节关键词
    troubleshooting_keywords = [
        "troubleshooting", "problem", "issue", "fix", "solution",
        "not working", "broken", "failed", "error", "malfunction"
    ]
    
    # 从故障描述中提取关键词
    issue_keywords = re.findall(r'\w+', issue.lower())
    
    # 结合常见故障关键词和问题关键词进行搜索
    all_keywords = troubleshooting_keywords + issue_keywords
    results = search_keywords_in_pdf(pdf_text, all_keywords)
    
    # 整合结果
    combined_results = []
    seen_lines = set()
    
    for keyword, keyword_results in results.items():
        for result in keyword_results:
            if result["line_number"] not in seen_lines:
                combined_results.append(result["context"])
                seen_lines.add(result["line_number"])
    
    if combined_results:
        return "\n\n".join(combined_results[:3])  # 返回前3个最相关的结果
    
    # 如果没有找到匹配的内容，返回一个通用的故障排除建议
    return f"Based on the issue '{issue}', here are some general troubleshooting steps:\n\n1. Check all connections and power sources\n2. Restart the device and try again\n3. Refer to the product manual for specific troubleshooting\n4. If the issue persists, contact customer support with detailed information\n"

def get_usage_info(pdf_text, feature):
    """
    从PDF文本中提取与功能使用相关的信息
    
    Args:
        pdf_text (str): PDF提取的文本内容
        feature (str): 功能描述
        
    Returns:
        str: 提取的功能使用信息
    """
    if not pdf_text:
        return None
    
    # 从功能描述中提取关键词
    feature_keywords = re.findall(r'\w+', feature.lower())
    results = search_keywords_in_pdf(pdf_text, feature_keywords)
    
    # 整合结果
    combined_results = []
    seen_lines = set()
    
    for keyword, keyword_results in results.items():
        for result in keyword_results:
            if result["line_number"] not in seen_lines:
                combined_results.append(result["context"])
                seen_lines.add(result["line_number"])
    
    if combined_results:
        return "\n\n".join(combined_results[:2])  # 返回前2个最相关的结果
    
    # 如果没有找到匹配的内容，返回一个通用的功能使用建议
    return f"For information about '{feature}', please refer to the product manual.\n\nGeneral steps for using this feature:\n1. Ensure the device is properly connected\n2. Access the feature through the device menu\n3. Follow the on-screen instructions or refer to the manual for detailed settings\n4. If you encounter any issues, contact customer support\n"

def main():
    """
    主函数，处理命令行参数
    """
    # 隐藏选项: 处理原始提取请求，供 subprocess 调用
    if len(sys.argv) == 4 and sys.argv[1] == "--raw-extract":
        file_path = sys.argv[2]
        out_path = sys.argv[3]
        text = _actual_extraction_logic(file_path)
        with open(out_path, 'w', encoding='utf-8') as f:
            if text:
                f.write(text)
            else:
                f.write("")
        return
        
    parser = argparse.ArgumentParser(description="Mooer PDF Manual Reader and Search Tool")
    parser.add_argument("--model", type=str, help="Product model name, e.g., GE150")
    parser.add_argument("--extract", action="store_true", help="Extract full text from PDF")
    parser.add_argument("--search", type=str, help="Search keywords in PDF, separated by commas")
    parser.add_argument("--troubleshoot", type=str, help="Get troubleshooting information for a specific issue")
    parser.add_argument("--usage", type=str, help="Get usage information for a specific feature")
    parser.add_argument("--context", type=int, default=5, help="Number of context lines to show (default: 5)")
    
    args = parser.parse_args()
    
    if not args.model:
        print("Error: --model parameter is required")
        return
    
    # 获取PDF路径
    pdf_path = get_pdf_path(args.model)
    if not pdf_path:
        print(f"Error: Could not find PDF manual for model '{args.model}'")
        return
    
    print(f"Found manual: {pdf_path}")
    
    # 提取PDF文本
    pdf_text = extract_text_from_pdf(pdf_path)
    if not pdf_text:
        print(f"Error: Could not extract text from PDF: {pdf_path}")
        return
    
    # 处理不同的命令
    if args.extract:
        print(f"=== Extracted text from {args.model} manual ===")
        try:
            # Directly use UTF-8 text without gbk conversion
            print(pdf_text[:2000] + "..." if len(pdf_text) > 2000 else pdf_text)
            print(f"\n=== End of extraction (total {len(pdf_text)} characters) ===")
        except Exception as e:
            print(f"Error displaying text: {e}")
            print(f"Total characters extracted: {len(pdf_text)}")
    
    if args.search:
        keywords = [k.strip() for k in args.search.split(",")]
        print(f"=== Search results for '{args.search}' in {args.model} manual ===")
        results = search_keywords_in_pdf(pdf_text, keywords, args.context)
        
        if not results:
            print("No matches found")
        else:
            for keyword, matches in results.items():
                print(f"\n--- Results for '{keyword}' ---")
                for i, match in enumerate(matches[:3]):  # 只显示前3个匹配
                    print(f"Match {i+1} (line {match['line_number']}):")
                    print(match['context'])
                    print("---")
    
    if args.troubleshoot:
        print(f"=== Troubleshooting information for '{args.troubleshoot}' ===")
        info = get_troubleshooting_info(pdf_text, args.troubleshoot)
        if info:
            print(info)
        else:
            print("No troubleshooting information found")
    
    if args.usage:
        print(f"=== Usage information for '{args.usage}' ===")
        info = get_usage_info(pdf_text, args.usage)
        if info:
            print(info)
        else:
            print("No usage information found")

if __name__ == "__main__":
    main()