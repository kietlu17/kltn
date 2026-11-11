"""Conversation invariants checked across product verticals.

Each scenario template is a short multi-turn conversation whose semantic turns
are scripted (what the decide model would return), so the run is deterministic
and tests the graph's mechanics: carry-over, relaxation, references and
multi-task handling. Templates are instantiated for every vertical in
VERTICALS, so a fix that only works for one kind of product shows up as a
failure elsewhere.

Run the matrix report:  python tests/test_invariants.py --report
Run as tests:           python -m unittest tests.test_invariants -v
"""

import asyncio
import re
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas import SemanticConstraint, SemanticReference, SemanticTask, SemanticTurn  # noqa: E402
from test_graph import state as base_state  # noqa: E402
from test_production import SemanticModels  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from app.config import AgenticSettings  # noqa: E402
from app.graph import AgenticShoppingGraph  # noqa: E402


# -- catalog -------------------------------------------------------------------

def _cat(index: int) -> str:
    return f"{index:x}".rjust(24, "c")


CATEGORIES = {
    "loa": (_cat(1), "Điện tử › Loa Bluetooth"),
    "loa_thanh": (_cat(2), "Điện tử › Loa thanh"),
    "dien_thoai": (_cat(3), "Điện tử › Điện thoại"),
    "op_lung": (_cat(4), "Điện tử › Phụ kiện › Ốp lưng"),
    "laptop": (_cat(5), "Điện tử › Laptop"),
    "balo": (_cat(6), "Thời trang › Balo"),
    "ao_khoac": (_cat(7), "Thời trang › Áo khoác"),
    "ao_thun": (_cat(8), "Thời trang › Áo thun"),
    "giay": (_cat(9), "Thời trang › Giày thể thao"),
    "dep": (_cat(10), "Thời trang › Dép"),
    "noi_com": (_cat(11), "Gia dụng › Nồi cơm điện"),
    "noi_chien": (_cat(12), "Gia dụng › Nồi chiên không dầu"),
}

_PRODUCTS: list[dict] = []


def _product(category: str, name: str, brand: str, price: int, specs: dict | None = None) -> str:
    product_id = f"{len(_PRODUCTS) + 1:x}".rjust(24, "a")
    _PRODUCTS.append({
        "id": product_id,
        "name": name,
        "brand": brand,
        "price": price,
        "categoryId": CATEGORIES[category][0],
        "category": category,
        "imageUrl": "",
        "shopId": "shop-1",
        "url": f"/product/{product_id}",
        "description": name,
        "specifications": [{"name": key, "value": value} for key, value in (specs or {}).items()],
        "variants": [{
            "id": product_id[:-1] + "f",
            "name": "Mặc định",
            "price": price,
            "availableStock": 10,
            "imageUrl": "",
        }],
    })
    return product_id


for _args in (
    ("loa", "Loa Bluetooth JBL Clip 5", "JBL", 1_790_000, {"Chống nước": "IP67", "Thời lượng pin": "12 giờ"}),
    ("loa", "Loa Bluetooth JBL Flip 6", "JBL", 2_690_000, {"Chống nước": "IP67", "Thời lượng pin": "12 giờ"}),
    ("loa", "Loa Bluetooth Anker Soundcore Boom Go 3i", "Anker", 1_290_000, {"Chống nước": "IP68", "Thời lượng pin": "15 giờ"}),
    ("loa", "Loa Bluetooth Xiaomi Sound Outdoor", "Xiaomi", 1_020_000, {"Chống nước": "IP67"}),
    ("loa_thanh", "Bộ loa thanh Sony HT-S40R 600W", "Sony", 6_990_000, {}),
    ("dien_thoai", "Điện thoại Samsung Galaxy A35 5G", "Samsung", 7_990_000, {"RAM": "8 GB", "Pin": "5000 mAh"}),
    ("dien_thoai", "Điện thoại Samsung Galaxy S24", "Samsung", 18_990_000, {"RAM": "8 GB"}),
    ("dien_thoai", "Điện thoại iPhone 15 128GB", "Apple", 19_990_000, {"RAM": "6 GB"}),
    ("dien_thoai", "Điện thoại Xiaomi Redmi 13", "Xiaomi", 4_290_000, {"RAM": "8 GB", "Pin": "5030 mAh"}),
    ("dien_thoai", "Điện thoại OPPO A79 5G", "OPPO", 6_490_000, {"RAM": "8 GB", "Pin": "5000 mAh"}),
    ("op_lung", "Ốp lưng iPhone 15 Apple MagSafe", "Apple", 1_290_000, {}),
    ("laptop", "Laptop Asus Vivobook 15 i5", "Asus", 15_990_000, {"RAM": "16 GB"}),
    ("laptop", "Laptop Lenovo IdeaPad Slim 3", "Lenovo", 13_990_000, {"RAM": "16 GB"}),
    ("laptop", "Laptop Dell Inspiron 15", "Dell", 17_490_000, {"RAM": "8 GB"}),
    ("laptop", "Laptop MacBook Air M3", "Apple", 27_990_000, {"RAM": "16 GB"}),
    ("balo", "Balo laptop Dell Essential 15", "Dell", 690_000, {}),
    ("ao_khoac", "Áo khoác gió nam Yody", "Yody", 399_000, {"Chất liệu": "Polyester"}),
    ("ao_khoac", "Áo khoác bomber nam Yody", "Yody", 459_000, {"Chất liệu": "Kaki"}),
    ("ao_khoac", "Áo khoác Uniqlo chống tia UV", "Uniqlo", 784_000, {"Chất liệu": "Polyester"}),
    ("ao_thun", "Áo thun nam Uniqlo Dry-EX", "Uniqlo", 293_000, {"Chất liệu": "Polyester"}),
    ("giay", "Giày thể thao Biti's Hunter X", "Biti's", 899_000, {}),
    ("giay", "Giày chạy bộ Adidas Duramo", "Adidas", 1_590_000, {}),
    ("giay", "Giày Nike Air Zoom Pegasus", "Nike", 3_290_000, {}),
    ("dep", "Dép Nike Victori One", "Nike", 790_000, {}),
    ("noi_com", "Nồi cơm điện Sharp 1.8 lít", "Sharp", 890_000, {"Dung tích": "1.8 lít"}),
    ("noi_com", "Nồi cơm điện tử Toshiba 1.8 lít", "Toshiba", 1_790_000, {"Dung tích": "1.8 lít"}),
    ("noi_com", "Nồi cơm điện Cuckoo 1 lít", "Cuckoo", 1_190_000, {"Dung tích": "1 lít"}),
    ("noi_chien", "Nồi chiên không dầu Philips 4.1 lít", "Philips", 2_590_000, {"Dung tích": "4.1 lít"}),
):
    _product(*_args)

BY_ID = {item["id"]: item for item in _PRODUCTS}


def _words(value: str) -> set[str]:
    return set(re.findall(r"\w+", value.casefold()))


class CatalogRetriever:
    """Behaves like the vector search: filters are applied, everything that
    passes them comes back ranked by word overlap (never an empty list just
    because the words differ)."""

    def __init__(self):
        self.calls = []

    async def search(self, query, filters, limit=None, sort_by="relevance"):
        self.calls.append((query, filters.model_dump()))
        brand = (filters.brand or "").casefold()
        hits = []
        for product in _PRODUCTS:
            if filters.category_ids and product["categoryId"] not in filters.category_ids:
                continue
            if brand and product["brand"].casefold() != brand:
                continue
            if filters.max_price is not None and product["price"] > filters.max_price:
                continue
            if filters.min_price is not None and product["price"] < filters.min_price:
                continue
            score = len(_words(query) & _words(f"{product['name']} {product['brand']}"))
            hits.append({
                "productId": product["id"],
                "vectorScore": score,
                "payload": {"text": f"Tên sản phẩm: {product['name']}", "brand": product["brand"],
                            "minPrice": product["price"]},
            })
        hits.sort(key=lambda item: -item["vectorScore"])
        return hits[: limit or 30]

    async def product_context(self, product_id):
        product = BY_ID.get(product_id)
        if not product:
            return None
        return {"productId": product_id, "text": product["name"], "minPrice": product["price"],
                "maxPrice": product["price"]}


class CatalogMarketplace:
    def __init__(self, cart_ids: list[str] | None = None):
        self.cart_writes = []
        self.cart_ids = list(cart_ids or [])

    async def cart(self, _user_id):
        return {"products": [
            {"productId": product_id, "variantId": BY_ID[product_id]["variants"][0]["id"], "quantity": 1}
            for product_id in self.cart_ids
        ]}

    async def product(self, product_id):
        product = BY_ID.get(product_id)
        return dict(product) if product else None

    async def addresses(self, _user_id):
        return [{"_id": "d" * 24, "address": "Hà Nội", "isDefault": True}]

    async def categories(self):
        return [{"id": category_id, "name": name} for category_id, name in CATEGORIES.values()]

    async def hydrate_products(self, hits, _filters, limit):
        return [dict(BY_ID[hit["productId"]]) for hit in hits[:limit] if hit["productId"] in BY_ID]

    async def product_card(self, product_id, filters=None):
        product = BY_ID.get(product_id)
        return dict(product) if product else None


# -- verticals -----------------------------------------------------------------

@dataclass
class Vertical:
    key: str
    kind: str                 # product_type the model would emit
    category: str             # key in CATEGORIES
    budget: int
    in_budget_brand: str      # has products inside budget and category
    trap_brand: str           # exists only outside budget or in a sibling category
    soft_spec: tuple[str, str]
    second_spec: tuple[str, str]
    other_kind: str           # a different product for the "switch" template
    other_category: str


VERTICALS = [
    Vertical("loa", "loa bluetooth", "loa", 2_000_000, "JBL", "Sony",
             ("water_resistant", "chống nước"), ("battery_life", "pin 8 giờ"), "nồi cơm điện", "noi_com"),
    Vertical("dien_thoai", "điện thoại", "dien_thoai", 8_000_000, "Samsung", "Apple",
             ("battery", "pin trâu"), ("camera", "chụp đẹp"), "laptop", "laptop"),
    Vertical("laptop", "laptop", "laptop", 16_000_000, "Asus", "Dell",
             ("weight", "nhẹ"), ("ram", "16GB"), "điện thoại", "dien_thoai"),
    Vertical("ao_khoac", "áo khoác", "ao_khoac", 500_000, "Yody", "Uniqlo",
             ("material", "thoáng mát"), ("style", "trẻ trung"), "giày thể thao", "giay"),
    Vertical("giay", "giày thể thao", "giay", 2_000_000, "Adidas", "Nike",
             ("weight", "nhẹ"), ("style", "chạy bộ"), "áo khoác", "ao_khoac"),
    Vertical("noi_com", "nồi cơm điện", "noi_com", 2_000_000, "Sharp", "Philips",
             ("capacity_note", "nấu cho 4 người"), ("feature", "dễ vệ sinh"), "loa bluetooth", "loa"),
]


# -- conversation runner --------------------------------------------------------

@dataclass
class Turn:
    message: str
    semantic: SemanticTurn
    result: dict = field(default_factory=dict)


class ScriptedModels(SemanticModels):
    async def answer(self, message, plan, result, products, history):
        self.answer_calls += 1
        names = "; ".join(item.get("name", "") for item in products)
        return f"[{len(products)} sp] {names}"


_PERSISTED = (
    "history", "search_context", "last_search", "pending_action", "focused_products",
    "active_product_id", "selected_options", "shopping_phase", "clarify_count", "last_clarify_key",
)


async def converse(turns: list[Turn], cart_ids: list[str] | None = None) -> list[Turn]:
    """Runs the turns like the API does: each turn starts from the state the
    previous one committed (see main._open_turn/_commit_turn)."""
    models = ScriptedModels()
    # cart_ids may be a function of the turns run so far, called before each
    # turn (a cart holding the product the first turn showed).
    marketplace = CatalogMarketplace(None if callable(cart_ids) else cart_ids)
    agent = AgenticShoppingGraph(
        AgenticSettings(gemini_api_key="test", web_search_enabled=False, rerank_mode="none"),
        models,
        CatalogRetriever(),
        marketplace,
        checkpointer=MemorySaver(),
    )
    previous: dict = {}
    for index, turn in enumerate(turns):
        if callable(cart_ids):
            marketplace.cart_ids = list(cart_ids(turns[:index]))
        models.turn = turn.semantic
        current = base_state(turn.message)
        current.update({key: previous[key] for key in _PERSISTED if key in previous})
        current.update({"semantic_turn": {}, "last_search": previous.get("last_search", {})})
        result = await agent.graph.ainvoke(
            current, config={"configurable": {"thread_id": f"inv-{id(turns)}-{index}"}}
        )
        turn.result = result
        previous = {**previous, **{key: result[key] for key in _PERSISTED if key in result}}
        previous["history"] = [
            *previous.get("history", []),
            {"role": "user", "content": turn.message},
            {"role": "assistant", "content": result.get("answer", "")},
        ][-12:]
    return turns


# -- invariants ----------------------------------------------------------------

def shown(turn: Turn) -> list[dict]:
    return list(turn.result.get("products") or [])


def check_category(turn: Turn, allowed: set[str]) -> str | None:
    wrong = [item["name"] for item in shown(turn) if item.get("category") not in allowed]
    return f"sai loại sản phẩm: {wrong}" if wrong else None


def check_budget(turn: Turn, budget: int, tolerance: float = 1.2) -> str | None:
    over = [f"{item['name']} ({item['price']:,})" for item in shown(turn) if item["price"] > budget * tolerance]
    return f"vượt ngân sách {budget:,}: {over}" if over else None


def check_filter_budget(turn: Turn, budget: int) -> str | None:
    filters = (turn.result.get("tool_result") or {}).get("filters") or {}
    if filters.get("max_price") is None:
        return "bộ lọc mất ngân sách (max_price=None)"
    return None


def check_spec_kept(turn: Turn, key: str) -> str | None:
    filters = (turn.result.get("tool_result") or {}).get("filters") or {}
    keys = [item.get("key") for item in filters.get("spec_constraints") or []]
    return None if key in keys else f"mất tiêu chí '{key}' (còn: {keys})"


def check_reference(turn: Turn, product_id: str) -> str | None:
    plan = turn.result.get("plan") or {}
    ids = list(plan.get("product_ids") or [])
    if product_id in ids:
        return None
    clarification = str((turn.result.get("tool_result") or {}).get("clarification") or "")
    if clarification:
        return None
    return f"không xác định được sản phẩm được nhắc (route={turn.result.get('route')}, ids={ids})"


def check_all_tasks_handled(turn: Turn, labels: list[str]) -> str | None:
    answer = str(turn.result.get("answer") or "")
    plan = turn.result.get("plan") or {}
    missing = []
    for label in labels:
        if label == "so sánh sản phẩm" and len(plan.get("product_ids") or []) >= 2:
            continue
        if label not in answer:
            missing.append(label)
    return f"yêu cầu bị bỏ mà không báo: {missing}" if missing else None


def check_no_leak(turn: Turn) -> str | None:
    filters = (turn.result.get("tool_result") or {}).get("filters") or {}
    if filters.get("max_price") is not None or filters.get("brand"):
        return f"tiêu chí của sản phẩm cũ bị mang sang: price={filters.get('max_price')}, brand={filters.get('brand')}"
    return None


# -- scenario templates --------------------------------------------------------

def _search(query, *constraints, refs=(), focus="replace", action="continue", web=False):
    return SemanticTurn(
        tasks=[SemanticTask(intent="product_search", query=query, constraints=list(constraints),
                            references=list(refs), web_research=web)],
        conversation_action=action, focus_update=focus, confidence=0.9,
    )


def _c(key, value, operator="eq", strength="hard"):
    return SemanticConstraint(key=key, value=value, operator=operator, strength=strength)


def _first_turn(v: Vertical, *extra):
    return Turn(
        f"Mình muốn mua {v.kind}, tầm {v.budget // 1000}k",
        _search(v.kind, _c("product_type", v.kind), _c("max_price", v.budget, "lte"), *extra, action="new"),
    )


def tpl_add_brand(v: Vertical):
    """Budget given first, a brand only named later (the loa/Sony case)."""
    turns = [_first_turn(v), Turn(f"Có mẫu nào của {v.trap_brand} không?",
                                  _search(f"{v.kind} {v.trap_brand}", _c("brand", v.trap_brand)))]

    def checks(done):
        last = done[-1]
        allowed = {v.category}
        return [check_filter_budget(last, v.budget), check_budget(last, v.budget), check_category(last, allowed)]

    return turns, checks


def tpl_two_brands(v: Vertical):
    """Two brands in one message ("JBL với Sony")."""
    turns = [_first_turn(v), Turn(f"Mình xem {v.in_budget_brand} với {v.trap_brand}, mẫu nào đáng mua?",
                                  _search(f"{v.kind} {v.in_budget_brand} {v.trap_brand}",
                                          _c("brand", [v.in_budget_brand, v.trap_brand], "any")))]

    def checks(done):
        last = done[-1]
        return [check_filter_budget(last, v.budget), check_budget(last, v.budget), check_category(last, {v.category})]

    return turns, checks


def tpl_add_spec(v: Vertical):
    """A wish in turn 2, another in turn 3: both must still be there."""
    k1, v1 = v.soft_spec
    k2, v2 = v.second_spec
    turns = [
        _first_turn(v),
        Turn(f"Ưu tiên {v1}", _search(f"{v.kind} {v1}", _c(k1, v1, strength="soft"))),
        Turn(f"Thêm nữa là {v2}", _search(f"{v.kind} {v2}", _c(k2, v2, strength="soft"))),
    ]

    def checks(done):
        last = done[-1]
        return [check_spec_kept(last, k1), check_filter_budget(last, v.budget), check_category(last, {v.category})]

    return turns, checks


def tpl_no_match(v: Vertical):
    """Nothing matches: relaxation may loosen brand/spec, never the kind."""
    turns = [Turn(
        f"{v.kind} {v.trap_brand} dưới {v.budget // 1000}k",
        _search(f"{v.kind} {v.trap_brand}", _c("product_type", v.kind), _c("max_price", v.budget, "lte"),
                _c("brand", v.trap_brand), action="new"),
    )]

    def checks(done):
        last = done[-1]
        return [check_category(last, {v.category}), check_budget(last, v.budget)]

    return turns, checks


def tpl_reference_earlier(v: Vertical):
    """A product shown two turns ago is named again ("mẫu Sony này")."""
    in_cat = [item for item in _PRODUCTS if item["category"] == v.category and item["price"] <= v.budget]
    target = in_cat[0]
    brand_word = target["brand"]
    turns = [
        _first_turn(v),
        Turn(f"Có {v.other_kind} không?", _search(v.other_kind, _c("product_type", v.other_kind), action="switch")),
        Turn(
            f"So sánh mẫu {brand_word} lúc nãy với một mẫu khác cùng tầm giá",
            SemanticTurn(
                tasks=[SemanticTask(intent="compare_products", query=f"so sánh {brand_word}",
                                    references=[SemanticReference(kind="name", name=brand_word)],
                                    web_research=True)],
                conversation_action="resume", confidence=0.85,
            ),
        ),
    ]

    def checks(done):
        return [check_reference(done[-1], target["id"])]

    return turns, checks


def tpl_multi_intent(v: Vertical):
    """'Gợi ý giúp mình. À, cái này có X không?' — both parts must be served."""
    turns = [
        _first_turn(v),
        Turn(
            "Gợi ý giúp mình mẫu nên mua. À, mẫu đầu có bảo hành không?",
            SemanticTurn(
                tasks=[
                    SemanticTask(intent="product_detail", references=[SemanticReference(kind="focused_index", index=1)],
                                 requested_attributes=["bảo hành"]),
                    SemanticTask(intent="compare_products", query="nên mua mẫu nào"),
                ],
                conversation_action="continue", confidence=0.9,
            ),
        ),
    ]

    def checks(done):
        return [check_all_tasks_handled(done[-1], ["so sánh sản phẩm"])]

    return turns, checks


def tpl_switch_kind(v: Vertical):
    """A new kind of product starts fresh: no budget or brand leaks over."""
    turns = [
        Turn(f"{v.kind} {v.in_budget_brand} tầm {v.budget // 1000}k",
             _search(v.kind, _c("product_type", v.kind), _c("max_price", v.budget, "lte"),
                     _c("brand", v.in_budget_brand), action="new")),
        Turn(f"Còn {v.other_kind} thì sao?", _search(v.other_kind, _c("product_type", v.other_kind), action="switch")),
    ]

    def checks(done):
        last = done[-1]
        return [check_no_leak(last), check_category(last, {v.other_category})]

    return turns, checks


def check_brand_reported(turn: Turn, brand: str, category: str) -> str | None:
    """A brand the catalog carries in this category is either shown or listed
    in brandAvailability, so the reply cannot claim the shop lacks it."""
    in_catalog = [item for item in _PRODUCTS if item["category"] == category and item["brand"] == brand]
    if not in_catalog:
        return None
    if any(item["brand"] == brand for item in shown(turn)):
        return None
    listed = ((turn.result.get("tool_result") or {}).get("brandAvailability") or {}).get(brand)
    return None if listed else f"{brand} có trong catalog nhưng không được báo cho model"


def check_clarified(turn: Turn) -> str | None:
    result = turn.result.get("tool_result") or {}
    return None if result.get("clarification") else f"không hỏi lại phạm vi thanh toán (route={turn.result.get('route')})"


def check_checkout_selection(turn: Turn, expected: list[str]) -> str | None:
    selected = (turn.result.get("tool_result") or {}).get("selectedProductIds") or []
    got = sorted(item.split("::")[0] for item in selected)
    return None if got == sorted(expected) else f"thanh toán sai sản phẩm: {got} (cần {sorted(expected)})"


def tpl_brand_coverage(v: Vertical):
    """Two brands asked, only two results shown: a brand cut from the top-k
    must still be reported as available."""
    turn = SemanticTurn(
        tasks=[SemanticTask(intent="product_search", query=f"{v.kind} {v.trap_brand} {v.in_budget_brand}",
                            constraints=[_c("product_type", v.kind),
                                         _c("brand", [v.trap_brand, v.in_budget_brand], "any")],
                            result_limit=1)],
        conversation_action="new", focus_update="replace", confidence=0.9,
    )
    turns = [Turn(f"{v.kind} {v.trap_brand} hay {v.in_budget_brand}?", turn)]

    def checks(done):
        return [check_brand_reported(done[-1], brand, v.category) for brand in (v.trap_brand, v.in_budget_brand)]

    return turns, checks


def _checkout(message: str):
    return SemanticTurn(tasks=[SemanticTask(intent="checkout", query=message)],
                        conversation_action="continue", confidence=0.9)


def tpl_partial_checkout(v: Vertical):
    """Cart holds the product discussed plus an older one from another kind:
    "thanh toán luôn" asks which, "chỉ <kind>" pays only that line."""
    older = next(item for item in _PRODUCTS if item["category"] == v.other_category)
    head = v.kind.split()[0]
    turns = [
        _first_turn(v),
        Turn("thanh toán luôn", _checkout("thanh toán luôn")),
        Turn(f"chỉ thanh toán {head} thôi", _checkout(f"chỉ thanh toán {head}")),
    ]

    def discussed(done) -> str:
        # The product the first turn showed (as if added to the cart from it).
        return str(shown(done[0])[0]["id"]) if done and shown(done[0]) else ""

    def cart(done):
        return [item for item in (discussed(done), older["id"]) if item] if done else [older["id"]]

    def checks(done):
        return [check_clarified(done[1]), check_checkout_selection(done[2], [discussed(done)])]

    return turns, checks, cart


TEMPLATES = {
    "brand_coverage": tpl_brand_coverage,
    "partial_checkout": tpl_partial_checkout,
    "add_brand": tpl_add_brand,
    "two_brands": tpl_two_brands,
    "add_spec": tpl_add_spec,
    "no_match": tpl_no_match,
    "reference_earlier": tpl_reference_earlier,
    "multi_intent": tpl_multi_intent,
    "switch_kind": tpl_switch_kind,
}


async def run_scenario(template: str, vertical: Vertical) -> list[str]:
    turns, checks, *cart = TEMPLATES[template](vertical)
    try:
        done = await converse(turns, cart[0] if cart else None)
    except Exception as error:  # a crash is a failure, not a test error
        return [f"lỗi chạy: {type(error).__name__}: {str(error)[:160]}"]
    return [problem for problem in checks(done) if problem]


# -- unittest entry --------------------------------------------------------------

class ConversationInvariantTests(unittest.IsolatedAsyncioTestCase):
    async def test_matrix(self):
        for template in TEMPLATES:
            for vertical in VERTICALS:
                with self.subTest(template=template, vertical=vertical.key):
                    problems = await run_scenario(template, vertical)
                    self.assertEqual(problems, [], "; ".join(problems))


# -- report ----------------------------------------------------------------------

async def _report() -> int:
    failures = 0
    header = f"{'template':<18}" + "".join(f"{v.key:<12}" for v in VERTICALS)
    print(header)
    details = []
    for template in TEMPLATES:
        row = f"{template:<18}"
        for vertical in VERTICALS:
            problems = await run_scenario(template, vertical)
            row += f"{'FAIL' if problems else 'ok':<12}"
            if problems:
                failures += 1
                details.append(f"  {template}/{vertical.key}: " + "; ".join(problems))
        print(row)
    total = len(TEMPLATES) * len(VERTICALS)
    print(f"\n{total - failures}/{total} pass\n")
    print("\n".join(details))
    return failures


if __name__ == "__main__":
    if "--report" in sys.argv:
        sys.stdout.reconfigure(encoding="utf-8")
        raise SystemExit(1 if asyncio.run(_report()) else 0)
    unittest.main()
