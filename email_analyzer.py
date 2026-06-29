import imaplib
import email
from email.header import decode_header
import json
import re
import logging
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from collections import defaultdict, Counter

load_dotenv()


class EmailAnalyzer:
    def __init__(self, config_path=None):
        self.logger = logging.getLogger(__name__)
        self.config = self._load_config(config_path)
        self.imap = None
        from database import DatabaseHandler
        from ai_handler import AIHandler
        self.db = DatabaseHandler()
        self.ai = AIHandler()

    def _load_config(self, config_path):
        import yaml
        config = {}
        if config_path and os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
        else:
            config = {
                'email': {
                    'address': os.getenv('EMAIL_ADDRESS', 'support@mooeraudio.com'),
                    'password': os.getenv('EMAIL_PASSWORD', ''),
                    'imap': {
                        'server': os.getenv('IMAP_SERVER', 'imap.example.com'),
                        'port': int(os.getenv('IMAP_PORT', 993)),
                        'ssl': os.getenv('IMAP_SSL', 'True').lower() == 'true',
                        'folder': os.getenv('IMAP_FOLDER', 'INBOX')
                    }
                }
            }
        email_config = config.setdefault('email', {})
        # Keep secrets out of config.yml. Environment variables always win.
        email_config['address'] = os.getenv('EMAIL_ADDRESS', email_config.get('address', 'support@mooeraudio.com'))
        email_config['password'] = os.getenv('EMAIL_PASSWORD', email_config.get('password', ''))
        return config

    def _connect_imap(self):
        try:
            cfg = self.config['email']['imap']
            if cfg['ssl']:
                self.imap = imaplib.IMAP4_SSL(cfg['server'], cfg['port'])
            else:
                self.imap = imaplib.IMAP4(cfg['server'], cfg['port'])
            self.imap.login(self.config['email']['address'], self.config['email']['password'])
            self.logger.info(f"Connected to IMAP: {cfg['server']}")
            return True
        except Exception as e:
            self.logger.error(f"IMAP connect failed: {e}")
            return False

    def _disconnect_imap(self):
        if self.imap:
            try:
                self.imap.logout()
            except Exception:
                pass
            finally:
                self.imap = None

    def _parse_email(self, msg):
        subject = ''
        try:
            parts = decode_header(msg['Subject'])
            subject = ''.join(
                p.decode(enc or 'utf-8', errors='replace') if isinstance(p, bytes) else str(p)
                for p, enc in parts
            )
        except Exception:
            subject = str(msg.get('Subject', ''))

        sender = ''
        try:
            parts = decode_header(msg['From'])
            sender = ''.join(
                p.decode(enc or 'utf-8', errors='replace') if isinstance(p, bytes) else str(p)
                for p, enc in parts
            )
        except Exception:
            sender = str(msg.get('From', ''))

        date_str = msg.get('Date', '')
        message_id = msg.get('Message-ID', '')

        body = ''
        html_body = ''

        def get_payload_decoded(part):
            charset = part.get_content_charset() or 'utf-8'
            try:
                payload = part.get_payload(decode=True)
                return payload.decode(charset, errors='replace') if payload else ''
            except Exception:
                return ''

        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_disposition() in ['attachment', 'inline'] and part.get_filename():
                    continue
                ct = part.get_content_type()
                if ct == 'text/plain' and not body:
                    body = get_payload_decoded(part)
                elif ct == 'text/html' and not html_body:
                    html_body = get_payload_decoded(part)
        else:
            ct = msg.get_content_type()
            decoded = get_payload_decoded(msg)
            if ct == 'text/plain':
                body = decoded
            elif ct == 'text/html':
                html_body = decoded
                body = re.sub(r'<[^>]+>', '\n', html_body)
                body = re.sub(r'\n+', '\n', body).strip()

        return {
            'subject': subject,
            'sender': sender,
            'date': date_str,
            'message_id': message_id,
            'body': body[:5000],
            'html_body': html_body[:5000]
        }

    def search_emails_imap(self, keywords=None, since_date=None, before_date=None, max_emails=500):
        emails = []
        if not self._connect_imap():
            return emails
        try:
            folder = self.config['email']['imap']['folder']
            status, _ = self.imap.select(folder)
            if status != 'OK':
                self.logger.error(f"Failed to select folder: {folder}")
                return emails

            criteria_parts = []
            if since_date:
                criteria_parts.append(f'SINCE {since_date.strftime("%d-%b-%Y")}')
            if before_date:
                criteria_parts.append(f'BEFORE {before_date.strftime("%d-%b-%Y")}')
            if keywords:
                for kw in keywords:
                    criteria_parts.append(f'SUBJECT "{kw}"')

            criteria = ' '.join(criteria_parts) if criteria_parts else 'ALL'
            self.logger.info(f"IMAP search criteria: {criteria}")

            status, response = self.imap.uid('SEARCH', None, f'({criteria})')
            if status != 'OK' or not response[0]:
                self.logger.info("No emails found matching criteria")
                return emails

            uids = response[0].split()
            uids = uids[-min(max_emails, len(uids)):]
            self.logger.info(f"Found {len(uids)} emails to fetch")

            for uid in uids:
                uid_str = uid.decode('utf-8') if isinstance(uid, bytes) else str(uid)
                status, msg_data = self.imap.uid('FETCH', uid_str, '(BODY.PEEK[])')
                if status != 'OK':
                    continue
                for part in msg_data:
                    if isinstance(part, tuple):
                        msg = email.message_from_bytes(part[1])
                        email_data = self._parse_email(msg)
                        email_data['uid'] = uid_str
                        emails.append(email_data)

            self.logger.info(f"Fetched {len(emails)} emails from IMAP")
            return emails
        except Exception as e:
            self.logger.error(f"Error searching IMAP: {e}")
            return emails
        finally:
            self._disconnect_imap()

    def search_emails_db(self, product_model=None, keywords=None, since_date=None, before_date=None, limit=1000):
        try:
            conn = self.db._connect()
            conn.row_factory = None
            cursor = conn.cursor()

            conditions = []
            params = []

            if product_model:
                conditions.append("(product_model LIKE ? OR subject LIKE ? OR body LIKE ?)")
                params.extend([f'%{product_model}%'] * 3)

            if keywords:
                for kw in keywords:
                    conditions.append("(subject LIKE ? OR body LIKE ?)")
                    params.extend([f'%{kw}%'] * 2)

            if since_date:
                conditions.append("received_at >= ?")
                params.append(since_date.isoformat())

            if before_date:
                conditions.append("received_at <= ?")
                params.append(before_date.isoformat())

            where_clause = ' AND '.join(conditions) if conditions else '1=1'
            sql = f"SELECT id, sender, subject, body, received_at, product_model, ai_intent, ai_sentiment FROM emails WHERE {where_clause} ORDER BY received_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)
            rows = cursor.fetchall()
            columns = ['id', 'sender', 'subject', 'body', 'received_at', 'product_model', 'ai_intent', 'ai_sentiment']
            result = [dict(zip(columns, row)) for row in rows]
            conn.close()
            self.logger.info(f"Found {len(result)} emails in DB matching criteria")
            return result
        except Exception as e:
            self.logger.error(f"DB search error: {e}")
            return []

    def ai_analyze_issue_match(self, email_data, product_model, issue_description, issue_keywords):
        if not self.ai.enabled or not self.ai.client:
            return {'is_related': False, 'confidence': 0, 'reason': 'AI unavailable'}

        subject = email_data.get('subject', '')
        body = email_data.get('body', '')[:3000]

        prompt = f"""You are an expert at analyzing customer support emails for MOOER Audio.

TASK: Determine if this email is related to a SPECIFIC product issue.

PRODUCT MODEL: {product_model}
ISSUE DESCRIPTION: {issue_description}
KEYWORDS TO MATCH: {', '.join(issue_keywords)}

EMAIL TO ANALYZE:
Subject: {subject}
Body: {body}

RULES:
1. Return ONLY valid JSON, no markdown.
2. "is_related": true ONLY if the email is about "{product_model}" AND mentions the specific issue described above.
3. Be strict - if the email is about a different product or different issue, return false.
4. "confidence": float 0.0-1.0 (how confident you are)
5. "reason": brief explanation of your decision
6. "issue_details": extract any specific details about the problem (firmware version, error messages, etc.)

RESPOND WITH JSON:
{{"is_related": bool, "confidence": float, "reason": string, "issue_details": string}}"""

        try:
            response = self.ai.client.chat.completions.create(
                model=self.ai.model,
                messages=[
                    {"role": "system", "content": "You are an expert email analyst. Output only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            result_text = response.choices[0].message.content.strip()
            if result_text.startswith("```"):
                result_text = re.sub(r'```(?:json)?\s*', '', result_text).strip().rstrip('`').strip()
            result = json.loads(result_text)
            return result
        except Exception as e:
            self.logger.error(f"AI analysis error: {e}")
            return {'is_related': False, 'confidence': 0, 'reason': f'Error: {str(e)}'}

    def query_issues(self, product_model, issue_description, issue_keywords=None, date_range=None, use_imap=True, use_db=True, max_emails=500, batch_size=20):
        since_date = date_range[0] if date_range else None
        before_date = date_range[1] if date_range else None
        if issue_keywords is None:
            issue_keywords = [issue_description]

        all_emails = []
        source_map = {}

        if use_db:
            db_emails = self.search_emails_db(product_model=product_model, keywords=issue_keywords, since_date=since_date, before_date=before_date, limit=max_emails)
            for em in db_emails:
                em['_source'] = 'db'
                all_emails.append(em)
            source_map['db'] = len(db_emails)
            self.logger.info(f"DB: found {len(db_emails)} candidate emails")

        if use_imap:
            imap_emails = self.search_emails_imap(keywords=[product_model] + issue_keywords[:3], since_date=since_date, before_date=before_date, max_emails=max_emails)
            existing_uids = {em.get('uid') for em in all_emails if em.get('uid')}
            for em in imap_emails:
                if em.get('uid') not in existing_uids:
                    em['_source'] = 'imap'
                    all_emails.append(em)
            source_map['imap'] = len([e for e in all_emails if e['_source'] == 'imap'])
            self.logger.info(f"IMAP: found {source_map.get('imap', 0)} additional emails")

        self.logger.info(f"Total candidates: {len(all_emails)}")

        matched_emails = []
        total_analyzed = 0

        for i in range(0, len(all_emails), batch_size):
            batch = all_emails[i:i + batch_size]
            for em in batch:
                total_analyzed += 1
                result = self.ai_analyze_issue_match(em, product_model, issue_description, issue_keywords)
                em['ai_analysis'] = result
                if result.get('is_related'):
                    em['match_confidence'] = result.get('confidence', 0)
                    em['match_reason'] = result.get('reason', '')
                    em['issue_details'] = result.get('issue_details', '')
                    matched_emails.append(em)

            progress = min(total_analyzed, len(all_emails))
            self.logger.info(f"Analyzed {progress}/{len(all_emails)} emails, matched so far: {len(matched_emails)}")

        unique_senders = set(em.get('sender', '') for em in matched_emails)
        unique_sender_count = len(unique_senders)

        stats = {
            'query': {
                'product_model': product_model,
                'issue_description': issue_description,
                'keywords': issue_keywords,
                'date_range': {'since': since_date.isoformat() if since_date else None, 'before': before_date.isoformat() if before_date else None},
                'sources': source_map
            },
            'summary': {
                'total_candidates': len(all_emails),
                'total_analyzed': total_analyzed,
                'matched_count': len(matched_emails),
                'unique_customers': unique_sender_count,
                'analysis_time': datetime.now().isoformat()
            },
            'matched_emails': matched_emails
        }

        return stats

    def generate_stats(self, matched_emails):
        monthly_counts = Counter()
        intent_distribution = Counter()
        sentiment_distribution = Counter()
        customer_email_counts = Counter()

        for em in matched_emails:
            date_str = em.get('received_at', '')
            try:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00')) if date_str else datetime.now()
                month_key = dt.strftime('%Y-%m')
                monthly_counts[month_key] += 1
            except Exception:
                monthly_counts['unknown'] += 1

            intent_distribution[em.get('ai_intent', 'Unknown')] += 1
            sentiment_distribution[em.get('ai_sentiment', 'Unknown')] += 1
            sender = em.get('sender', 'Unknown')
            customer_email_counts[sender] += 1

        top_customers = customer_email_counts.most_common(20)

        return {
            'monthly_trend': dict(sorted(monthly_counts.items())),
            'intent_distribution': dict(intent_distribution),
            'sentiment_distribution': dict(sentiment_distribution),
            'top_customers': [{'email': c, 'count': n} for c, n in top_customers]
        }


class HTMLReportGenerator:
    @staticmethod
    def generate(stats, output_path='email_analysis_report.html'):
        query = stats.get('query', {})
        summary = stats.get('summary', {})
        matched = stats.get('matched_emails', [])
        analyzer = EmailAnalyzer()
        detailed_stats = analyzer.generate_stats(matched)

        monthly = detailed_stats['monthly_trend']
        intents = detailed_stats['intent_distribution']
        sentiments = detailed_stats['sentiment_distribution']
        top_customers = detailed_stats['top_customers']

        months_label = json.dumps(list(monthly.keys()), ensure_ascii=False)
        months_data = json.dumps(list(monthly.values()))

        intents_label = json.dumps(list(intents.keys()), ensure_ascii=False)
        intents_data = json.dumps(list(intents.values()))

        sentiments_label = json.dumps(list(sentiments.keys()), ensure_ascii=False)
        sentiments_data = json.dumps(list(sentiments.values()))

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        matched_rows = ''
        for i, em in enumerate(matched[:200], 1):
            sender = em.get('sender', 'N/A')
            subject = em.get('subject', 'N/A')[:80]
            date = em.get('received_at', 'N/A')[:19]
            conf = em.get('match_confidence', 0)
            reason = em.get('match_reason', '')[:100]
            details = em.get('issue_details', '')[:150]
            matched_rows += f'''<tr>
<td>{i}</td><td title="{sender}">{sender[:40]}</td>
<td title="{em.get('subject','')}">{subject}</td>
<td>{date}</td>
<td>{conf:.0%}</td>
<td title="{em.get('match_reason','')}">{reason}</td>
<td title="{em.get('issue_details','')}">{details}</td></tr>'''

        top_customer_rows = ''
        for c in top_customers[:15]:
            top_customer_rows += f'<tr><td>{c["email"][:50]}</td><td>{c["count"]}</td></tr>'

        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>MOOER Support Email Analysis Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background:#f5f5f5; color:#333; }}
.container {{ max-width:1400px; margin:0 auto; padding:20px; }}
.header {{ background:linear-gradient(135deg,#1a237e,#283593); color:white; padding:30px; border-radius:12px; margin-bottom:24px; }}
.header h1 {{ font-size:28px; margin-bottom:8px; }}
.header .meta {{ opacity:0.85; font-size:14px; }}
.stats-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; margin-bottom:24px; }}
.stat-card {{ background:white; border-radius:10px; padding:20px; box-shadow:0 2px 8px rgba(0,0,0,0.08); text-align:center; }}
.stat-card .number {{ font-size:36px; font-weight:700; color:#1a237e; }}
.stat-card .label {{ color:#666; font-size:14px; margin-top:4px; }}
.section {{ background:white; border-radius:10px; padding:24px; margin-bottom:24px; box-shadow:0 2px 8px rgba(0,0,0,0.08); }}
.section h2 {{ font-size:18px; margin-bottom:16px; color:#1a237e; border-bottom:2px solid #e8eaf6; padding-bottom:8px; }}
.chart-container {{ position:relative; height:300px; width:100%; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#e8eaf6; color:#1a237e; padding:10px 8px; text-align:left; font-weight:600; }}
td {{ padding:8px; border-bottom:1px solid #eee; }}
tr:hover td {{ background:#f5f5ff; }}
.tag {{ display:inline-block; padding:3px 10px; border-radius:12px; font-size:12px; font-weight:600; }}
.tag-high {{ background:#ffebee; color:#c62828; }}
.tag-medium {{ background:#fff3e0; color:#e65100; }}
.tag-low {{ background:#e8f5e9; color:#2e7d32; }}
.query-info {{ background:#e8eaf6; border-radius:8px; padding:16px; margin-bottom:16px; }}
.query-info .row {{ display:flex; flex-wrap:wrap; gap:16px; }}
.query-info .item {{ flex:1; min-width:200px; }}
.query-info .item label {{ font-weight:600; color:#1a237e; display:block; margin-bottom:4px; font-size:13px; }}
.query-info .item value {{ color:#333; }}
.footer {{ text-align:center; color:#999; font-size:12px; padding:20px; }}
</style>
</head>
<body>
<div class="container">
<div class="header">
<h1>MOOER Support Email Analysis Report</h1>
<div class="meta">Generated: {now} | Product: {query.get("product_model","N/A")} | Issue: {query.get("issue_description","N/A")}</div>
</div>

<div class="section">
<h2>Query Parameters</h2>
<div class="query-info">
<div class="row">
<div class="item"><label>Product Model</label><value>{query.get("product_model","N/A")}</value></div>
<div class="item"><label>Issue Description</label><value>{query.get("issue_description","N/A")}</value></div>
<div class="item"><label>Keywords</label><value>{", ".join(query.get("keywords",[]))}</value></div>
<div class="item"><label>Date Range</label><value>{query.get("date_range",{}).get("since","All") or "All"} ~ {query.get("date_range",{}).get("before","Now") or "Now"}</value></div>
</div>
<div class="row" style="margin-top:8px;">
<div class="item"><label>Data Sources</label><value>{json.dumps(query.get("sources",{}))}</value></div>
</div>
</div>
</div>

<div class="stats-grid">
<div class="stat-card"><div class="number">{summary.get("total_candidates",0)}</div><div class="label">Candidate Emails</div></div>
<div class="stat-card"><div class="number">{summary.get("total_analyzed",0)}</div><div class="label">AI Analyzed</div></div>
<div class="stat-card"><div class="number" style="color:#c62828">{summary.get("matched_count",0)}</div><div class="label">Matched Issues</div></div>
<div class="stat-card"><div class="number" style="color:#2e7d32">{summary.get("unique_customers",0)}</div><div class="label">Unique Customers</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px;">
<div class="section"><h2>Monthly Trend</h2><div class="chart-container"><canvas id="monthChart"></canvas></div></div>
<div class="section"><h2>Intent Distribution</h2><div class="chart-container"><canvas id="intentChart"></canvas></div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px;">
<div class="section"><h2>Sentiment Distribution</h2><div class="chart-container"><canvas id="sentimentChart"></canvas></div></div>
<div class="section"><h2>Top Customers (by report count)</h2>
<table><tr><th>Customer Email</th><th>Reports</th></tr>{top_customer_rows}</table>
</div>
</div>

<div class="section">
<h2>Matched Emails Detail ({len(matched)} results)</h2>
<div style="overflow-x:auto;">
<table>
<tr><th>#</th><th>Sender</th><th>Subject</th><th>Date</th><th>Confidence</th><th>AI Reason</th><th>Issue Details</th></tr>
{matched_rows}
</table>
</div>
</div>

<div class="footer">MOOER Audio Customer Support Analysis | Auto-generated by EmailAnalyzer</div>
</div>

<script>
new Chart(document.getElementById('monthChart'),{{type:'line',data:{{
labels:{months_label},datasets:[{{label:'Emails',data:{months_data},borderColor:'#1a237e',backgroundColor:'rgba(26,35,126,0.1)',fill:true,tension:0.3}}]
}},options:{{responsive:true,maintainAspectRatio:false}}}});

new Chart(document.getElementById('intentChart'),{{type:'doughnut',data:{{
labels:{intents_label},datasets:[{{data:{intents_data},backgroundColor:['#1a237e','#3949ab','#5c6bc0','#7986cb','#9fa8da','#c5cae9']}}]
}},options:{{responsive:true,maintainAspectRatio:false}}}});

new Chart(document.getElementById('sentimentChart'),{{type:'pie',data:{{
labels:{sentiments_label},datasets:[{{data:{sentiments_data},backgroundColor:['#2e7d32','#fbc02d','#c62828','#757575']}}]
}},options:{{responsive:true,maintainAspectRatio:false}}}});
</script>
</body>
</html>'''

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        return output_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description='MOOER Support Email Issue Analyzer')
    parser.add_argument('--product', '-p', required=True, help='Product model (e.g., GS1000)')
    parser.add_argument('--issue', '-i', required=True, help='Issue description (e.g., balance output problem after update)')
    parser.add_argument('--keywords', '-k', nargs='+', help='Additional keywords to search')
    parser.add_argument('--since', '-s', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--until', '-u', help='End date (YYYY-MM-DD)')
    parser.add_argument('--output', '-o', default='email_analysis_report.html', help='Output HTML file path')
    parser.add_argument('--max-emails', '-m', type=int, default=500, help='Max emails to analyze')
    parser.add_argument('--no-imap', action='store_true', help='Skip IMAP search (DB only)')
    parser.add_argument('--no-db', action='store_true', help='Skip DB search (IMAP only)')
    args = parser.parse_args()

    since = datetime.strptime(args.since, '%Y-%m-%d') if args.since else None
    before = datetime.strptime(args.until, '%Y-%m-%d') if args.until else None

    analyzer = EmailAnalyzer()
    print(f"\n{'='*60}")
    print(f"MOOER Support Email Issue Analyzer")
    print(f"{'='*60}")
    print(f"Product:     {args.product}")
    print(f"Issue:       {args.issue}")
    print(f"Keywords:    {args.keywords or 'auto'}")
    print(f"Date Range:  {since or 'All'} ~ {before or 'Now'}")
    print(f"Sources:     {'IMAP+DB'}")
    print(f"{'='*60}\n")

    stats = analyzer.query_issues(
        product_model=args.product,
        issue_description=args.issue,
        issue_keywords=args.keywords,
        date_range=(since, before) if since or before else None,
        use_imap=not args.no_imap,
        use_db=not args.no_db,
        max_emails=args.max_emails
    )

    summary = stats['summary']
    print(f"\nResults Summary:")
    print(f"  Candidate Emails:   {summary['total_candidates']}")
    print(f"  AI Analyzed:        {summary['total_analyzed']}")
    print(f"  Matched Issues:     {summary['matched_count']}")
    print(f"  Unique Customers:   {summary['unique_customers']}")

    output_file = HTMLReportGenerator.generate(stats, args.output)
    print(f"\nReport generated: {os.path.abspath(output_file)}")


if __name__ == '__main__':
    main()
