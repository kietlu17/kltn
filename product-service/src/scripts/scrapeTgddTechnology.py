"""Collect attributed technology products from public TGDD product pages.

The crawler follows robots.txt crawl-delay, keeps a resumable JSONL snapshot,
and rejects pages without substantial descriptions or technical specifications.
"""

import argparse
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup


BASE = "https://www.thegioididong.com"
CATEGORIES = {"laptop": "Laptop", "dtdd": "Điện thoại", "tai-nghe": "Tai nghe", "loa-laptop": "Loa"}
DEFAULT_OUTPUT = Path("output/catalog/tgdd-technology-500.jsonl")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ResearchCatalogBot/1.0; +https://example.org/research)"}
BRAND_LIMITS = {"laptop": 12, "dtdd": 30, "tai-nghe": 24, "loa-laptop": 24}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def category_for(url):
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc != "www.thegioididong.com":
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) == 2 and parts[0] in CATEGORIES and parts[1]:
        return parts[0]
    return None


class PoliteSession:
    def __init__(self, delay=5):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.delay = delay
        self.last_request = 0

    def get(self, url):
        remaining = self.delay - (time.monotonic() - self.last_request)
        if remaining > 0:
            time.sleep(remaining)
        self.last_request = time.monotonic()
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response


def sitemap_urls(session, max_sitemaps, candidate_target, cache_path):
    index = ElementTree.fromstring(session.get(BASE + "/newsitemap/sitemap-product").content)
    maps = [node.text for node in index.iter() if node.tag.endswith("loc")]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cached = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line:
                record = json.loads(line)
                cached[record["sitemap"]] = record["urls"]
    seen = set()
    counts = Counter()
    with cache_path.open("a", encoding="utf-8") as handle:
      for index, sitemap in enumerate(maps[:max_sitemaps], 1):
        if sitemap in cached:
            urls = cached[sitemap]
        else:
            try:
                root = ElementTree.fromstring(session.get(sitemap).content)
                urls = [node.text.split("?", 1)[0] for node in root.iter()
                        if node.tag.endswith("loc") and node.text]
            except (requests.RequestException, ElementTree.ParseError) as error:
                print(f"Skip sitemap {sitemap}: {error}", flush=True)
                continue
            handle.write(json.dumps({"sitemap": sitemap, "urls": urls}, ensure_ascii=False) + "\n")
            handle.flush()
        for url in urls:
            category = category_for(url)
            if category and url not in seen:
                seen.add(url)
                counts[category] += 1
                yield category, url
        if index % 20 == 0:
            print(f"Scanned {index} sitemaps: {dict(counts)}", flush=True)
        if all(counts[item] >= candidate_target for item in CATEGORIES):
            print(f"Sitemap candidates by category: {dict(counts)}", flush=True)
            break


def live_category_urls(session, cache_path):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cached = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line:
                record = json.loads(line)
                cached[record["page"]] = record
    seen = set()
    with cache_path.open("a", encoding="utf-8") as handle:
        for category in CATEGORIES:
            pages = [BASE + "/" + category]
            brand_count = 0
            index = 0
            while index < len(pages) and brand_count <= BRAND_LIMITS[category]:
                page = pages[index]
                index += 1
                if page in cached:
                    record = cached[page]
                else:
                    try:
                        soup = BeautifulSoup(session.get(page).text, "html.parser")
                    except requests.RequestException as error:
                        print(f"Skip listing {page}: {error}", flush=True)
                        continue
                    links = [urljoin(BASE, anchor.get("href")) for anchor in soup.find_all("a", href=True)]
                    record = {"page": page,
                              "urls": list(dict.fromkeys(url for url in links if category_for(url) == category)),
                              "brands": list(dict.fromkeys(url for url in links
                                  if re.fullmatch(r"/" + category + r"-[^/?#]+", urlparse(url).path)))}
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    handle.flush()
                    cached[page] = record
                if index == 1:
                    pages.extend(record["brands"][:BRAND_LIMITS[category]])
                for url in record["urls"]:
                    if url not in seen:
                        seen.add(url)
                        yield category, url
                brand_count += 1
            print(f"Live listing {category}: {sum(category_for(url) == category for url in seen)} unique URLs", flush=True)


def parse_product(html, url, category):
    soup = BeautifulSoup(html, "html.parser")
    groups = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("@type") in ("ProductGroup", "Product"):
            groups.append(payload)
    if not groups:
        return None
    group = max(groups, key=lambda item: len(item.get("additionalProperty") or []))
    name = clean(group.get("name"))
    source_id = clean(group.get("productGroupID") or group.get("sku"))
    specs = {}
    for prop in group.get("additionalProperty") or []:
        key, value = clean(prop.get("name")), clean(prop.get("value"))
        if key and value and value.casefold() not in ("không", "đang cập nhật"):
            specs.setdefault(key, value)
    descriptions = [clean(block.get_text(" ", strip=True)) for block in soup.find_all(id="description-text-detail")]
    description = max(descriptions, key=len, default="")
    if len(description) < 180 or len(specs) < 5 or not name or not source_id:
        return None
    variants_raw = group.get("hasVariant") or [group]
    if isinstance(variants_raw, dict):
        variants_raw = [variants_raw]
    images = []
    for variant in variants_raw:
        variant_images = variant.get("image") or []
        if not isinstance(variant_images, list):
            variant_images = [variant_images]
        for image in variant_images:
            link = image.get("url") if isinstance(image, dict) else image
            if isinstance(link, str) and link.startswith("https://") and link not in images:
                images.append(link)
    if not images:
        return None
    # The visible promotional price can differ from schema.org's list price.
    price = None
    original_price = None
    for span in soup.find_all("span"):
        classes = span.get("class") or []
        if "text-24" in classes and "text-red-5" in classes:
            match = re.search(r"\d[\d.]*", span.get_text(" ", strip=True))
            if match:
                price = int(match.group().replace(".", ""))
                parent = span.parent.parent if span.parent else None
                old = parent.find("del") if parent else None
                if old:
                    old_match = re.search(r"\d[\d.]*", old.get_text(" ", strip=True))
                    if old_match:
                        original_price = int(old_match.group().replace(".", ""))
                break
    if not price:
        offer_prices = [int((v.get("offers") or {}).get("price") or 0) for v in variants_raw]
        price = min((p for p in offer_prices if p > 0), default=0)
    if price <= 0:
        return None
    if not original_price or original_price < price:
        original_price = price
    return {
        "sourceProvider": "tgdd",
        "sourceId": source_id,
        "sourceUrl": url,
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "category": CATEGORIES[category],
        "name": name,
        "brand": clean(group.get("brand", {}).get("name") if isinstance(group.get("brand"), dict) else group.get("brand")),
        "price": price,
        "originalPrice": original_price,
        "description": description[:4000],
        "specifications": specs,
        "images": images[:6],
    }


def run(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if output.exists():
        existing = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line]
    counts = Counter(row["category"] for row in existing)
    used_urls = {row["sourceUrl"] for row in existing}
    used_ids = {row["sourceId"] for row in existing}
    attempt_path = Path(args.attempt_cache)
    attempt_path.parent.mkdir(parents=True, exist_ok=True)
    attempted = set(attempt_path.read_text(encoding="utf-8").splitlines()) if attempt_path.exists() else set()
    quotas = {name: args.per_category for name in CATEGORIES.values()}
    if all(counts[name] >= quotas[name] for name in quotas):
        print(f"Already complete: {dict(counts)}", flush=True)
        return
    session = PoliteSession(args.delay)
    live = list(live_category_urls(session, Path(args.listing_cache)))
    fallback = list(sitemap_urls(session, args.max_sitemaps, args.per_category,
                                 Path(args.candidate_cache)))
    seen_candidates = set()
    candidates = []
    for category, url in live + fallback:
        if url not in seen_candidates:
            candidates.append((category, url))
            seen_candidates.add(url)
    print(f"Candidates: {len(candidates)}; existing: {dict(counts)}", flush=True)
    rejected = Counter()
    with output.open("a", encoding="utf-8") as handle, attempt_path.open("a", encoding="utf-8") as attempts:
        for category, url in candidates:
            name = CATEGORIES[category]
            if counts[name] >= quotas[name] or url in used_urls or url in attempted:
                continue
            attempts.write(url + "\n")
            attempts.flush()
            attempted.add(url)
            try:
                row = parse_product(session.get(url).text, url, category)
            except (requests.RequestException, TypeError, ValueError, AttributeError) as error:
                rejected["request_or_parse"] += 1
                print(f"Skip {url}: {error}", flush=True)
                continue
            if not row or row["sourceId"] in used_ids:
                rejected["quality_or_duplicate"] += 1
                continue
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            used_urls.add(url)
            used_ids.add(row["sourceId"])
            counts[name] += 1
            if sum(counts.values()) % 20 == 0:
                print(f"Accepted {sum(counts.values())}: {dict(counts)}; rejected: {dict(rejected)}", flush=True)
            if all(counts[item] >= quotas[item] for item in quotas):
                break
    print(f"Final: {dict(counts)}; rejected: {dict(rejected)}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--per-category", type=int, default=125)
    parser.add_argument("--max-sitemaps", type=int, default=100)
    parser.add_argument("--candidate-cache", default="output/catalog/tgdd-sitemap-cache.jsonl")
    parser.add_argument("--listing-cache", default="output/catalog/tgdd-listing-cache.jsonl")
    parser.add_argument("--attempt-cache", default="output/catalog/tgdd-attempted-urls.txt")
    parser.add_argument("--delay", type=float, default=5)
    run(parser.parse_args())
