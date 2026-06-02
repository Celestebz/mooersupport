"""
重新识别所有邮件的产品型号
用法: python reidentify_products.py [--force]
"""
import sys
import os
import argparse

# 添加当前目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import DatabaseHandler
from ai_handler import AIHandler
from response_generator import ResponseGenerator
import re
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true', help='Skip confirmation prompt')
    args = parser.parse_args()

    # 初始化
    db = DatabaseHandler()
    ai_handler = AIHandler()

    # 初始化 ResponseGenerator 以使用其标准化逻辑
    response_gen = ResponseGenerator(
        templates_path="售后模板/Customer Service Email.txt",
        pdf_reader_path="pdf_reader.py",
        product_manuals_path="MOOER产品说明书"
    )

    # 获取所有有产品型号的邮件
    emails = db.get_emails(limit=500)

    print(f"Found {len(emails)} emails to process")

    # 需要重新识别的邮件（排除已经标准化的）
    to_reprocess = []
    for email in emails:
        product = email.get('product_model')
        if product:
            # 检查是否需要标准化
            normalized = response_gen._normalize_product_model(product)
            if normalized != product:
                to_reprocess.append((email['id'], email['subject'], email['body'], product, normalized))

    print(f"\nEmails needing normalization: {len(to_reprocess)}")
    print("\nSample of products that will be normalized:")
    seen = set()
    count = 0
    for email_id, subject, body, old, new in to_reprocess:
        if old not in seen and count < 20:
            print(f"  {old} -> {new}")
            seen.add(old)
            count += 1

    # 确认继续
    print(f"\nTotal: {len(to_reprocess)} emails will be updated.")
    if not args.force:
        response = input("\nContinue? (y/n): ")
        if response.lower() != 'y':
            print("Cancelled")
            return
    else:
        print("Running in force mode...")

    # 重新识别 - 只对无法标准化的邮件调用 AI
    success = 0
    failed = 0
    skipped = 0

    # 先只标准化能直接转换的
    print("\nStep 1: Direct normalization...")
    direct_normalized = 0

    for i, (email_id, subject, body, old_product, expected_new) in enumerate(to_reprocess):
        # 如果已经有期望值，直接更新
        if expected_new:
            db.update_email_ai_analysis(email_id, {
                'intent': 'Technical Support',  # 保留原值
                'sentiment': 'Neutral',         # 保留原值
                'product_model': expected_new
            })
            direct_normalized += 1
            if (i + 1) % 20 == 0:
                print(f"  Processed {i + 1}/{len(to_reprocess)}")

    print(f"Directly normalized: {direct_normalized} emails")

    # 对于无法标准化的邮件，调用 AI 重新识别
    to_reidentify = [(eid, sub, bod, old, new)
                     for eid, sub, bod, old, new in to_reprocess
                     if not new]

    print(f"\nStep 2: Re-identify {len(to_reidentify)} emails with AI...")
    if len(to_reidentify) > 0 and not args.force:
        response = input("Continue with AI re-identification? (y/n): ")
        if response.lower() != 'y':
            print("Skipped AI re-identification")
            return
        try:
            # 调用 AI 重新分析
            result = ai_handler.analyze_email_content(
                email_subject=subject,
                email_body=body
            )

            ai_product = result.get('product_model', 'Unknown')

            # 用新逻辑标准化
            normalized = response_gen._normalize_product_model(ai_product)

            # 如果 AI 返回 Unknown 但我们有期望值，使用期望值
            if not normalized and expected_new:
                normalized = expected_new

            if normalized:
                # 更新数据库
                db.update_email_ai_analysis(email_id, {
                    'intent': result.get('intent', 'Technical Support'),
                    'sentiment': result.get('sentiment', 'Neutral'),
                    'product_model': normalized
                })
                success += 1

                if (i + 1) % 10 == 0:
                    print(f"Processed {i + 1}/{len(to_reprocess)}")
            else:
                # 无法标准化，保留原值但更新 intent/sentiment
                db.update_email_ai_analysis(email_id, {
                    'intent': result.get('intent', 'Technical Support'),
                    'sentiment': result.get('sentiment', 'Neutral'),
                    'product_model': old_product  # 保留原值
                })
                print(f"  Could not normalize: {ai_product}, keeping: {old_product}")

        except Exception as e:
            failed += 1
            logger.error(f"Error processing {email_id}: {e}")

    print(f"\nDone! Success: {success}, Failed: {failed}")


if __name__ == "__main__":
    main()
