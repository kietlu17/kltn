import asyncio
import base64
import io
import json
import os
import ssl
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from ..core.settings import Settings

Image.MAX_IMAGE_PIXELS = 20_000_000


def normalize_image(raw: bytes, max_bytes: int) -> str:
    if not raw or len(raw) > max_bytes:
        raise ValueError("Ảnh phải có dung lượng tối đa 5 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Chỉ hỗ trợ ảnh JPG, PNG hoặc WebP.")
            if source.width * source.height > 20_000_000:
                raise ValueError("Ảnh có độ phân giải quá lớn.")
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1024, 1024))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=85)
            return base64.b64encode(output.getvalue()).decode()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Không đọc được ảnh. Hãy chọn ảnh JPG, PNG hoặc WebP hợp lệ.") from exc


class CatalogAPI:
    def __init__(self, settings: Settings):
        self.settings = settings
        verify = True
        if os.getenv("MTLS_ENABLED") == "true":
            verify = ssl.create_default_context(cafile=os.environ["MTLS_CA_PATH"])
            verify.load_cert_chain(os.environ["MTLS_CLIENT_CERT_PATH"], os.environ["MTLS_CLIENT_KEY_PATH"])
        # Never forward shopper/admin headers to catalog reads.
        self.http = httpx.AsyncClient(verify=verify, timeout=20)
        # Public image downloads must not receive our service certificate.
        self.images = httpx.AsyncClient(timeout=20, follow_redirects=False)

    async def all_products(self) -> list[dict]:
        products = {}
        page = 1
        while True:
            response = await self.http.get(f"{self.settings.product_url}/products", params={
                "paginated": "true", "page": page, "limit": 100, "sort": "newest",
            })
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict) or "items" not in body or "pagination" not in body:
                raise RuntimeError("Invalid paginated catalog response; reconciliation aborted")
            for product in body["items"]:
                if product.get("moderationStatus") == "approved":
                    products[str(product["_id"])] = product
            if not body["pagination"]["hasNextPage"]:
                break
            page += 1
            if page > 10000:
                raise RuntimeError("Catalog pagination exceeded safety limit")
        return list(products.values())

    async def product(self, product_id: str) -> dict | None:
        response = await self.http.get(f"{self.settings.product_url}/products/{product_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        product = response.json()
        return product if product.get("moderationStatus") == "approved" else None

    async def fresh(self, ids: list[str]) -> tuple[list[dict], dict]:
        if not ids:
            return [], {}
        products_response, stock_response = await asyncio.gather(
            self.http.get(f"{self.settings.product_url}/products/batch", params={"ids": ",".join(ids)}),
            self.http.get(f"{self.settings.inventory_url}/inventory/products", params={"ids": ",".join(ids)}),
        )
        products_response.raise_for_status()
        stock_response.raise_for_status()
        products = [p for p in products_response.json() if p.get("moderationStatus") == "approved"]
        stock = {(str(p["productId"]), str(p.get("variantId") or "")): p["availableStock"]
                 for p in stock_response.json()["items"]}
        return products, stock

    async def review_summaries(self, ids: list[str]) -> dict:
        if not ids:
            return {"items": [], "globalAverageRating": None, "globalReviewCount": 0}
        response = await self.http.get(
            f"{self.settings.review_url}/reviews/products/summary",
            params={"ids": ",".join(dict.fromkeys(ids[:200]))},
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise RuntimeError("Invalid review summary response")
        return body

    async def reviews(self, product_id: str) -> list[dict]:
        response = await self.http.get(f"{self.settings.review_url}/reviews/product/{product_id}")
        response.raise_for_status()
        body = response.json()
        return body if isinstance(body, list) else []

    async def image(self, url: str) -> str:
        public = self.settings.image_public_base
        if url.startswith("/uploads/"):
            target = self.settings.product_url + url
            client = self.http
        elif public and url.startswith(public + "/"):
            target = self.settings.product_url + "/uploads/" + url[len(public) + 1:]
            client = self.http
        else:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.username or parsed.password or parsed.hostname not in self.settings.image_hosts:
                raise ValueError("Image host is not allowed; configure CHATBOT_IMAGE_HOSTS")
            target, client = url, self.images
        raw = bytearray()
        async with client.stream("GET", target) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > self.settings.max_image_bytes:
                    raise ValueError("Catalog image exceeds 5 MB")
        return await asyncio.to_thread(normalize_image, bytes(raw), self.settings.max_image_bytes)

    async def close(self):
        await self.http.aclose()
        await self.images.aclose()


class CommerceError(RuntimeError):
    def __init__(self, status: int, message: str, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


class CommerceAPI:
    """Authenticated service-to-service client for deterministic shopping actions."""

    def __init__(self, settings: Settings):
        self.settings = settings
        verify = True
        if os.getenv("MTLS_ENABLED") == "true":
            verify = ssl.create_default_context(cafile=os.environ["MTLS_CA_PATH"])
            verify.load_cert_chain(os.environ["MTLS_CLIENT_CERT_PATH"], os.environ["MTLS_CLIENT_KEY_PATH"])
        self.http = httpx.AsyncClient(verify=verify, timeout=30)

    @staticmethod
    def _headers(user_id: str, action_key: str = "") -> dict:
        headers = {"x-user-id": user_id, "x-user-role": "buyer"}
        if action_key:
            headers["Idempotency-Key"] = action_key
        return headers

    @staticmethod
    async def _json(response: httpx.Response) -> dict | list:
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.is_error:
            raise CommerceError(
                response.status_code,
                body.get("message", "Dịch vụ mua hàng tạm thời không xử lý được yêu cầu."),
                body.get("code", ""),
            )
        return body

    async def cart(self, user_id: str) -> dict:
        response = await self.http.get(
            f"{self.settings.cart_url}/cart/user", headers=self._headers(user_id)
        )
        return await self._json(response)

    async def user_orders(self, user_id: str) -> list[dict]:
        response = await self.http.get(
            f"{self.settings.order_url}/orders/user", headers=self._headers(user_id)
        )
        body = await self._json(response)
        return body if isinstance(body, list) else []

    async def order_shipment(self, user_id: str, order_id: int) -> dict | None:
        response = await self.http.get(
            f"{self.settings.order_url}/orders/shipments/order/{order_id}",
            headers=self._headers(user_id),
        )
        if response.status_code == 404:
            return None
        body = await self._json(response)
        return body if isinstance(body, dict) else None

    async def add_to_cart(
        self, user_id: str, product_id: str, variant_id: str | None, quantity: int, action_key: str
    ) -> dict:
        response = await self.http.post(
            f"{self.settings.cart_url}/cart/add",
            headers=self._headers(user_id),
            json={
                "userId": user_id,
                "productId": product_id,
                "variantId": variant_id,
                "quantity": quantity,
                "actionKey": action_key,
            },
        )
        return await self._json(response)

    async def remove_cart_line(self, user_id: str, product_id: str, variant_id: str | None) -> None:
        response = await self.http.put(
            f"{self.settings.cart_url}/cart/items",
            headers=self._headers(user_id),
            json={
                "userId": user_id,
                "productId": product_id,
                "variantId": variant_id,
                "targetQuantity": 0,
            },
        )
        await self._json(response)

    async def set_cart_line(
        self,
        user_id: str,
        product_id: str,
        variant_id: str | None,
        quantity: int,
        expected_quantity: int | None = None,
    ) -> dict:
        payload = {
            "userId": user_id,
            "productId": product_id,
            "variantId": variant_id,
            "targetQuantity": quantity,
        }
        if expected_quantity is not None:
            payload["expectedCurrentQuantity"] = expected_quantity
        response = await self.http.put(
            f"{self.settings.cart_url}/cart/items",
            headers=self._headers(user_id),
            json=payload,
        )
        return await self._json(response)

    async def replace_cart_line(
        self,
        user_id: str,
        old_product_id: str,
        old_variant_id: str | None,
        new_product_id: str,
        new_variant_id: str | None,
        quantity: int,
    ) -> dict:
        if old_product_id == new_product_id and str(old_variant_id or "") == str(new_variant_id or ""):
            return await self.set_cart_line(user_id, old_product_id, old_variant_id, quantity)
        cart = await self.cart(user_id)
        existing_new = next((
            item for item in cart.get("products", [])
            if str(item.get("productId")) == str(new_product_id)
            and str(item.get("variantId") or "") == str(new_variant_id or "")
        ), None)
        previous_new_quantity = int(existing_new.get("quantity", 0)) if existing_new else 0
        await self.set_cart_line(
            user_id, new_product_id, new_variant_id, previous_new_quantity + quantity,
            previous_new_quantity,
        )
        try:
            return await self.set_cart_line(user_id, old_product_id, old_variant_id, 0, quantity)
        except CommerceError:
            await self.set_cart_line(
                user_id, new_product_id, new_variant_id, previous_new_quantity,
                previous_new_quantity + quantity,
            )
            raise

    async def addresses(self, user_id: str) -> list[dict]:
        response = await self.http.get(
            f"{self.settings.user_url}/users/{user_id}/addresses",
            headers=self._headers(user_id),
        )
        body = await self._json(response)
        return body if isinstance(body, list) else []

    async def checkout_vouchers(self, user_id: str, items: list[dict]) -> list[dict]:
        response = await self.http.post(
            f"{self.settings.voucher_url}/vouchers/checkout",
            headers=self._headers(user_id),
            json={"userId": user_id, "items": items},
        )
        body = await self._json(response)
        return body if isinstance(body, list) else []

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
        self, user_id: str, session_id: str, quote_id: str, confirmation_token: str
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
        await self.http.aclose()
