from __future__ import annotations

import asyncio
import html
import os
import re
import ssl
import time
import unicodedata

import httpx

from .config import AgenticSettings
from .schemas import ProductCard, ProductVariant, SearchFilters


_CATEGORY_CACHE_SECONDS = 300


def _plain_text(value, limit: int = 1200) -> str:
    text = re.sub(r"<[^>]*>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()[:limit]


def _normalized(value) -> str:
    text = unicodedata.normalize("NFD", _plain_text(value).casefold()).replace("đ", "d")
    return "".join(char for char in text if not unicodedata.combining(char))


def _matches_audience(product: dict, audience: str | None) -> bool:
    """Reject explicit audience conflicts when indexed facets are noisy."""
    if not audience or audience == "unisex":
        return True
    name = _normalized(product.get("name", ""))
    signals = {
        "nam": bool(re.search(r"\bnam\b|\bbe trai\b", name)),
        "nu": bool(re.search(r"\bnu\b|\bbe gai\b", name)),
        "tre_em": bool(re.search(r"\btre em\b|\btre\b|\bbe trai\b|\bbe gai\b", name)),
    }
    if audience == "nam" and signals["nu"] and not signals["nam"]:
        return False
    if audience == "nu" and signals["nam"] and not signals["nu"]:
        return False
    if audience == "tre_em" and (signals["nam"] or signals["nu"]) and not signals["tre_em"]:
        return False
    return True


class MarketplaceError(RuntimeError):
    def __init__(self, status: int, message: str, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


class MarketplaceClient:
    """Deterministic boundary around catalog, cart, order and checkout APIs."""

    def __init__(self, settings: AgenticSettings, http: httpx.AsyncClient | None = None):
        self.settings = settings
        if http is not None:
            self.http = http
            self._owns_http = False
            return
        verify: bool | ssl.SSLContext = True
        if os.getenv("MTLS_ENABLED", "false").lower() == "true":
            verify = ssl.create_default_context(cafile=os.environ["MTLS_CA_PATH"])
            verify.load_cert_chain(
                os.environ["MTLS_CLIENT_CERT_PATH"],
                os.environ["MTLS_CLIENT_KEY_PATH"],
            )
        self.http = httpx.AsyncClient(verify=verify, timeout=settings.request_timeout)
        self._owns_http = True

    @staticmethod
    def _headers(user_id: str, idempotency_key: str = "") -> dict:
        headers = {"x-user-id": user_id, "x-user-role": "buyer"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    @staticmethod
    async def _json(response: httpx.Response):
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.is_error:
            raise MarketplaceError(
                response.status_code,
                body.get("message", "Dịch vụ thương mại điện tử tạm thời không khả dụng."),
                body.get("code", ""),
            )
        return body

    async def categories(self) -> list[dict]:
        # The taxonomy changes rarely but is read on most planning turns.
        cached = getattr(self, "_categories_cache", None)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        response = await self.http.get(f"{self.settings.product_url}/categories")
        body = await self._json(response)
        categories = [
            {
                "id": str(item.get("_id") or item.get("id") or ""),
                "name": item.get("name", ""),
                "parentId": str(item.get("parentId") or "") or None,
                "shopId": str(item.get("shopId") or ""),
            }
            for item in body
            if isinstance(item, dict) and item.get("name")
        ] if isinstance(body, list) else []
        self._categories_cache = (time.monotonic() + _CATEGORY_CACHE_SECONDS, categories)
        return categories

    async def all_products(self) -> list[dict]:
        """Every approved product; raises instead of returning a partial catalog."""
        products: dict[str, dict] = {}
        page = 1
        while True:
            response = await self.http.get(
                f"{self.settings.product_url}/products",
                params={"paginated": "true", "page": page, "limit": 100, "sort": "newest"},
            )
            body = await self._json(response)
            if not isinstance(body, dict) or "items" not in body or "pagination" not in body:
                raise MarketplaceError(502, "Invalid paginated catalog response")
            for product in body["items"]:
                if isinstance(product, dict) and product.get("moderationStatus") == "approved":
                    products[str(product["_id"])] = product
            if not body["pagination"].get("hasNextPage"):
                return list(products.values())
            page += 1
            if page > 10000:
                raise MarketplaceError(502, "Catalog pagination exceeded safety limit")

    async def product(self, product_id: str) -> dict | None:
        response = await self.http.get(
            f"{self.settings.product_url}/products/{product_id}"
        )
        if response.status_code == 404:
            return None
        body = await self._json(response)
        if not isinstance(body, dict) or body.get("moderationStatus") != "approved":
            return None
        return body

    async def hydrate_products(
        self,
        hits: list[dict],
        filters: SearchFilters,
        limit: int,
    ) -> list[dict]:
        ids = list(dict.fromkeys(str(hit.get("productId")) for hit in hits if hit.get("productId")))
        if not ids:
            return []
        product_response, inventory_response = await asyncio.gather(
            self.http.get(
                f"{self.settings.product_url}/products/batch",
                params={"ids": ",".join(ids[:200])},
            ),
            self.http.get(
                f"{self.settings.inventory_url}/inventory/products",
                params={"ids": ",".join(ids[:200])},
            ),
        )
        products_body = await self._json(product_response)
        inventory_body = await self._json(inventory_response)
        products = {
            str(item.get("_id")): item
            for item in products_body
            if isinstance(item, dict) and item.get("moderationStatus") == "approved"
        } if isinstance(products_body, list) else {}
        stock = {
            (str(item.get("productId")), str(item.get("variantId") or "")): float(
                item.get("availableStock") or 0
            )
            for item in (inventory_body.get("items", []) if isinstance(inventory_body, dict) else [])
            if isinstance(item, dict) and item.get("productId")
        }
        hit_scores = {str(item["productId"]): item.get("vectorScore") for item in hits}
        cards: list[dict] = []
        for product_id in ids:
            product = products.get(product_id)
            if not product:
                continue
            if not _matches_audience(product, filters.audience):
                continue
            allowed_categories = set(filters.category_ids)
            if filters.category_id:
                allowed_categories.add(filters.category_id)
            if allowed_categories and str(product.get("categoryId") or "") not in allowed_categories:
                continue
            searchable_product = _normalized(
                " ".join(
                    [
                        str(product.get("name") or ""),
                        str(product.get("description") or ""),
                        str(product.get("brand") or product.get("brandName") or ""),
                    ]
                )
            )
            if filters.brand and _normalized(filters.brand) not in searchable_product:
                continue
            variants: list[ProductVariant] = []
            offers = product.get("variants") or [product]
            for offer in offers:
                variant_id = str(offer.get("_id") or "") if product.get("variants") else ""
                available = stock.get((product_id, variant_id))
                if filters.in_stock and (available is None or available <= 0):
                    continue
                try:
                    price = float(offer.get("price", product.get("price", 0)) or 0)
                except (TypeError, ValueError):
                    continue
                if filters.min_price is not None and price < filters.min_price:
                    continue
                if filters.max_price is not None and price > filters.max_price:
                    continue
                offer_text = _normalized(offer.get("name", ""))
                if filters.colors and not all(
                    _normalized(value) in offer_text for value in filters.colors
                ):
                    continue
                if filters.sizes and not any(
                    re.search(rf"(?<!\w){re.escape(_normalized(value))}(?!\w)", offer_text)
                    for value in filters.sizes
                ):
                    continue
                variants.append(
                    ProductVariant(
                        id=variant_id or None,
                        name=_plain_text(offer.get("name"), 300),
                        price=price,
                        availableStock=float(available or 0),
                        imageUrl=str(offer.get("imageUrl") or ""),
                    )
                )
            if not variants:
                continue
            best = min(variants, key=lambda item: item.price)
            card = ProductCard(
                id=product_id,
                name=_plain_text(product.get("name"), 300),
                price=best.price,
                imageUrl=best.imageUrl
                or next(iter(product.get("images") or []), ""),
                shopId=str(product.get("shopId") or ""),
                url=f"/product/{product_id}",
                description=_plain_text(product.get("description"), 800),
                score=hit_scores.get(product_id),
                variants=variants[:20],
                specifications=[
                    {
                        "name": _plain_text(item.get("name"), 200),
                        "value": _plain_text(item.get("value"), 500),
                    }
                    for item in product.get("specifications", [])[:80]
                    if isinstance(item, dict)
                    and _plain_text(item.get("name"), 200)
                    and _plain_text(item.get("value"), 500)
                ],
            )
            cards.append(card.model_dump())
            if len(cards) >= limit:
                break
        return cards

    async def product_card(
        self, product_id: str, filters: SearchFilters | None = None
    ) -> dict | None:
        hits = [{"productId": product_id, "vectorScore": None}]
        cards = await self.hydrate_products(hits, filters or SearchFilters(), 1)
        return cards[0] if cards else None

    async def cart(self, user_id: str) -> dict:
        response = await self.http.get(
            f"{self.settings.cart_url}/cart/user", headers=self._headers(user_id)
        )
        body = await self._json(response)
        return body if isinstance(body, dict) else {"userId": user_id, "products": []}

    async def add_to_cart(
        self,
        user_id: str,
        product_id: str,
        variant_id: str | None,
        quantity: int,
        action_id: str,
    ) -> dict:
        response = await self.http.post(
            f"{self.settings.cart_url}/cart/add",
            headers=self._headers(user_id, action_id),
            json={
                "userId": user_id,
                "productId": product_id,
                "variantId": variant_id,
                "quantity": quantity,
                "actionKey": action_id,
            },
        )
        body = await self._json(response)
        return body if isinstance(body, dict) else {}

    async def set_cart_line(
        self,
        user_id: str,
        product_id: str,
        variant_id: str | None,
        quantity: int,
    ) -> dict:
        response = await self.http.put(
            f"{self.settings.cart_url}/cart/items",
            headers=self._headers(user_id),
            json={
                "userId": user_id,
                "productId": product_id,
                "variantId": variant_id,
                "targetQuantity": quantity,
            },
        )
        body = await self._json(response)
        return body if isinstance(body, dict) else {}

    async def addresses(self, user_id: str) -> list[dict]:
        response = await self.http.get(
            f"{self.settings.user_url}/users/{user_id}/addresses",
            headers=self._headers(user_id),
        )
        body = await self._json(response)
        return body if isinstance(body, list) else []

    async def orders(self, user_id: str) -> list[dict]:
        response = await self.http.get(
            f"{self.settings.order_url}/orders/user", headers=self._headers(user_id)
        )
        body = await self._json(response)
        return body if isinstance(body, list) else []

    async def shipment(self, user_id: str, order_id: int) -> dict | None:
        response = await self.http.get(
            f"{self.settings.order_url}/orders/shipments/order/{order_id}",
            headers=self._headers(user_id),
        )
        if response.status_code == 404:
            return None
        body = await self._json(response)
        return body if isinstance(body, dict) else None

    async def checkout_quote(
        self,
        user_id: str,
        session_id: str,
        products: list[dict],
        address_id: str,
        payment_method: str,
        voucher_code: str | None,
    ) -> dict:
        response = await self.http.post(
            f"{self.settings.order_url}/orders/checkout/quotes",
            headers=self._headers(user_id),
            json={
                "userId": user_id,
                "sessionId": session_id,
                "products": products,
                "addressId": address_id,
                "paymentMethod": payment_method,
                "voucherCode": voucher_code,
            },
        )
        body = await self._json(response)
        return body if isinstance(body, dict) else {}

    async def confirm_checkout(
        self,
        user_id: str,
        session_id: str,
        quote_id: str,
        confirmation_token: str,
    ) -> dict:
        response = await self.http.post(
            f"{self.settings.order_url}/orders/checkout/quotes/{quote_id}/confirm",
            headers=self._headers(user_id),
            json={
                "userId": user_id,
                "sessionId": session_id,
                "confirmationToken": confirmation_token,
            },
        )
        body = await self._json(response)
        return body if isinstance(body, dict) else {}

    async def close(self):
        if self._owns_http:
            await self.http.aclose()

