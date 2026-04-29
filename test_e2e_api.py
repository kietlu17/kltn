import json
import time
import unittest
import urllib.error
import urllib.request


BASE_URL = "http://localhost:3000"


class ApiError(Exception):
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload
        super().__init__(f"HTTP {status}: {payload}")


class EcommerceE2ETest(unittest.TestCase):
    def api(self, method, path, data=None, token=None, expected_statuses=(200, 201), extra_headers=None):
        url = f"{BASE_URL}{path}"
        headers = {}
        body = None

        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if extra_headers:
            headers.update(extra_headers)

        request = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8") if response else ""
                payload = json.loads(raw) if raw else {}
                if response.status not in expected_statuses:
                    raise ApiError(response.status, payload)
                return response.status, payload
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8") if err else ""
            try:
                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {"raw": raw}
            raise ApiError(err.code, payload) from err

    def wait_until(self, fn, timeout_sec=20, interval_sec=1):
        end = time.time() + timeout_sec
        last = None
        while time.time() < end:
            last = fn()
            if last:
                return True
            time.sleep(interval_sec)
        return False

    def test_full_e2e_flow(self):
        stamp = str(int(time.time() * 1000))
        seller_email = f"seller_{stamp}@demo.com"
        buyer_email = f"buyer_{stamp}@demo.com"
        password = "123456"

        self.api("GET", "/shops", expected_statuses=(200,))

        # 1) Register + login seller
        self.api(
            "POST",
            "/auth/register",
            {
                "email": seller_email,
                "password": password,
                "role": "seller",
                "shopName": f"Shop {stamp}",
            },
            expected_statuses=(201,),
        )
        _, seller_login = self.api(
            "POST",
            "/auth/login",
            {"email": seller_email, "password": password},
            expected_statuses=(200,),
        )
        seller_token = seller_login["token"]
        shop_id = seller_login["user"]["shopId"]
        self.assertTrue(shop_id)

        # 2) Seller creates a variant product
        _, product = self.api(
            "POST",
            "/products",
            {
                "name": f"Safe Product {stamp}",
                "description": "Safe demo item",
                "detail": "No restricted content",
                "shopId": shop_id,
                "variants": [
                    {"name": "Red", "sku": f"RED-{stamp}", "price": 120, "quantity": 10},
                    {"name": "Blue", "sku": f"BLUE-{stamp}", "price": 150, "quantity": 5},
                ],
            },
            token=seller_token,
            expected_statuses=(201,),
        )
        product_id = product.get("_id") or product.get("id")
        self.assertTrue(product_id)
        variants = product.get("variants") or []
        self.assertGreater(len(variants), 0)
        variant_id = variants[0].get("_id")
        self.assertTrue(variant_id)

        # 3) Register + login buyer
        self.api(
            "POST",
            "/auth/register",
            {
                "email": buyer_email,
                "password": password,
                "role": "buyer",
                "name": "Buyer Demo",
            },
            expected_statuses=(201,),
        )
        _, buyer_login = self.api(
            "POST",
            "/auth/login",
            {"email": buyer_email, "password": password},
            expected_statuses=(200,),
        )
        buyer_token = buyer_login["token"]
        buyer_id = buyer_login["user"]["id"]
        self.assertTrue(buyer_id)

        # 4) Buyer adds shipping address
        _, address = self.api(
            "POST",
            f"/users/{buyer_id}/addresses",
            {
                "label": "Home",
                "line1": "123 Test Street",
                "city": "HCM",
                "country": "VN",
                "isDefault": True,
            },
            token=buyer_token,
            expected_statuses=(200, 201),
        )
        self.assertTrue(address)

        # 5) Topup wallet + validate balance
        _, wallet_before = self.api(
            "GET",
            f"/payments/wallet/{buyer_id}",
            token=buyer_token,
            expected_statuses=(200,),
        )
        before_balance = float(wallet_before.get("balance", 0))

        self.api(
            "POST",
            f"/payments/wallet/{buyer_id}/topup",
            {"amount": 300, "source": "python_e2e"},
            token=buyer_token,
            expected_statuses=(201,),
        )
        _, wallet_after_topup = self.api(
            "GET",
            f"/payments/wallet/{buyer_id}",
            token=buyer_token,
            expected_statuses=(200,),
        )
        topup_balance = float(wallet_after_topup.get("balance", 0))
        self.assertGreaterEqual(topup_balance, before_balance + 300)

        # 6) Buyer add to cart (variant line)
        self.api(
            "POST",
            "/cart/add",
            {
                "userId": buyer_id,
                "productId": product_id,
                "variantId": variant_id,
                "quantity": 1,
            },
            token=buyer_token,
            expected_statuses=(200, 201),
        )
        _, cart = self.api(
            "GET",
            f"/cart/{buyer_id}",
            token=buyer_token,
            expected_statuses=(200,),
        )
        cart_lines = cart.get("products") or []
        self.assertTrue(any(str(line.get("variantId")) == str(variant_id) for line in cart_lines))

        # 7) Create order with wallet payment
        _, order = self.api(
            "POST",
            "/orders",
            {
                "userId": buyer_id,
                "paymentMethod": "wallet",
                "shippingAddress": address,
                "products": [
                    {
                        "productId": product_id,
                        "variantId": variant_id,
                        "variantName": variants[0].get("name"),
                        "quantity": 1,
                        "price": 120,
                        "shopId": shop_id,
                        "productName": product.get("name"),
                    }
                ],
            },
            token=buyer_token,
            extra_headers={"Idempotency-Key": f"order-{buyer_id}-{stamp}-1"},
            expected_statuses=(201,),
        )
        order_id = order["id"]
        self.assertTrue(order_id)

        # Duplicate create request with same idempotency key should return the same order
        _, duplicate_order = self.api(
            "POST",
            "/orders",
            {
                "userId": buyer_id,
                "paymentMethod": "wallet",
                "shippingAddress": address,
                "products": [
                    {
                        "productId": product_id,
                        "variantId": variant_id,
                        "variantName": variants[0].get("name"),
                        "quantity": 1,
                        "price": 120,
                        "shopId": shop_id,
                        "productName": product.get("name"),
                    }
                ],
            },
            token=buyer_token,
            extra_headers={"Idempotency-Key": f"order-{buyer_id}-{stamp}-1"},
            expected_statuses=(200, 201),
        )
        self.assertEqual(int(duplicate_order.get("id")), int(order_id))

        # Same key but different payload must be rejected
        with self.assertRaises(ApiError) as conflict:
            self.api(
                "POST",
                "/orders",
                {
                    "userId": buyer_id,
                    "paymentMethod": "wallet",
                    "shippingAddress": address,
                    "products": [
                        {
                            "productId": product_id,
                            "variantId": variant_id,
                            "variantName": variants[0].get("name"),
                            "quantity": 2,
                            "price": 120,
                            "shopId": shop_id,
                            "productName": product.get("name"),
                        }
                    ],
                },
                token=buyer_token,
                extra_headers={"Idempotency-Key": f"order-{buyer_id}-{stamp}-1"},
                expected_statuses=(200, 201),
            )
        self.assertEqual(conflict.exception.status, 409)

        # Wait for async payment to mark as paid (wallet should be quick)
        def is_paid():
            _, orders = self.api("GET", f"/orders/{buyer_id}", token=buyer_token, expected_statuses=(200,))
            if not orders:
                return False
            current = orders[0]
            return current.get("id") == order_id and current.get("status") in ("paid", "confirmed")

        self.assertTrue(self.wait_until(is_paid), "Order was not moved to paid/confirmed in time")

        _, wallet_after_pay = self.api(
            "GET",
            f"/payments/wallet/{buyer_id}",
            token=buyer_token,
            expected_statuses=(200,),
        )
        paid_balance = float(wallet_after_pay.get("balance", 0))
        self.assertLess(paid_balance, topup_balance)

        # 8) Cancel order and verify refund
        self.api(
            "POST",
            f"/orders/{order_id}/cancel",
            token=buyer_token,
            expected_statuses=(200,),
        )

        def refunded():
            _, wallet_now = self.api("GET", f"/payments/wallet/{buyer_id}", token=buyer_token, expected_statuses=(200,))
            return float(wallet_now.get("balance", 0)) >= topup_balance

        self.assertTrue(self.wait_until(refunded), "Wallet was not refunded after cancellation")

        _, txs = self.api(
            "GET",
            f"/payments/wallet/{buyer_id}/transactions?limit=20",
            token=buyer_token,
            expected_statuses=(200,),
        )
        refund_txs = [tx for tx in (txs or []) if tx.get("type") == "refund_order" and int(tx.get("order_id") or 0) == int(order_id)]
        self.assertGreaterEqual(len(refund_txs), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
