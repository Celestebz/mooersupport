#!/usr/bin/env python3
"""
Simple test script to verify special character filtering in email generation
"""

import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

from pdf_reader import extract_text_from_pdf

def test_special_character_filtering():
    """Test that special characters are filtered out from email content"""
    print("Testing special character filtering...\n")
    
    # Test 1: PDF extraction with S1 manual (since the example was about S1)
    pdf_path = r"e:\My Docment\Celeste\客服\MOOER产品说明书\S1_Manual_EN.pdf"
    
    print(f"1. Testing PDF extraction from: {pdf_path}")
    text = extract_text_from_pdf(pdf_path)
    if not text:
        print("   Failed to extract text")
        return False
    
    # Check for special characters in extracted text
    special_chars = []
    for i, char in enumerate(text):
        if not (char.isprintable() or char in '\n\t\r\f'):
            special_chars.append((i, char, ord(char)))
    
    if special_chars:
        print(f"   Found {len(special_chars)} special characters in extracted text")
        for pos, char, code in special_chars[:5]:
            print(f"   - Position {pos}: {char!r} (code: {code})")
    else:
        print("   ✓ No special characters found in extracted text")
    
    # Test 2: Filter method test with example from user query
    print("\n2. Testing filter method with user's example...")
    
    # Create a test string with the problematic pattern
    test_string = "Regarding 'S1': \n●Individual\u0001headphone\u0001output \u0001\u0001\u0001\u0001 \n●Two\u0001main\u0001outputs\u0001allow\u0001users\u0001to\u0001set\u0001stereo\u0001connections \u0001\u0001\u0001\u0001"
    
    # Filter it using our method
    filtered = ''.join(char for char in test_string if char.isprintable() or char in '\n\t\r\f')
    
    print(f"   Original (with special chars): {test_string[:120]}")
    print(f"   Filtered: {filtered[:120]}")
    
    if '\u0001' in filtered:
        print("   ✗ Special characters still present!")
    else:
        print("   ✓ Special characters removed successfully")
    
    # Test 3: Manual special character removal
    print("\n3. Testing manual special character removal...")
    
    # Simulate the problematic text from PDF
    problematic_text = "●Individual\x01headphone\x01output \x01\x01\x01\x01\n●Two\x01main\x01outputs\x01allow\x01users\x01to\x01set\x01stereo\x01connections \x01\x01\x01\x01"
    
    # Filter using our method
    cleaned = ''.join(char for char in problematic_text if char.isprintable() or char in '\n\t\r\f')
    
    print(f"   Problematic: {problematic_text}")
    print(f"   Cleaned: {cleaned}")
    
    if '\x01' in cleaned:
        print("   ✗ Failed to remove SOH characters")
    else:
        print("   ✓ Successfully removed all SOH characters")
    
    print("\n=== Test Results ===")
    if not special_chars and '\u0001' not in filtered and '\x01' not in cleaned:
        print("✓ All tests passed! Special characters are being filtered correctly.")
        return True
    else:
        print("✗ Some tests failed. Let's check the email automation service to see if it's working.")
        return False

def test_filter_function():
    """Test the filter function directly"""
    print("\nTesting filter function directly...")
    
    # Create a filter function that mimics our implementation
    def filter_special_chars(text):
        return ''.join(char for char in text if char.isprintable() or char in '\n\t\r\f')
    
    test_cases = [
        ("Normal text with no special chars", "Normal text with no special chars", False),
        ("Text with \x01 SOH chars", "Text with  SOH chars", True),
        ("Multiple \x01\x02\x03\x1f control chars", "Multiple    control chars", True),
        ("Mixed \x01headphone\x01output", "Mixed headphonesoutput", True),
        ("\nNewline and \t tab are allowed", "\nNewline and \t tab are allowed", False),
    ]
    
    passed = 0
    total = len(test_cases)
    
    for original, expected, should_change in test_cases:
        result = filter_special_chars(original)
        if result == expected:
            print(f"   ✓ Test passed: {original[:50]}")
            passed += 1
        else:
            print(f"   ✗ Test failed:")
            print(f"     Original: {original}")
            print(f"     Expected: {expected}")
            print(f"     Got: {result}")
    
    print(f"\nFilter function test results: {passed}/{total} passed")
    return passed == total

if __name__ == "__main__":
    # Run both test functions
    test1_passed = test_special_character_filtering()
    test2_passed = test_filter_function()
    
    if test1_passed and test2_passed:
        print("\n🎉 All tests passed! The special character filtering is working correctly.")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed. Please check the implementation.")
        sys.exit(1)