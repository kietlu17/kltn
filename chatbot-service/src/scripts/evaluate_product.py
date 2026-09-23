"""Run reproducible retrieval checks against real catalog data (no LLM judging).

python -m src.scripts.evaluate_product --limit 12 --output /data/product-evaluation.json
Catalog-image self-retrieval is a wiring check, not a held-out quality benchmark.
"""
import argparse
import asyncio
import json
from pathlib import Path

from ..agents.state import SearchPlan
from ..core.settings import Settings
from ..infrastructure.clients import CatalogAPI
from ..infrastructure.models import ModelClients
from ..product.catalog import VectorCatalog
from ..product.rag import ProductRAG
from ..product.visual import VisualCatalog


async def run(limit, output):
    settings = Settings()
    api = CatalogAPI(settings)
    models = ModelClients(settings)
    text = VectorCatalog(settings)
    visual = VisualCatalog(settings)
    try:
        catalog = await api.all_products()
        # Spread picks through the catalogue instead of selecting one adjacent category.
        step = max(1, len(catalog) // limit)
        samples = [p for p in catalog[::step] if p.get('images')][:limit]
        rows = []
        for product in samples:
            pid = str(product['_id'])
            image = await api.image(product['images'][0])
            hits = await visual.query(await visual.embed(image))
            ids = list(dict.fromkeys(h.payload['productId'] for h in hits))
            rows.append({'kind':'catalog_image_self_lookup', 'productId':pid,
                         'top1': bool(ids and ids[0] == pid), 'hit_at_5': pid in ids[:5], 'returned':ids[:5]})
            result = await ProductRAG(api, models, text).chain.ainvoke({
                'message':product['name'], 'plan':SearchPlan(query=product['name']).model_dump()})
            fresh, stock = await api.fresh([pid])
            from ..product.catalog import eligible_cards
            eligible = bool(eligible_cards(fresh, stock, [pid], {}))
            returned = [p['id'] for p in result['products']]
            rows.append({'kind':'catalog_name_lookup', 'productId':pid, 'eligible':eligible,
                         'hit_at_6':pid in returned, 'returned':returned})
        images = [r for r in rows if r['kind']=='catalog_image_self_lookup']
        names = [r for r in rows if r['kind']=='catalog_name_lookup' and r['eligible']]
        summary = {'image_samples':len(images), 'image_hit_at_5':sum(r['hit_at_5'] for r in images),
                   'eligible_name_samples':len(names), 'name_hit_at_6':sum(r['hit_at_6'] for r in names),
                   'limitation':'Catalog self-lookup only; not independent shopper-photo evaluation.'}
        Path(output).write_text(json.dumps({'summary':summary,'cases':rows},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(summary))
    finally:
        await api.close(); await models.close(); await text.close(); await visual.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit',type=int,default=12)
    parser.add_argument('--output',default='/data/product-evaluation.json')
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    asyncio.run(run(args.limit,args.output))
