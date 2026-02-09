#!/usr/bin/env python3
"""
Test script to verify the improved response generation functionality
"""

import sys
import os

# Add the current directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from content_extractor import ContentExtractor

class MockResponseGenerator:
    """Mock response generator to test the improved content extraction"""
    
    def __init__(self):
        self.content_extractor = ContentExtractor()
    
    def test_keyword_extraction(self, email_content):
        """Test the improved keyword extraction"""
        print("\n=== Testing Keyword Extraction ===")
        print(f"Email Content: {email_content[:100]}...")
        
        keywords = self.content_extractor._extract_keywords(email_content)
        print(f"Extracted Keywords: {keywords}")
        
        return keywords
    
    def test_content_analysis(self, email_content):
        """Test the content analysis"""
        print("\n=== Testing Content Analysis ===")
        print(f"Email Content: {email_content[:100]}...")
        
        info = self.content_extractor.extract_info(email_content)
        print(f"Product Model: {info['product_model']}")
        print(f"Problem Category: {info['problem_category']}")
        print(f"Sentiment: {info['sentiment']}")
        print(f"Keywords: {info['keywords']}")
        
        return info

# Test cases
if __name__ == "__main__":
    # Create test cases
    test_cases = [
        {
            "name": "GE150 Firmware Update Issue",
            "content": "Subject: GE150 Firmware Update Issue\n\nI'm having trouble updating the firmware on my GE150. My computer won't recognize it when I connect it via USB. I'm using Windows 11. Please help!"
        },
        {
            "name": "Prime P2 SELECT Button Question",
            "content": "Subject: Prime P2 SELECT Button\n\nDoes the Prime P2 have a SELECT button? I can't find it in the manual and I need to navigate through the menus."
        },
        {
            "name": "Ocean Machine II Display Settings",
            "content": "Subject: Ocean Machine II Display Settings\n\nHello, Is it possible to change display settings to bpm or miliseconds from percents? I have no idea how to use percents to set up time for delays."
        },
        {
            "name": "GE150 Max Li Bass Tuning",
            "content": "Subject: GE150 Max Li Bass Tuning\n\nI wanted to ask you guys if it is possible to tune a Bass with this Product? Because i tried to tune my 5 String Bass with it and it won`t detect the B and E String, which every Multieffect Processor i know does easily."
        }
    ]
    
    # Create test instance
    tester = MockResponseGenerator()
    
    print("Testing Improved Email Response Generation")
    print("=" * 50)
    
    for test_case in test_cases:
        print(f"\n\nTesting: {test_case['name']}")
        print("-" * 30)
        
        # Test keyword extraction
        tester.test_keyword_extraction(test_case['content'])
        
        # Test content analysis
        tester.test_content_analysis(test_case['content'])
    
    print("\n\nTest completed successfully!")
