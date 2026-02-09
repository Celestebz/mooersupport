#!/usr/bin/env python3
"""
Script to search for SELECT button information in Prime P2 manual
"""

import sys
import os

# Add current directory to path so we can import pdf_reader
sys.path.append(os.getcwd())

from pdf_reader import get_pdf_path, extract_text_from_pdf, search_keywords_in_pdf

def main():
    # Search for SELECT button in Prime P2 manual
    product_model = "Prime P2"
    keywords = ["SELECT", "button", "control"]
    
    print(f"Searching for SELECT button information in {product_model} manual...")
    
    # Get PDF path
    pdf_path = get_pdf_path(product_model)
    if not pdf_path:
        print(f"Error: Could not find PDF manual for {product_model}")
        return
    
    print(f"Found manual: {pdf_path}")
    
    # Extract text from PDF
    pdf_text = extract_text_from_pdf(pdf_path)
    if not pdf_text:
        print(f"Error: Could not extract text from PDF")
        return
    
    print(f"Extracted {len(pdf_text)} characters from PDF")
    
    # Search for keywords
    results = search_keywords_in_pdf(pdf_text, keywords, context_lines=3)
    
    if not results:
        print("No information found about SELECT button")
        return
    
    print("\n=== Search Results ===")
    for keyword, matches in results.items():
        print(f"\n--- Results for '{keyword}' ---")
        for i, match in enumerate(matches[:5]):  # Show top 5 matches
            print(f"Match {i+1} (line {match['line_number']}):")
            print(match['context'])
            print("---")
    
    # Also check for any buttons or controls section
    print("\n=== Checking for Controls Section ===")
    if "control" in pdf_text.lower():
        lines = pdf_text.split('\n')
        for i, line in enumerate(lines):
            if "control" in line.lower() and "section" in line.lower():  # Look for "Controls Section" or similar
                start = max(0, i - 2)
                end = min(len(lines), i + 20)  # Show next 20 lines
                print(f"Found controls section around line {i+1}:")
                print('\n'.join(lines[start:end]))
                break
    
    print("\n=== Summary ===")
    if "select" in pdf_text.lower():
        print(f"SELECT button was mentioned in the manual")
    else:
        print(f"SELECT button was NOT mentioned in the manual")

if __name__ == "__main__":
    main()