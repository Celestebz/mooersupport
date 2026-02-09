import sys
import os
import re
import argparse
import subprocess

# Set stdout to use UTF-8
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def get_pdf_path(product_model, pdf_dir=r"e:\My Docment\Celeste\客服\MOOER产品说明书"):
    """
    根据产品型号查找对应的PDF文件路径
    
    Args:
        product_model (str): 产品型号，如 "GE150"
        pdf_dir (str): PDF文件存放目录
        
    Returns:
        str: 找到的PDF文件路径，若未找到则返回None
    """
    # 产品型号到PDF文件名的映射
    product_pdf_map = {
        "C4 AirSwitch": "C4 AirSwitch_Manual_EN.pdf",
        "DRUMMER X2": "DRUMMER_X2_Manul_EN.pdf",
        "F15i Li": "F15i Li_Manual_EN_V01_2025.06.19.pdf",
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
        "Harmonier": "Harmonier_Manual_EN.pdf"
    }
    
    # 尝试精确匹配
    if product_model in product_pdf_map:
        pdf_filename = product_pdf_map[product_model]
        pdf_path = os.path.join(pdf_dir, pdf_filename)
        if os.path.exists(pdf_path):
            return pdf_path
    
    # 尝试模糊匹配
    for model, filename in product_pdf_map.items():
        if product_model.lower() in model.lower():
            pdf_path = os.path.join(pdf_dir, filename)
            if os.path.exists(pdf_path):
                return pdf_path
    
    # 遍历目录查找包含产品型号的PDF文件
    for filename in os.listdir(pdf_dir):
        if filename.endswith(".pdf") and product_model.lower() in filename.lower():
            return os.path.join(pdf_dir, filename)
    
    return None

def extract_text_from_pdf(pdf_path):
    """
    从PDF文件中提取文本内容
    
    Args:
        pdf_path (str): PDF文件路径
        
    Returns:
        str: 提取的文本内容
    """
    if not os.path.exists(pdf_path):
        return None
    
    text = ""
    
    # 优先尝试 pdfplumber (提取质量更好)
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        
        # Filter text
        if text.strip():
             return ''.join(char for char in text if char.isprintable() or char in '\n\t\r\f')
    except ImportError:
        pass # pdfplumber not installed
    except Exception as e:
        print(f"pdfplumber extraction failed: {e}")

    # 回退到 PyPDF2
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        
        if text.strip():
            return ''.join(char for char in text if char.isprintable() or char in '\n\t\r\f')
    except Exception as e:
        print(f"PyPDF2 extraction failed: {e}")
        return f"[Error extracting content from {os.path.basename(pdf_path)}]\n\nError: {str(e)}\n"

    return None

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