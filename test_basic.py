print("Hello, World!")
print("Testing Python script execution...")

# 测试基本功能
try:
    import os
    import sys
    import re
    import argparse
    import subprocess
    
    print("All required modules imported successfully!")
    print(f"Python version: {sys.version}")
    print(f"Current directory: {os.getcwd()}")
    
    # 测试PDF文件查找功能
    pdf_dir = r"e:\My Docment\Celeste\客服\MOOER产品说明书"
    print(f"PDF directory exists: {os.path.exists(pdf_dir)}")
    
    if os.path.exists(pdf_dir):
        files = os.listdir(pdf_dir)
        pdf_files = [f for f in files if f.endswith('.pdf')]
        print(f"Found {len(pdf_files)} PDF files in directory")
        if pdf_files:
            print(f"First PDF file: {pdf_files[0]}")
    
    print("Test completed successfully!")
    
except Exception as e:
    print(f"Error during test: {e}")
    import traceback
    traceback.print_exc()