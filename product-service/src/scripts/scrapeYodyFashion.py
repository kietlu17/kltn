"""Collect attributed YODY fashion catalog records from its public product sitemap.

Requires requests and beautifulsoup4. Records are append-only JSONL so an
interrupted crawl can resume without downloading already accepted products.
"""

import argparse
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup


SITEMAP = "https://yody.vn/sitemap_products_1.xml"
FASHION_WORDS = ("áo", "quần", "váy", "đầm", "đồ bộ", "đồ ngủ", "trang phục", "jeans")
HEADERS = {"User-Agent": "EcommerceCatalogResearch/1.0 (+public product sitemap)", "Accept": "text/html,application/xml"}


def sitemap_urls():
    response = requests.get(SITEMAP, headers=HEADERS, timeout=20)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    products = []
    for item in root:
        fields = {node.tag.rsplit("}", 1)[-1]: node.text for node in item}
        url = fields.get("loc") or ""
        if url.startswith("https://yody.vn/product/"):
            products.append((fields.get("lastmod") or "", url))
    products.sort(reverse=True)
    return list(dict.fromkeys(url for _, url in products))


def product_data(page):
    match = re.search(r'self\.PDPData\s*=\s*("(?:\\.|[^"\\])*")', page)
    return json.loads(json.loads(match.group(1))) if match else None


def extract_record(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = product_data(response.text)
        if not data or not data.get("status"):
            return None
        name = str(data.get("name") or "").strip()
        category = str((data.get("category") or {}).get("name") or "").strip()
        if not name or not any(word in f"{name} {category}".lower() for word in FASHION_WORDS):
            return None
        source_description = BeautifulSoup(data.get("description") or "", "html.parser").get_text(" ", strip=True)
        source_description = re.sub(r"\s+", " ", html.unescape(source_description)).strip()
        source_description = source_description.split("Thông tin về chất lượng sản phẩm", 1)[0].strip()
        if len(source_description) < 80:
            return None
        variants = []
        seen = set()
        for item in data.get("variants") or []:
            price = item.get("sale_price")
            if not item.get("status") or not isinstance(price, (int, float)) or price <= 0:
                continue
            sku = str(item.get("sku") or item.get("id") or "")
            if not sku or sku in seen:
                continue
            seen.add(sku)
            color = str((item.get("color") or {}).get("name") or "").strip()
            size = str((item.get("size") or {}).get("name") or "").strip()
            images = [image.get("image_url") for image in item.get("images") or [] if image.get("image_url")]
            variants.append({
                "name": " / ".join(part for part in (color, size) if part) or sku,
                "sku": sku[:100],
                "imageUrl": images[0] if images else "",
                "originalPrice": max(price, item.get("original_price") or price),
                "price": price,
                "quantity": max(0, int(item.get("inventory") or 0)) if item.get("in_stock") else 0,
            })
        if not variants:
            return None
        images = list(dict.fromkeys(variant["imageUrl"] for variant in variants if variant["imageUrl"]))[:6]
        if not images:
            return None
        prices = [variant["price"] for variant in variants]
        return {
            "sourceId": str(data["id"]),
            "sourceUrl": url,
            "name": name,
            "categoryName": category,
            "description": source_description[:650],
            "sourceDetail": source_description[:2200],
            "images": images,
            "price": min(prices),
            "originalPrice": min(variant["originalPrice"] for variant in variants),
            "quantity": sum(variant["quantity"] for variant in variants),
            "variants": variants[:40],
        }
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output/catalog/yody-fashion.jsonl"))
    parser.add_argument("--target", type=int, default=1000)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if args.output.exists():
        existing = [json.loads(line) for line in args.output.read_text(encoding="utf-8").splitlines() if line.strip()]
    seen_ids = {record["sourceId"] for record in existing}
    seen_urls = {record["sourceUrl"] for record in existing}
    urls = [url for url in sitemap_urls() if url not in seen_urls]
    print(f"Sitemap: {len(urls)} product URLs; existing: {len(existing)}; target: {args.target}", flush=True)
    attempted = 0
    with ThreadPoolExecutor(max_workers=4) as pool, args.output.open("a", encoding="utf-8") as output:
        for offset in range(0, len(urls), 32):
            if len(seen_ids) >= args.target:
                break
            batch = urls[offset:offset + 32]
            for record in pool.map(extract_record, batch):
                attempted += 1
                if len(seen_ids) >= args.target:
                    break
                if not record or record["sourceId"] in seen_ids:
                    continue
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                seen_ids.add(record["sourceId"])
                if len(seen_ids) % 100 == 0:
                    print(f"Collected {len(seen_ids)}; checked {attempted}", flush=True)
            time.sleep(0.4)
    print(f"Collected {len(seen_ids)} unique products; checked {attempted}", flush=True)
    if len(seen_ids) < args.target:
        raise SystemExit(f"Only {len(seen_ids)} eligible products found")


if __name__ == "__main__":
    main()
