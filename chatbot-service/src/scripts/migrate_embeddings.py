"""Re-embed fresh product text and existing valid captions; never copy old vectors.

Stop the text indexer before running. Source deletion is deliberately a separate
operation after the API has switched and retrieval has been verified.
"""
import argparse
import asyncio

from qdrant_client import models

from ..core.settings import Settings
from ..infrastructure.clients import CatalogAPI
from ..infrastructure.models import ModelClients
from ..product.catalog import VectorCatalog, image_records, point_id, product_document


async def migrate(source):
    settings = Settings()
    api, encoder, target = CatalogAPI(settings), ModelClients(settings), VectorCatalog(settings)
    try:
        if source == target.collection or not source.startswith('catalog_') or source.startswith('catalog_images_'):
            raise ValueError('Source must be a separate legacy text collection')
        products = {str(p['_id']): p for p in await api.all_products()}
        if not products:
            raise RuntimeError('Refusing migration of an empty catalog')
        records = {}
        for pid, product in products.items():
            doc = product_document(product)
            records[point_id(pid)] = {**doc.metadata, 'kind':'text', 'text':doc.page_content}
        offset = None
        while True:
            points, offset = await target.client.scroll(source, limit=100, offset=offset, with_vectors=False)
            for point in points:
                payload = point.payload
                product = products.get(payload.get('productId'))
                if not product or payload.get('kind') != 'image_description' or not payload.get('text'):
                    continue
                expected = {(r['url'], r['variantId']) for r in image_records(product, settings.max_images)}
                if (payload.get('imageUrl'), payload.get('variantId', '')) not in expected:
                    continue
                records[str(point.id)] = {**payload, **product_document(product).metadata}
            if offset is None:
                break
        await target.ensure(settings.embedding_dimensions)
        items = list(records.items())
        # Resume safely after quota/network failures; changed payloads are re-embedded.
        existing_payloads = {}
        offset = None
        while True:
            points, offset = await target.client.scroll(target.collection, limit=100, offset=offset, with_vectors=False)
            existing_payloads.update((str(p.id), p.payload) for p in points)
            if offset is None:
                break
        items = [(pid, payload) for pid, payload in items if existing_payloads.get(pid) != payload]
        print(f'Remaining points: {len(items)}', flush=True)
        for start in range(0, len(items), 20):
            batch = items[start:start + 20]
            vectors = await encoder.embed_documents([payload['text'] for _, payload in batch])
            await target.upsert([models.PointStruct(id=pid, vector=vector, payload=payload)
                for (pid, payload), vector in zip(batch, vectors)])
            print(f'Re-embedded {min(start + 20, len(items))}/{len(items)}', flush=True)
            if start + 20 < len(items):
                await asyncio.sleep(15)  # Leave capacity for online queries on 100 RPM keys.
        # Verify every expected point exists, including captions, before cutover.
        actual = set()
        offset = None
        while True:
            points, offset = await target.client.scroll(target.collection, limit=100, offset=offset, with_payload=False)
            actual.update(str(p.id) for p in points)
            if offset is None:
                break
        if not set(records).issubset(actual):
            raise RuntimeError('Destination is incomplete; keep source collection')
        print({'source': source, 'destination': target.collection, 'products': len(products),
               'points': len(records), 'dimensions': settings.embedding_dimensions, 'verified': True}, flush=True)
    finally:
        await api.close()
        await encoder.close()
        await target.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    asyncio.run(migrate(parser.parse_args().source))
