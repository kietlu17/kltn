"""Extract basic RAG chunks from local policy PDF files."""
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from pypdf import PdfReader


def load_policy_pdf(path, *, chunk_size=1400, overlap=180):
    pdf_path = Path(path).resolve()
    if not pdf_path.is_file() or pdf_path.suffix.casefold() != ".pdf":
        raise ValueError(f"Policy PDF not found: {pdf_path}")
    reader = PdfReader(str(pdf_path))
    if not reader.pages:
        raise ValueError(f"Policy PDF has no pages: {pdf_path}")
    title = str((reader.metadata or {}).get("/Title") or pdf_path.stem)
    pages = [page.extract_text() or "" for page in reader.pages]
    all_text = "\n".join(pages)
    source_match = re.search(r"Nguồn chính thức:\s*(https://\S+)", all_text)
    source_url = source_match.group(1).rstrip(".,)") if source_match else pdf_path.as_uri()
    category_match = re.search(r"^Nhóm:\s*(.+)$", all_text, re.MULTILINE)
    subcategory_match = re.search(r"^Danh mục:\s*(.+)$", all_text, re.MULTILINE)
    article_id = urlparse(source_url).path.rstrip("/").rsplit("/", 1)[-1] or pdf_path.stem
    indexed_at = datetime.now(timezone.utc).isoformat()
    chunks, index = [], 0
    for page_number, raw_text in enumerate(pages, 1):
        lines = []
        for line in raw_text.splitlines():
            line = re.sub(r"\s+", " ", line).strip()
            if not line or re.fullmatch(r"Trang \d+", line) or line.startswith("Nguồn: help.shopee.vn"):
                continue
            if line.startswith((
                "Bản lưu cục bộ", "Nguồn chính thức:", "Thời điểm thu thập",
                "SHA-256 nội dung:", "Nhóm:", "Danh mục:",
            )):
                continue
            lines.append(line)
        text = "\n".join(lines)
        start = 0
        while start < len(text):
            end = min(len(text), start + chunk_size)
            if end < len(text):
                boundary = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
                if boundary > start + chunk_size // 2:
                    end = boundary + 1
            body = text[start:end].strip()
            if body:
                chunks.append({
                    "index": index,
                    "articleId": article_id,
                    "title": title,
                    "text": body,
                    "sourceUrl": source_url,
                    "localPath": str(pdf_path),
                    "page": page_number,
                    "category": category_match.group(1).strip() if category_match else "",
                    "subcategory": subcategory_match.group(1).strip() if subcategory_match else "",
                    "crawledAt": indexed_at,
                    "hash": hashlib.sha256(body.encode()).hexdigest(),
                })
                index += 1
            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
            while start < end and start > 0 and not text[start - 1].isspace():
                start += 1
    if not chunks:
        raise ValueError(f"No extractable policy text in PDF: {pdf_path}")
    return chunks
