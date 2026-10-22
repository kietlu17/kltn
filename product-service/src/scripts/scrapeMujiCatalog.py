"""Collect MUJI Vietnam products and select a catalog balanced across departments.

Requires requests and beautifulsoup4. The candidate file is append-only so a
failed crawl can resume. The selected JSONL file contains exactly --target rows.
"""

import argparse
import html
import json
import re
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup, SoupStrainer


SITEMAP = "https://boservices.muji.com.vn/media/sitemap/sitemap_vn.xml"
HEADERS = {"User-Agent": "EcommerceCatalogResearch/1.0 (+public product sitemap)", "Accept": "text/html,application/xml"}
RSC_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,("(?:\\.|[^"\\])*")\]\)')
DEPARTMENT_IDS = {
    "Thực phẩm": 44,
    "Làm đẹp": 228,
    "Văn phòng phẩm": 49,
    "Du lịch": 50,
    "Quần áo": 6,
    "Nhà cửa": 43,
}
DEPARTMENT_ORDER = list(DEPARTMENT_IDS)


def sitemap_urls():
    response = requests.get(SITEMAP, headers=HEADERS, timeout=30)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    urls = []
    for item in root:
        location = next((node.text for node in item if node.tag.endswith("loc")), None)
        if location and location.startswith("https://www.muji.com.vn/vn/product/"):
            urls.append(location)
    return list(dict.fromkeys(urls))


def embedded_product(page):
    for match in RSC_CHUNK.finditer(page):
        try:
            chunk = json.loads(match.group(1))
            marker = chunk.find('"product":')
            if marker >= 0:
                product = json.JSONDecoder().raw_decode(chunk[marker + len('"product":'):])[0]
                if product.get("sku") and product.get("price_range"):
                    return product
        except (ValueError, TypeError):
            continue
    return None


def category_info(product):
    paths = [category.get("breadcrumbs") or [] for category in product.get("categories") or []]
    paths = [path for path in paths if path]
    if not paths:
        return None
    for department, category_id in DEPARTMENT_IDS.items():
        matching = [path for path in paths if category_id in {item.get("category_id") for item in path}]
        if matching:
            path = max(matching, key=len)
            names = [str(item.get("category_name") or "").strip() for item in path]
            return department, " › ".join(name for name in names if name)
    return None


def price_pair(product):
    minimum = ((product.get("price_range") or {}).get("minimum_price") or {})
    price = (minimum.get("final_price") or {}).get("value")
    original = (minimum.get("regular_price") or {}).get("value")
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    return int(price), int(max(price, original or price))


def image_urls(product):
    values = [((product.get("image") or {}).get("url"))]
    values.extend(image.get("url") for image in product.get("media_gallery") or []
                  if not image.get("disabled"))
    return list(dict.fromkeys(value for value in values
                              if value and value.startswith("https://")
                              and "/placeholder/" not in value.lower()))[:6]


def source_quantity(product):
    stock = product.get("advanced_stock") or {}
    quantity = stock.get("qty")
    if product.get("stock_status") != "IN_STOCK" or not stock.get("manage_stock"):
        return 0
    return max(0, int(quantity or 0))


def extract_record(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        product = embedded_product(response.text)
        if not product:
            return None
        category = category_info(product)
        if not category:
            return None
        department, category_path = category
        soup = BeautifulSoup(response.text, "html.parser", parse_only=SoupStrainer(attrs={"role": "tabpanel"}))
        panel = soup.find(attrs={"role": "tabpanel", "data-state": "active"})
        description = re.sub(r"\s+", " ", html.unescape(panel.get_text(" ", strip=True) if panel else "")).strip()
        if len(description) < 80:
            return None
        parent_images = image_urls(product)
        if not parent_images:
            return None
        variants = []
        source_variants = product.get("variants") or []
        if source_variants:
            for variant in source_variants:
                item = variant.get("product") or {}
                pair = price_pair(item)
                sku = str(item.get("sku") or "")
                if not pair or not sku:
                    continue
                labels = [str(attribute.get("label") or "").strip()
                          for attribute in variant.get("attributes") or []]
                images = image_urls(item)
                variants.append({"name": " / ".join(label for label in labels if label) or sku,
                                 "sku": sku[:100], "imageUrl": (images or parent_images)[0],
                                 "price": pair[0], "originalPrice": pair[1],
                                 "quantity": source_quantity(item)})
                if len(variants) >= 40:
                    break
        else:
            pair = price_pair(product)
            if pair:
                variants.append({"name": "Mặc định", "sku": str(product["sku"])[:100],
                                 "imageUrl": parent_images[0], "price": pair[0],
                                 "originalPrice": pair[1], "quantity": source_quantity(product)})
        if not variants:
            return None
        return {
            "sourceId": str(product["id"]), "sourceSku": str(product["sku"]), "sourceUrl": url,
            "name": str(product["name"]).strip(), "department": department,
            "categoryPath": category_path, "description": description[:650],
            "sourceDetail": description[:2200], "images": parent_images,
            "price": min(variant["price"] for variant in variants),
            "originalPrice": min(variant["originalPrice"] for variant in variants),
            "quantity": sum(variant["quantity"] for variant in variants),
            "variants": variants, "updatedAt": product.get("updated_at") or "",
            "inStock": product.get("stock_status") == "IN_STOCK",
        }
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        return None


def select_balanced(records, target):
    groups = defaultdict(list)
    for record in records:
        groups[(record["department"], record["categoryPath"])].append(record)
    queues = {}
    for key, values in groups.items():
        values.sort(key=lambda item: (item["inStock"], item["updatedAt"]), reverse=True)
        queues[key] = deque(values)
    categories = {department: deque(sorted(path for group, path in queues if group == department))
                  for department in DEPARTMENT_ORDER}
    selected = []
    while len(selected) < target:
        added = False
        for department in DEPARTMENT_ORDER:
            paths = categories[department]
            while paths and not queues[(department, paths[0])]:
                paths.popleft()
            if not paths:
                continue
            path = paths.popleft()
            selected.append(queues[(department, path)].popleft())
            if queues[(department, path)]:
                paths.append(path)
            added = True
            if len(selected) == target:
                break
        if not added:
            break
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, default=Path("output/catalog/muji-candidates.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("output/catalog/muji-diverse-1000.jsonl"))
    parser.add_argument("--target", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    args.candidates.parent.mkdir(parents=True, exist_ok=True)
    urls = sitemap_urls()
    if args.max_pages:
        urls = urls[:args.max_pages]
    existing = [json.loads(line) for line in args.candidates.read_text(encoding="utf-8").splitlines()
                if line.strip()] if args.candidates.exists() else []
    seen_urls = {item["sourceUrl"] for item in existing}
    seen_ids = {item["sourceId"] for item in existing}
    pending = [url for url in urls if url not in seen_urls]
    print(f"MUJI sitemap: {len(urls)} URLs; candidates: {len(existing)}; pending: {len(pending)}", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool, args.candidates.open("a", encoding="utf-8") as output:
        for offset in range(0, len(pending), 25):
            for record in pool.map(extract_record, pending[offset:offset + 25]):
                if not record or record["sourceId"] in seen_ids:
                    continue
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                seen_ids.add(record["sourceId"])
                existing.append(record)
            if (offset + 25) % 200 == 0 or offset + 25 >= len(pending):
                print(f"Checked {min(offset + 25, len(pending))}/{len(pending)}; candidates {len(existing)}", flush=True)
            time.sleep(0.25)
    selected = select_balanced(existing, args.target)
    if len(selected) < args.target:
        raise SystemExit(f"Only {len(selected)}/{args.target} eligible MUJI products found")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in selected), encoding="utf-8")
    counts = {department: sum(item["department"] == department for item in selected)
              for department in DEPARTMENT_ORDER}
    print(f"Selected {len(selected)} unique products by department: {counts}", flush=True)


if __name__ == "__main__":
    main()
