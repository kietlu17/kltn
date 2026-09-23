"""Fetch and chunk allow-listed public help-center articles."""
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

ALLOWED_HOSTS = {"help.shopee.vn"}
DEFAULT_POLICY_URL = "https://help.shopee.vn/portal/4/article/77244"


def extract_article(html, source_url):
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.find("h2")
    content = soup.select_one("div.tiny-editor-preview")
    if not title_node or not content:
        raise ValueError("Shopee Help article structure was not recognized")
    for node in content.select("script, style, button"):
        node.decompose()
    title = re.sub(r"\s+", " ", title_node.get_text(" ", strip=True))
    paragraphs = []
    for node in content.find_all(["p", "li"]):
        if node.name == "li" and node.find("p"):
            continue
        paragraph = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        if paragraph:
            paragraphs.append(paragraph)
    text = "\n".join(paragraphs)
    if len(text) < 200:
        raise ValueError("Shopee Help article content is unexpectedly short")

    return {
        "articleId": source_url.rstrip("/").rsplit("/", 1)[-1],
        "title": title,
        "paragraphs": paragraphs,
        "sourceUrl": source_url,
        "crawledAt": datetime.now(timezone.utc).isoformat(),
        "hash": hashlib.sha256(text.encode()).hexdigest(),
    }


def parse_article(html, source_url, *, chunk_size=1400, overlap=180):
    article = extract_article(html, source_url)
    paragraphs = article["paragraphs"]

    units = []
    for paragraph in paragraphs:
        while len(paragraph) > chunk_size:
            boundary = max(
                paragraph.rfind(". ", 0, chunk_size),
                paragraph.rfind("; ", 0, chunk_size),
                paragraph.rfind(" ", 0, chunk_size),
            )
            boundary = boundary + 1 if boundary > chunk_size // 2 else chunk_size
            units.append(paragraph[:boundary].strip())
            paragraph = paragraph[boundary:].strip()
        if paragraph:
            units.append(paragraph)

    chunks, current, index = [], [], 0
    minimum_chunk_size = min(200, chunk_size // 2)
    for unit in units:
        current_size = len("\n".join(current))
        if current and current_size >= minimum_chunk_size and current_size + len(unit) + 1 > chunk_size:
            body = "\n".join(current)
            chunks.append({
                "index": index,
                "articleId": article["articleId"],
                "title": article["title"],
                "text": body,
                "sourceUrl": article["sourceUrl"],
                "crawledAt": article["crawledAt"],
                "hash": hashlib.sha256(body.encode()).hexdigest(),
            })
            index += 1
            retained, retained_size = [], 0
            for previous in reversed(current):
                if retained_size + len(previous) > overlap:
                    break
                retained.insert(0, previous)
                retained_size += len(previous)
            current = retained
        current.append(unit)
    if current:
        body = "\n".join(current)
        chunks.append({
            "index": index,
            "articleId": article["articleId"],
            "title": article["title"],
            "text": body,
            "sourceUrl": article["sourceUrl"],
            "crawledAt": article["crawledAt"],
            "hash": hashlib.sha256(body.encode()).hexdigest(),
        })
    return chunks


async def fetch_article(source_url):
    article = await fetch_article_document(source_url)
    return parse_article(article["html"], source_url)


async def fetch_article_document(source_url):
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("Policy source host is not allow-listed")
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        response = await client.get(source_url, headers={
            "User-Agent": "EcommercePolicyIndexer/1.0 (+customer-service-rag)"
        })
        response.raise_for_status()
    return {**extract_article(response.text, source_url), "html": response.text}
