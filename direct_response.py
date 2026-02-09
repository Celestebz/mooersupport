import sys
import argparse
import logging
import os
import io

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from content_extractor import ContentExtractor
from response_generator import ResponseGenerator

# Configure logging to stderr to keep stdout clean for the result
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def main():
    parser = argparse.ArgumentParser(description="Generate email response from text input")
    parser.add_argument("text", nargs="?", help="Email content text")
    parser.add_argument("--file", help="Read email content from file")
    args = parser.parse_args()

    # Get input text
    email_content = ""
    if args.file:
        try:
            with open(args.file, 'r', encoding='utf-8') as f:
                email_content = f.read()
        except Exception as e:
            sys.stderr.write(f"Error reading file: {e}\n")
            return
    elif args.text:
        email_content = args.text
    else:
        # Read from stdin
        if sys.stdin.encoding != 'utf-8':
            sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
        email_content = sys.stdin.read()

    if not email_content or not email_content.strip():
        sys.stderr.write("Error: No email content provided.\n")
        return

    # Paths (Dynamic based on script location)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    templates_path = os.path.join(base_dir, "售后模板", "Customer Service Email.txt")
    pdf_reader_path = os.path.join(base_dir, "pdf_reader.py")
    product_manuals_path = os.path.join(base_dir, "MOOER产品说明书")

    try:
        # Initialize components
        extractor = ContentExtractor()
        generator = ResponseGenerator(templates_path, pdf_reader_path, product_manuals_path)

        # 1. Extract Info
        # Suppress extraction logs by ensuring logger level is high
        extractor.logger.setLevel(logging.ERROR)
        
        info = extractor.extract_info(email_content)
        
        # 2. Generate Response
        # Suppress generator logs
        generator.logger.setLevel(logging.ERROR)
        if generator.ai_handler:
             generator.ai_handler.logger.setLevel(logging.ERROR)

        response = generator.generate_response(info, email_content)

        if response:
            print(response)
        else:
            sys.stderr.write("Error: Failed to generate response.\n")

    except Exception as e:
        sys.stderr.write(f"Error processing request: {str(e)}\n")

if __name__ == "__main__":
    main()