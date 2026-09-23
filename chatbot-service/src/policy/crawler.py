"""Download the public Shopee Help buyer portal into one local PDF per article."""
import argparse
import asyncio
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from .pdf import build_policy_pdf


PORTAL_ID = 4
PORTAL_ORIGIN = "https://help.shopee.vn"
API_BASE = f"{PORTAL_ORIGIN}/api/inhouse/hc/mobile/v1"
ARTICLE_URL = f"{PORTAL_ORIGIN}/portal/{PORTAL_ID}/article/{{article_id}}"
# This public article belongs to category 654 but is currently absent from the
# category-list response, so keep it as an explicit discovery seed.
REQUIRED_ARTICLE_IDS = (77244,)


def _slug(value):
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")[:80] or "article"


def _content_to_paragraphs(content):
    soup = BeautifulSoup(content or "", "html.parser")
    for node in soup.select("script, style, button"):
        node.decompose()
    paragraphs = []
    for node in soup.find_all(["p", "li", "tr"]):
        if node.name == "li" and node.find("p"):
            continue
        separator = " | " if node.name == "tr" else " "
        text = re.sub(r"\s+", " ", node.get_text(separator, strip=True)).strip()
        if text and (not paragraphs or paragraphs[-1] != text):
            paragraphs.append(text)
    if not paragraphs:
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
        if text:
            paragraphs.append(text)
    if not paragraphs:
        image_urls = [node.get("src", "").strip() for node in soup.find_all("img")]
        paragraphs.extend(
            f"Nội dung bài viết là hình ảnh tại: {url}" for url in image_urls if url
        )
    return paragraphs


class ShopeeHelpPortal:
    def __init__(self, concurrency=8):
        self.semaphore = asyncio.Semaphore(max(1, concurrency))
        self.client = httpx.AsyncClient(
            base_url=API_BASE,
            follow_redirects=True,
            timeout=45,
            limits=httpx.Limits(max_connections=max(4, concurrency)),
            headers={
                "Accept": "application/json",
                "User-Agent": "EcommercePolicyCrawler/1.0 (+customer-service-rag)",
                "frontend-id": str(PORTAL_ID),
            },
        )

    async def close(self):
        await self.client.aclose()

    async def _get(self, path, params):
        async with self.semaphore:
            for attempt in range(4):
                try:
                    response = await self.client.get(path, params=params)
                    response.raise_for_status()
                    return response.json()
                except (httpx.HTTPError, ValueError):
                    if attempt == 3:
                        raise
                    await asyncio.sleep(1.5 * (attempt + 1))

    async def discover(self):
        tree = (await self._get("/categories", {"frontend_id": PORTAL_ID})).get("dir_info") or []
        discovered = {}
        for category in tree:
            for subcategory in category.get("sub_dir_info") or []:
                page = 1
                while True:
                    data = await self._get("/categories/articles", {
                        "frontend_id": PORTAL_ID,
                        "category_id": subcategory["id"],
                        "page": page,
                        "size": 100,
                    })
                    articles = data.get("articles") or []
                    for item in articles:
                        discovered[item["id"]] = {
                            "id": item["id"],
                            "title": item.get("title") or str(item["id"]),
                            "category": category["category_name"],
                            "categoryId": category["id"],
                            "subcategory": subcategory["category_name"],
                            "subcategoryId": subcategory["id"],
                        }
                    if page * 100 >= int(data.get("total") or 0):
                        break
                    page += 1
        for article_id in REQUIRED_ARTICLE_IDS:
            discovered.setdefault(article_id, {"id": article_id})
        return tree, list(discovered.values())

    async def fetch_article(self, item):
        payload = await self._get("/article", {
            "frontend_id": PORTAL_ID,
            "id": item["id"],
        })
        full_category = payload.get("full_category_info") or {}
        subcategory = full_category.get("sub_category") or payload.get("category_info") or {}
        paragraphs = _content_to_paragraphs(payload.get("content"))
        if not paragraphs:
            raise ValueError(f"Article {item['id']} has no extractable content")
        text = "\n".join(paragraphs)
        return {
            "articleId": str(item["id"]),
            "title": payload.get("title") or item.get("title") or str(item["id"]),
            "paragraphs": paragraphs,
            "sourceUrl": ARTICLE_URL.format(article_id=item["id"]),
            "crawledAt": datetime.now(timezone.utc).isoformat(),
            "hash": hashlib.sha256(text.encode()).hexdigest(),
            "category": item.get("category") or full_category.get("name") or "",
            "categoryId": item.get("categoryId") or full_category.get("category_id"),
            "subcategory": item.get("subcategory") or subcategory.get("name") or "",
            "subcategoryId": item.get("subcategoryId") or subcategory.get("category_id"),
        }


def _article_output_path(output_dir, article):
    category = f'{article.get("categoryId") or 0}-{_slug(article.get("category") or "uncategorized")}'
    subcategory = f'{article.get("subcategoryId") or 0}-{_slug(article.get("subcategory") or "uncategorized")}'
    filename = f'{article["articleId"]}-{_slug(article["title"])}.pdf'
    return Path(output_dir) / category / subcategory / filename


async def crawl_portal(output_dir, concurrency=8):
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    portal = ShopeeHelpPortal(concurrency=concurrency)
    failures, records = [], []
    try:
        tree, discovered = await portal.discover()

        async def fetch(item):
            try:
                return await portal.fetch_article(item), None
            except Exception as error:
                return None, {"articleId": item["id"], "error": str(error)}

        tasks = [asyncio.create_task(fetch(item)) for item in discovered]
        for completed in asyncio.as_completed(tasks):
            article, failure = await completed
            if failure:
                failures.append(failure)
                continue
            pdf_path = _article_output_path(output, article)
            build_policy_pdf(article, pdf_path)
            records.append({
                "articleId": article["articleId"],
                "title": article["title"],
                "category": article["category"],
                "subcategory": article["subcategory"],
                "sourceUrl": article["sourceUrl"],
                "pdf": str(pdf_path.relative_to(output)).replace("\\", "/"),
                "hash": article["hash"],
            })
    finally:
        await portal.close()
    records.sort(key=lambda item: int(item["articleId"]))
    manifest = {
        "source": f"{PORTAL_ORIGIN}/portal/{PORTAL_ID}",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "categoryCount": len(tree),
        "subcategoryCount": sum(len(item.get("sub_dir_info") or []) for item in tree),
        "articleCount": len(records),
        "failureCount": len(failures),
        "articles": records,
        "failures": failures,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        raise RuntimeError(f"Shopee Help crawl incomplete: {len(failures)} failures; see {manifest_path}")
    return manifest_path, manifest


def main():
    repository = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(repository / "output" / "pdf" / "shopee-help"))
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    path, manifest = asyncio.run(crawl_portal(args.output_dir, args.concurrency))
    print(f"PDFs={manifest['articleCount']} categories={manifest['categoryCount']} manifest={path}")


if __name__ == "__main__":
    main()
