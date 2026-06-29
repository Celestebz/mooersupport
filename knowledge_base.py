import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from database import DatabaseHandler


KNOWLEDGE_TYPES = [
    "product_manual",
    "product_page_download",
    "firmware_software_download",
    "support_policy",
    "business_data",
    "issue_solution",
]

MANUAL_TEXT_PIPELINE = "manual_text_decode_v2"


def _rel(path, root):
    try:
        return str(Path(path).resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def _checksum(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()
    except Exception:
        return ""


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def _fix_manual_text(text):
    try:
        from pdf_reader import _detect_and_fix_caesar_cipher
        return _detect_and_fix_caesar_cipher(text)
    except Exception:
        return text


def _chunks(text, knowledge_type, product_model="", chunk_type="text", size=3500):
    clean = (text or "").strip()
    if not clean:
        return []

    parts = []
    current = []
    current_len = 0
    for paragraph in re.split(r"\n\s*\n", clean):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and current_len + len(paragraph) > size:
            parts.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(paragraph)
        current_len += len(paragraph)
    if current:
        parts.append("\n\n".join(current))

    return [
        {
            "knowledge_type": knowledge_type,
            "product_model": product_model,
            "chunk_type": chunk_type,
            "section_title": f"{chunk_type} {i:03d}",
            "content": part,
            "status": "active",
            "metadata": {"chunk_index": i},
        }
        for i, part in enumerate(parts, 1)
    ]


def _guess_product_model(filename):
    stem = Path(filename).stem
    value = stem.replace("_", " ").replace("&", " & ")
    value = re.sub(r"\b(manual|manul|owner'?s|en|cn|v\d+|pdf)\b.*$", "", value, flags=re.I)
    value = re.sub(r"\d{8,}|\d{4}\.\d{2}\.\d{2}|\d{6}", "", value)
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"\s+", " ", value).strip(" -_")
    return value or stem


def _template_knowledge_type(category, body):
    text = f"{category or ''}\n{body or ''}".lower()
    if "companyfile/downloads-1" in text or "firmware" in text or "driver" in text or "software" in text:
        return "firmware_software_download"
    if "owner's manual" in text or "product page" in text:
        return "product_page_download"
    if category in {"Repair/Warranty", "Amazon Purchase Issues", "Registration Unbinding"}:
        return "support_policy"
    if category == "Parts/Accessories Purchase":
        return "business_data"
    return "issue_solution"


class KnowledgeBaseSync:
    """Synchronize existing scattered support knowledge into the structured KB index."""

    def __init__(self, root_dir=None, db_path="mooer_support.db"):
        self.root_dir = Path(root_dir or os.getcwd()).resolve()
        self.db = DatabaseHandler(db_path=str(self.root_dir / db_path) if not Path(db_path).is_absolute() else db_path)
        self.counts = {"documents": 0, "chunks": 0, "skipped": 0}

    def _is_current(self, document):
        checksum = document.get("checksum") or ""
        version = document.get("version") or ""
        if not (checksum or version):
            return False
        try:
            conn = self.db._connect()
            conn.row_factory = sqlite3.Row
            row = conn.execute('''
                SELECT d.checksum, d.version,
                       (SELECT count(*) FROM knowledge_chunks c WHERE c.document_id = d.id) AS chunk_count
                FROM knowledge_documents d
                WHERE d.source_key = ?
            ''', (document.get("source_key") or "",)).fetchone()
            conn.close()
            if not row:
                return False
            return (
                (row["checksum"] or "") == checksum
                and (row["version"] or "") == version
                and int(row["chunk_count"] or 0) > 0
            )
        except Exception:
            return False

    def _upsert(self, document, chunks=None):
        if self._is_current(document):
            self.counts["skipped"] += 1
            return
        doc_id = self.db.upsert_knowledge_document(document)
        if doc_id is None:
            return
        chunks = chunks or []
        self.db.replace_knowledge_chunks(doc_id, chunks)
        self.counts["documents"] += 1
        self.counts["chunks"] += len(chunks)

    def sync_all(self):
        self.counts = {"documents": 0, "chunks": 0, "skipped": 0}
        self.sync_manuals()
        self.sync_download_rules()
        self.sync_policy_files()
        self.sync_reply_templates()
        self.sync_part_prices()
        self.sync_support_issues()
        return {
            "ok": True,
            "synced_at": datetime.now().isoformat(),
            **self.counts,
            "summary": self.db.get_knowledge_summary(),
        }

    def sync_manuals(self):
        manuals_dir = self.root_dir / "MOOER产品说明书"
        cache_dir = self.root_dir / "manuals_cache"
        index_path = cache_dir / "index.json"
        cache_index = {}
        if index_path.exists():
            try:
                cache_index = json.loads(_read_text(index_path))
            except Exception:
                cache_index = {}
        if not manuals_dir.exists():
            return

        for pdf_path in sorted(manuals_dir.glob("*.pdf")):
            product_model = _guess_product_model(pdf_path.name)
            cache_file = ""
            if pdf_path.name in cache_index:
                cache_file = cache_index[pdf_path.name].get("cache_file") or ""
            cache_path = cache_dir / cache_file if cache_file else None
            text = _read_text(cache_path) if cache_path and cache_path.exists() else ""
            text = _fix_manual_text(text)
            cache_checksum = _checksum(cache_path) if cache_path and cache_path.exists() else ""
            cache_mtime = str(int(cache_path.stat().st_mtime)) if cache_path and cache_path.exists() else ""
            source_path = _rel(pdf_path, self.root_dir)
            artifact_path = _rel(cache_path, self.root_dir) if cache_path and cache_path.exists() else ""
            document = {
                "source_key": f"manual:{pdf_path.name}",
                "knowledge_type": "product_manual",
                "source_kind": "manual_pdf",
                "title": f"Owner's manual - {product_model}",
                "product_model": product_model,
                "source_path": source_path,
                "artifact_path": artifact_path,
                "version": f"{int(pdf_path.stat().st_mtime)}:{cache_mtime}:{MANUAL_TEXT_PIPELINE}",
                "checksum": f"{_checksum(pdf_path)}:{cache_checksum}:{MANUAL_TEXT_PIPELINE}",
                "status": "active",
                "metadata": {"filename": pdf_path.name, "cache_file": cache_file, "pipeline": MANUAL_TEXT_PIPELINE},
            }
            self._upsert(document, _chunks(text, "product_manual", product_model, "manual_text"))

    def sync_download_rules(self):
        product_page_content = (
            "Owner's manuals are downloaded from each product's own page on the MOOER official website. "
            "Open the product page and use the Download section on that product page. "
            "Do not use https://www.mooeraudio.com/pages/download as a direct owner's manual link. "
            "If the exact product-page URL is not available, provide navigation steps instead of inventing a URL."
        )
        self._upsert(
            {
                "source_key": "rule:product_page_download:owners_manual",
                "knowledge_type": "product_page_download",
                "source_kind": "official_download_rule",
                "title": "Owner's manual download location rule",
                "source_url": "https://www.mooeraudio.com",
                "status": "active",
                "metadata": {"scope": "manual_download"},
            },
            _chunks(product_page_content, "product_page_download", chunk_type="download_rule"),
        )

        firmware_content = (
            "Firmware files, editors, drivers, and software installation packages are downloaded from "
            "https://www.mooeraudio.com/companyfile/Downloads-1. Always distinguish firmware/software "
            "downloads from owner's manuals, and ask the customer to choose the package for the exact product model."
        )
        self._upsert(
            {
                "source_key": "rule:firmware_software_download:official_page",
                "knowledge_type": "firmware_software_download",
                "source_kind": "official_download_rule",
                "title": "Firmware, editor, driver, and software download rule",
                "source_url": "https://www.mooeraudio.com/companyfile/Downloads-1",
                "status": "active",
                "metadata": {"scope": "firmware_software_download"},
            },
            _chunks(firmware_content, "firmware_software_download", chunk_type="download_rule"),
        )

    def sync_policy_files(self):
        files = [
            ("warranty_policy.txt", "support_policy", "policy_file", "MOOER warranty and repair policy"),
            ("distributor_info.txt", "business_data", "distributor_file", "MOOER distributor list"),
        ]
        for filename, knowledge_type, source_kind, title in files:
            path = self.root_dir / filename
            if not path.exists():
                continue
            text = _read_text(path)
            self._upsert(
                {
                    "source_key": f"file:{filename}",
                    "knowledge_type": knowledge_type,
                    "source_kind": source_kind,
                    "title": title,
                    "source_path": _rel(path, self.root_dir),
                    "version": str(int(path.stat().st_mtime)),
                    "checksum": _checksum(path),
                    "status": "active",
                    "metadata": {"filename": filename},
                },
                _chunks(text, knowledge_type, chunk_type=source_kind),
            )

    def sync_reply_templates(self):
        conn = self.db._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM reply_templates ORDER BY id").fetchall()
        conn.close()
        for row in rows:
            body = row["body"] or ""
            knowledge_type = _template_knowledge_type(row["category"], body)
            status = "active" if (row["status"] or "active") == "active" else "archived"
            title = row["name"] or f"Reply template #{row['id']}"
            product_model = row["product_model"] or ""
            self._upsert(
                {
                    "source_key": f"reply_template:{row['id']}",
                    "knowledge_type": knowledge_type,
                    "source_kind": "reply_template",
                    "title": title,
                    "product_model": product_model,
                    "source_table": "reply_templates",
                    "source_id": row["id"],
                    "status": status,
                    "version": str(row["updated_at"] or ""),
                    "metadata": {
                        "category": row["category"],
                        "issue_category": row["issue_category"],
                        "language": row["language"],
                    },
                },
                _chunks(body, knowledge_type, product_model, "reply_template"),
            )

    def sync_part_prices(self):
        rows = self.db.list_all_part_prices()
        if not rows:
            return
        lines = []
        for row in rows:
            lines.append(
                f"{row['product_model']} - {row['part_name']}: {row['price']} {row.get('currency') or 'USD'}"
            )
        self._upsert(
            {
                "source_key": "table:part_prices",
                "knowledge_type": "business_data",
                "source_kind": "part_price_table",
                "title": "Official part price table",
                "source_table": "part_prices",
                "status": "active",
                "metadata": {"row_count": len(rows)},
            },
            [
                {
                    "knowledge_type": "business_data",
                    "product_model": row["product_model"],
                    "chunk_type": "part_price",
                    "section_title": f"{row['product_model']} - {row['part_name']}",
                    "content": f"{row['part_name']} for {row['product_model']}: {row['price']} {row.get('currency') or 'USD'}",
                    "keywords": row["part_name"],
                    "status": "active",
                    "metadata": {"price_id": row["id"]},
                }
                for row in rows
            ],
        )

    def sync_support_issues(self):
        conn = self.db._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM support_issues ORDER BY id").fetchall()
        conn.close()
        for row in rows:
            solution = row["solution_summary"] or ""
            template = row["final_reply_template"] or ""
            content = "\n\n".join(
                part for part in [
                    f"Issue: {row['issue_title'] or ''}",
                    f"Category: {row['issue_category'] or ''}",
                    f"Status: {row['status'] or ''}; R&D status: {row['rnd_status'] or ''}",
                    f"Solution summary:\n{solution}" if solution else "",
                    f"Final reply template:\n{template}" if template else "",
                ]
                if part
            )
            status = "active" if (solution or template) else "draft"
            self._upsert(
                {
                    "source_key": f"support_issue:{row['id']}",
                    "knowledge_type": "issue_solution",
                    "source_kind": "support_issue",
                    "title": row["issue_title"] or f"Support issue #{row['id']}",
                    "product_model": row["product_model"] or "",
                    "source_table": "support_issues",
                    "source_id": row["id"],
                    "status": status,
                    "version": str(row["updated_at"] or ""),
                    "metadata": {
                        "issue_category": row["issue_category"],
                        "issue_signature": row["issue_signature"],
                        "user_count": row["user_count"],
                        "email_count": row["email_count"],
                        "rnd_status": row["rnd_status"],
                    },
                },
                _chunks(content, "issue_solution", row["product_model"] or "", "support_issue"),
            )
