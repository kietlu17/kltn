import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "http://localhost:3000"
PASSWORD = "123456"


class TestFailure(Exception):
    pass


class Runner:
    def __init__(self, base_url, compose_project_dir):
        self.base_url = base_url.rstrip("/")
        self.compose_project_dir = compose_project_dir
        self.results = []

    def command(self, cmd, timeout=60, check=True):
        process = subprocess.run(
            cmd,
            cwd=self.compose_project_dir,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if check and process.returncode != 0:
            raise TestFailure(
                f"command failed: {cmd}\nSTDOUT={process.stdout}\nSTDERR={process.stderr}"
            )
        return process.stdout.strip(), process.stderr.strip(), process.returncode

    def compose(self, action, service, timeout=90):
        return self.command(f"docker compose {action} {service}", timeout=timeout, check=False)

    def api(self, method, path, data=None, token=None, expected=(200, 201), headers=None, timeout=15):
        request_headers = {}
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        if headers:
            request_headers.update(headers)

        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=request_headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
                if response.status not in expected:
                    raise TestFailure(f"{method} {path} expected {expected}, got {response.status}: {payload}")
                return response.status, payload
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8")
            try:
                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {"raw": raw}
            if err.code not in expected:
                raise TestFailure(f"{method} {path} expected {expected}, got {err.code}: {payload}")
            return err.code, payload

    def wait_for(self, callback, timeout=60, interval=1, label="condition"):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                ok, last = callback()
                if ok:
                    return last
            except Exception as exc:
                last = repr(exc)
            time.sleep(interval)
        raise TestFailure(f"timeout waiting for {label}; last={last}")

    def psql(self, db_name, sql):
        escaped_sql = sql.replace('"', '\\"')
        stdout, _, _ = self.command(
            f'docker exec postgres psql -U postgres -d {db_name} -t -A -c "{escaped_sql}"',
            timeout=30,
        )
        return stdout.strip()

    def pass_case(self, name, detail):
        self.results.append((name, "PASS", detail))
        print(f"PASS {name}: {detail}", flush=True)

    def fail_case(self, name, error):
        self.results.append((name, "FAIL", str(error)))
        print(f"FAIL {name}: {error}", flush=True)

    def setup_user_product(self, prefix, topup=1000, price=120):
        stamp = f"{prefix}_{int(time.time() * 1000)}"
        seller_email = f"seller_{stamp}@demo.com"
        buyer_email = f"buyer_{stamp}@demo.com"

        self.api(
            "POST",
            "/auth/register",
            {
                "email": seller_email,
                "password": PASSWORD,
                "role": "seller",
                "shopName": f"Shop {stamp}",
            },
            expected=(201,),
        )
        _, seller_login = self.api("POST", "/auth/login", {"email": seller_email, "password": PASSWORD})
        seller_token = seller_login["token"]
        shop_id = seller_login["user"]["shopId"]

        _, product = self.api(
            "POST",
            "/products",
            {
                "name": f"Safe Product {stamp}",
                "description": "Safe demo item",
                "detail": "Safe detail",
                "shopId": shop_id,
                "variants": [
                    {
                        "name": "Red",
                        "sku": f"RED-{stamp}",
                        "price": price,
                        "quantity": 20,
                    }
                ],
            },
            token=seller_token,
            expected=(201,),
        )
        product_id = product.get("_id") or product.get("id")
        variant_id = (product.get("variants") or [{}])[0].get("_id")

        self.wait_for(
            lambda: self.inventory_projection_ready(product_id),
            timeout=45,
            label="inventory projection from product.created",
        )

        self.api(
            "POST",
            "/auth/register",
            {
                "email": buyer_email,
                "password": PASSWORD,
                "role": "buyer",
                "name": "Buyer Demo",
            },
            expected=(201,),
        )
        _, buyer_login = self.api("POST", "/auth/login", {"email": buyer_email, "password": PASSWORD})
        buyer_token = buyer_login["token"]
        buyer_id = buyer_login["user"]["id"]

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
            expected=(200, 201),
        )

        self.api(
            "POST",
            f"/payments/wallet/{buyer_id}/topup",
            {"amount": topup, "source": prefix},
            token=buyer_token,
            expected=(200, 201),
            headers={"Idempotency-Key": f"topup-{stamp}"},
        )
        wallet = self.wait_for(
            lambda: self.wallet_has_at_least(buyer_id, buyer_token, topup),
            timeout=20,
            label="wallet topup",
        )

        return {
            "stamp": stamp,
            "seller_token": seller_token,
            "shop_id": shop_id,
            "buyer_token": buyer_token,
            "buyer_id": buyer_id,
            "address": address[-1] if isinstance(address, list) and address else address,
            "product_id": product_id,
            "variant_id": variant_id,
            "price": price,
            "wallet_before": float(wallet.get("balance", 0)),
        }

    def inventory_projection_ready(self, product_id):
        status, payload = self.api(
            "GET",
            f"/inventory/products/{product_id}",
            expected=(200, 404, 500, 502, 503),
            timeout=8,
        )
        if status != 200:
            return False, f"HTTP {status}: {payload}"
        return True, payload

    def wallet_has_at_least(self, buyer_id, token, amount):
        _, wallet = self.api("GET", f"/payments/wallet/{buyer_id}", token=token)
        return float(wallet.get("balance", 0)) >= amount, wallet

    def create_wallet_order(self, ctx, idempotency_suffix):
        item = {
            "productId": ctx["product_id"],
            "variantId": ctx["variant_id"],
            "variantName": "Red",
            "quantity": 1,
            "price": ctx["price"],
            "shopId": ctx["shop_id"],
            "productName": "Safe Product",
        }
        _, order = self.api(
            "POST",
            "/orders",
            {
                "userId": ctx["buyer_id"],
                "paymentMethod": "wallet",
                "shippingAddress": ctx["address"],
                "products": [item],
            },
            token=ctx["buyer_token"],
            expected=(201,),
            headers={"Idempotency-Key": f"order-{ctx['stamp']}-{idempotency_suffix}"},
            timeout=20,
        )
        return order

    def get_order(self, ctx, order_id):
        _, orders = self.api("GET", f"/orders/{ctx['buyer_id']}", token=ctx["buyer_token"])
        for order in orders:
            if int(order.get("id") or 0) == int(order_id):
                return order
        return None

    def wallet_balance(self, ctx):
        _, wallet = self.api("GET", f"/payments/wallet/{ctx['buyer_id']}", token=ctx["buyer_token"])
        return float(wallet.get("balance", 0))

    def wait_order_status(self, ctx, order_id, expected_status, timeout=60):
        return self.wait_for(
            lambda: (
                lambda order: (
                    bool(order and order.get("status") == expected_status),
                    order.get("status") if order else None,
                )
            )(self.get_order(ctx, order_id)),
            timeout=timeout,
            label=f"order {order_id} status {expected_status}",
        )

    def ensure_services_running(self):
        for service in [
            "kafka_e",
            "payment-service",
            "wallet-service",
            "order-service",
            "inventory-service",
            "product-service",
        ]:
            self.compose("start", service)
        time.sleep(8)

    def test_wallet_service_down(self):
        name = "1 wallet-service down during wallet checkout"
        try:
            ctx = self.setup_user_product("case1")
            self.compose("stop", "wallet-service")
            time.sleep(2)
            wallet_status, _ = self.api(
                "GET",
                f"/payments/wallet/{ctx['buyer_id']}",
                token=ctx["buyer_token"],
                expected=(500, 502, 503, 504),
                timeout=8,
            )
            order = self.create_wallet_order(ctx, "wallet-down")
            order_id = order["id"]
            self.wait_order_status(ctx, order_id, "payment_processing", timeout=40)

            self.compose("start", "wallet-service")
            time.sleep(8)
            self.wait_order_status(ctx, order_id, "paid", timeout=70)
            balance_after = self.wallet_balance(ctx)
            if balance_after >= ctx["wallet_before"]:
                raise TestFailure(f"wallet was not debited: {ctx['wallet_before']} -> {balance_after}")

            self.pass_case(
                name,
                f"wallet endpoint HTTP {wallet_status}; order {order_id} payment_processing -> paid; "
                f"balance {ctx['wallet_before']} -> {balance_after}",
            )
        except Exception as exc:
            self.fail_case(name, exc)
        finally:
            self.compose("start", "wallet-service")

    def test_order_service_down_after_debit(self):
        name = "2 order-service down after wallet debit"
        try:
            ctx = self.setup_user_product("case2")
            order = self.create_wallet_order(ctx, "order-down")
            order_id = order["id"]
            self.compose("stop", "order-service")
            time.sleep(10)
            balance_after_debit = self.wallet_balance(ctx)
            if balance_after_debit >= ctx["wallet_before"]:
                raise TestFailure(
                    f"wallet was not debited while order-service down: "
                    f"{ctx['wallet_before']} -> {balance_after_debit}"
                )
            outbox_state = self.psql(
                "payment_service",
                (
                    "select status || '|' || count(*) "
                    "from outbox_events "
                    f"where aggregate_id='{order_id}' and topic='payment.succeeded' "
                    "group by status order by status;"
                ),
            )
            self.compose("start", "order-service")
            time.sleep(8)
            self.wait_order_status(ctx, order_id, "paid", timeout=70)
            self.pass_case(
                name,
                f"wallet debited {ctx['wallet_before']} -> {balance_after_debit}; "
                f"payment.succeeded outbox before restart: {outbox_state or 'not visible'}; "
                f"order {order_id} -> paid",
            )
        except Exception as exc:
            self.fail_case(name, exc)
        finally:
            self.compose("start", "order-service")

    def test_kafka_down_outbox_retry(self):
        name = "3 Kafka down with outbox-producing action"
        try:
            ctx = self.setup_user_product("case3")
            source = f"case3_kafka_down_{ctx['stamp']}"
            self.compose("stop", "kafka_e")
            time.sleep(8)
            self.api(
                "POST",
                f"/payments/wallet/{ctx['buyer_id']}/topup",
                {"amount": 77, "source": source},
                token=ctx["buyer_token"],
                expected=(200, 201),
                headers={"Idempotency-Key": f"topup-kafka-down-{ctx['stamp']}"},
                timeout=15,
            )
            failed_or_pending = self.wait_for(
                lambda: (
                    lambda value: (value in {"failed", "pending"}, value)
                )(
                    self.psql(
                        "wallet_service",
                        (
                            "select status from outbox_events "
                            f"where payload::text like '%{source}%' "
                            "order by created_at desc limit 1;"
                        ),
                    )
                ),
                timeout=25,
                label="wallet outbox failed/pending while Kafka is down",
            )
            self.compose("start", "kafka_e")
            time.sleep(20)
            published = self.wait_for(
                lambda: (
                    lambda value: (value == "published", value)
                )(
                    self.psql(
                        "wallet_service",
                        (
                            "select status from outbox_events "
                            f"where payload::text like '%{source}%' "
                            "order by created_at desc limit 1;"
                        ),
                    )
                ),
                timeout=90,
                interval=3,
                label="wallet outbox published after Kafka restarts",
            )
            self.pass_case(
                name,
                f"outbox was {failed_or_pending} while Kafka down, then {published}",
            )
        except Exception as exc:
            self.fail_case(name, exc)
        finally:
            self.compose("start", "kafka_e")
            time.sleep(10)

    def test_wallet_down_after_delivered(self):
        name = "4 wallet-service down after delivered"
        try:
            self.ensure_services_running()
            ctx = self.setup_user_product("case4")
            order = self.create_wallet_order(ctx, "settlement")
            order_id = order["id"]
            self.wait_order_status(ctx, order_id, "paid", timeout=70)

            self.api("POST", f"/orders/{order_id}/confirm", token=ctx["seller_token"], expected=(200, 201))
            _, shipment_payload = self.api(
                "POST",
                f"/orders/{order_id}/shipments",
                {"carrier": "mock_carrier"},
                token=ctx["seller_token"],
                expected=(200, 201),
            )
            shipment = shipment_payload.get("shipment") or shipment_payload
            tracking_code = shipment.get("tracking_code") or shipment.get("trackingCode")
            if not tracking_code:
                raise TestFailure(f"missing tracking code in shipment payload: {shipment_payload}")

            self.compose("stop", "wallet-service")
            time.sleep(2)
            self.api(
                "POST",
                "/orders/shipping/callback",
                {
                    "trackingCode": tracking_code,
                    "status": "delivered",
                    "metadata": {"source": "resilience_test"},
                },
                expected=(200, 201),
            )
            delivered_order = self.get_order(ctx, order_id)
            if not delivered_order or delivered_order.get("status") != "delivered":
                raise TestFailure(f"order was not delivered: {delivered_order}")

            jobs_while_down = self.psql(
                "wallet_service",
                f"select coalesce(count(*),0) from settlement_jobs where order_id={order_id};",
            )
            if int(jobs_while_down or "0") != 0:
                raise TestFailure(f"settlement job exists while wallet-service is down: {jobs_while_down}")

            self.compose("start", "wallet-service")
            time.sleep(8)
            created_status = self.wait_for(
                lambda: (
                    lambda value: (bool(value), value)
                )(
                    self.psql(
                        "wallet_service",
                        f"select status from settlement_jobs where order_id={order_id} order by id desc limit 1;",
                    )
                ),
                timeout=60,
                label="settlement job created",
            )
            settled_status = self.wait_for(
                lambda: (
                    lambda value: (value == "settled", value)
                )(
                    self.psql(
                        "wallet_service",
                        f"select status from settlement_jobs where order_id={order_id} order by id desc limit 1;",
                    )
                ),
                timeout=90,
                interval=3,
                label="settlement job settled",
            )
            _, shop_balance = self.api(
                "GET",
                f"/payments/wallet/shop/{ctx['shop_id']}/balance",
                token=ctx["seller_token"],
            )
            available = shop_balance.get("sellerBalance", {}).get("availableBalance")
            self.pass_case(
                name,
                f"order {order_id} delivered with no job while down; job {created_status} -> "
                f"{settled_status}; shop available {available}",
            )
        except Exception as exc:
            self.fail_case(name, exc)
        finally:
            self.compose("start", "wallet-service")

    def test_inventory_service_down_checkout(self):
        name = "5 inventory-service down during checkout"
        try:
            ctx = self.setup_user_product("case5")
            self.compose("stop", "inventory-service")
            time.sleep(3)
            item = {
                "productId": ctx["product_id"],
                "variantId": ctx["variant_id"],
                "variantName": "Red",
                "quantity": 1,
                "price": ctx["price"],
                "shopId": ctx["shop_id"],
                "productName": "Safe Product",
            }
            status, payload = self.api(
                "POST",
                "/orders",
                {
                    "userId": ctx["buyer_id"],
                    "paymentMethod": "wallet",
                    "shippingAddress": ctx["address"],
                    "products": [item],
                },
                token=ctx["buyer_token"],
                headers={"Idempotency-Key": f"order-{ctx['stamp']}-inventory-down"},
                expected=(500, 502, 503, 504),
                timeout=20,
            )
            self.pass_case(name, f"checkout failed immediately with HTTP {status}: {payload}")
        except Exception as exc:
            self.fail_case(name, exc)
        finally:
            self.compose("start", "inventory-service")

    def run_all(self):
        self.ensure_services_running()
        self.test_wallet_service_down()
        self.test_order_service_down_after_debit()
        self.test_kafka_down_outbox_retry()
        self.test_wallet_down_after_delivered()
        self.test_inventory_service_down_checkout()
        self.ensure_services_running()

        print("\nSUMMARY")
        for name, status, detail in self.results:
            print(f"{status}: {name} -- {detail}")

        if any(status == "FAIL" for _, status, _ in self.results):
            return 1
        return 0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run checkout resilience tests by stopping/starting docker compose services."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API gateway base URL")
    parser.add_argument(
        "--compose-dir",
        default=".",
        help="Directory that contains docker-compose.yml",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    runner = Runner(args.base_url, args.compose_dir)
    return runner.run_all()


if __name__ == "__main__":
    sys.exit(main())
