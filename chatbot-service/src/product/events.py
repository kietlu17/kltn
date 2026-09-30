"""Reliable, micro-batched product event consumption for catalog indexers."""
import asyncio
import json
import logging
import os

from aiokafka import AIOKafkaConsumer


log = logging.getLogger(__name__)
PRODUCT_TOPICS = ("product.created", "product.updated", "product.deleted")


def _product_id(message) -> str:
    try:
        payload = json.loads(message.value.decode()) if message.value else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    product_id = payload.get("id") or payload.get("productId")
    if not product_id and message.key:
        product_id = message.key.decode()
    return str(product_id or "").strip()


async def consume_product_events(group_id: str, handler):
    """Consume at-least-once and commit only after the whole micro-batch succeeds."""
    broker = os.getenv("KAFKA_BROKER")
    if not broker:
        raise RuntimeError("KAFKA_BROKER is required for event-driven indexing")
    batch_size = max(1, int(os.getenv("CHATBOT_EVENT_BATCH_SIZE", "20")))
    batch_ms = max(100, int(os.getenv("CHATBOT_EVENT_BATCH_MS", "1000")))
    retry_seconds = max(1, int(os.getenv("CHATBOT_INDEX_RETRY_SECONDS", "15")))
    failures = 0

    while True:
        consumer = AIOKafkaConsumer(
            *PRODUCT_TOPICS,
            bootstrap_servers=broker,
            group_id=group_id,
            auto_offset_reset="latest",
            enable_auto_commit=False,
            max_poll_interval_ms=900_000,
        )
        try:
            await consumer.start()
            log.info("Product event indexer ready: group=%s", group_id)
            while True:
                records = await consumer.getmany(timeout_ms=batch_ms, max_records=batch_size)
                latest = {}
                for messages in records.values():
                    for message in messages:
                        product_id = _product_id(message)
                        if product_id:
                            # Assignment preserves insertion order while the last event wins.
                            latest[product_id] = message.topic
                        else:
                            log.warning("Skipping product event without an id: topic=%s", message.topic)
                if latest:
                    await handler([(topic, product_id) for product_id, topic in latest.items()])
                if records:
                    await consumer.commit()
                    failures = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            failures += 1
            delay = min(300, retry_seconds * (2 ** min(failures - 1, 5)))
            log.exception("Product event consumer failed; retrying in %ss", delay)
            await asyncio.sleep(delay)
        finally:
            await consumer.stop()
