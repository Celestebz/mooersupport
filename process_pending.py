#!/usr/bin/env python3
"""处理数据库中状态为new的待处理邮件"""
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')

if "--force" not in sys.argv:
    print("DEPRECATED: process_pending.py uses legacy duplicate logic and can skip valid customer replies.")
    print("Run with --force only for manual recovery after reviewing the code.")
    sys.exit(1)

from database import DatabaseHandler
from imap_handler import IMAPHandler
from ai_handler import AIHandler
from content_extractor import ContentExtractor
from response_generator import ResponseGenerator
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def process_pending_emails(limit=50):
    """处理待处理的邮件"""
    db = DatabaseHandler()
    imap = IMAPHandler()
    ai = AIHandler()  # 用于分析邮件
    content_extractor = ContentExtractor()  # 用于提取邮件信息

    # 初始化 ResponseGenerator
    templates_path = os.path.join(os.getcwd(), "售后模板", "Customer Service Email.txt")
    pdf_reader_path = os.path.join(os.getcwd(), "pdf_reader.py")
    product_manuals_path = os.path.join(os.getcwd(), "MOOER产品说明书")
    generator = ResponseGenerator(templates_path, pdf_reader_path, product_manuals_path)

    # 连接IMAP
    imap.connect_imap()

    # 获取所有状态为new的邮件
    emails = db.get_emails(status='new', limit=limit)
    logger.info(f"找到 {len(emails)} 封待处理邮件")

    processed = 0
    skipped_duplicate = 0

    for email in emails:
        email_id = email['id']
        subject = email.get('subject', '')
        sender = email.get('sender', '')
        body = email.get('body', '')

        # 检查重复: 如果同一个发送者已经有过回复（drafted/sent），则跳过
        # 这样避免同一个用户重复发送多封邮件时生成多个草稿
        import sqlite3
        conn = sqlite3.connect('mooer_support.db')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, status, product_model FROM emails WHERE sender=? AND status IN ('drafted', 'sent') ORDER BY received_at DESC LIMIT 1",
            (sender,)
        )
        dup = cursor.fetchone()
        conn.close()

        if dup:
            dup_id, dup_status, dup_product = dup
            logger.info(f"跳过重复邮件: {sender} (已有{dup_status}记录, 产品:{dup_product})")
            db.update_email_status(email_id, 'skipped', reasoning=f"Duplicate: already replied to {sender}")
            imap.mark_as_read(email_id)
            skipped_duplicate += 1
            continue

        logger.info(f"处理: ID={email_id} | {subject[:40]}...")

        try:
            # 使用AI分析并生成回复
            email_content = f"Subject: {subject}\n\n{body}"

            # 提取信息 (使用 content_extractor 而不是直接调用 ai)
            email_info = content_extractor.extract_info(email_content, sender_email=sender)
            email_info['subject'] = subject
            email_info['body'] = body

            intent = email_info.get("problem_category", "Technical Support")
            logger.info(f"  分析结果: intent={intent}, product={email_info.get('product_model', 'Unknown')}")

            # 生成回复
            draft = generator.generate_response(email_info, email_content)

            if draft:
                # 保存草稿
                db.update_email_status(
                    email_id,
                    status='drafted',
                    draft_body=draft,
                    reasoning=email_info.get('reasoning', '')
                )
                logger.info(f"  -> 已生成草稿")
            else:
                # 标记为跳过
                db.update_email_status(email_id, status='skipped', reasoning='No draft generated')
                logger.info(f"  -> 跳过")

            processed += 1

        except Exception as e:
            logger.error(f"处理邮件 {email_id} 出错: {e}")
            db.update_email_status(email_id, status='skipped', reasoning=str(e))

    imap.disconnect_imap()
    logger.info(f"完成! 共处理 {processed} 封邮件，跳过重复 {skipped_duplicate} 封")

if __name__ == '__main__':
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    process_pending_emails(limit)
