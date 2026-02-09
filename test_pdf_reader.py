import os
from PyPDF2 import PdfReader

def test_pdf_reading():
    """
    简单测试PDF读取功能
    """
    print("Testing PDF reading functionality...")
    
    # 测试文件路径
    pdf_path = r"e:\My Docment\Celeste\客服\MOOER产品说明书\GE150_Manual_EN.pdf"
    print(f"Testing with file: {pdf_path}")
    
    # 检查文件是否存在
    if not os.path.exists(pdf_path):
        print(f"Error: File not found: {pdf_path}")
        return False
    
    try:
        # 尝试打开PDF文件
        reader = PdfReader(pdf_path)
        print(f"Successfully opened PDF, total pages: {len(reader.pages)}")
        
        # 尝试读取第一页
        first_page = reader.pages[0]
        text = first_page.extract_text()
        print(f"Successfully extracted text from first page, length: {len(text)} characters")
        print(f"First 100 characters: {text[:100]}...")
        
        return True
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return False

if __name__ == "__main__":
    test_pdf_reading()