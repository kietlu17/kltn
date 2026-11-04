import unittest

from app.search_parser import (
    LOOSE_CONFIDENCE,
    STRICT_CONFIDENCE,
    parse_policy_turn,
    parse_search_turn,
)


def constraints(message, **kwargs):
    turn = parse_search_turn(message, **kwargs)
    if turn is None:
        return None
    return {(item.key, item.operator): item.value for item in turn.tasks[0].constraints}


class SearchParserTests(unittest.TestCase):
    def test_price_color_and_size_are_parsed(self):
        self.assertEqual(
            constraints("tìm tai nghe bluetooth dưới 500k"),
            {("product_type", "eq"): "tai nghe bluetooth", ("price", "lte"): 500000},
        )
        self.assertEqual(
            constraints("áo thun nam màu đen size L"),
            {
                ("product_type", "eq"): "áo thun nam",
                ("color", "any"): ["đen"],
                ("size", "any"): ["L"],
            },
        )
        self.assertEqual(
            constraints("bàn phím cơ từ 1 đến 2 triệu"),
            {
                ("product_type", "eq"): "bàn phím cơ",
                ("price", "gte"): 1_000_000,
                ("price", "lte"): 2_000_000,
            },
        )
        self.assertEqual(constraints("iphone 13 trên 10tr")[("price", "gte")], 10_000_000)
        around = constraints("nồi chiên không dầu 1.5 triệu")
        self.assertEqual(around[("product_type", "eq")], "nồi chiên không dầu")
        self.assertEqual(
            (around[("price", "gte")], around[("price", "lte")]), (1_200_000, 1_800_000)
        )

    def test_product_words_that_look_like_fillers_survive(self):
        self.assertEqual(
            constraints("shop có tai nghe không dây không?")[("product_type", "eq")],
            "tai nghe không dây",
        )
        self.assertEqual(
            constraints("đồ gia dụng khoảng 300k")[("product_type", "eq")], "đồ gia dụng"
        )
        self.assertEqual(constraints("đèn ngủ màu vàng")[("color", "any")], ["vàng"])
        self.assertEqual(constraints("tim tai nghe duoi 500k")[("price", "lte")], 500000)

    def test_shop_chat_abbreviations_are_expanded(self):
        turn = parse_search_turn("ip 15 pro max")
        self.assertEqual(turn.tasks[0].query, "iphone 15 pro max")
        self.assertEqual(
            constraints("nồi chiên ko dầu loại to")[("product_type", "eq")], "nồi chiên không dầu to"
        )
        self.assertEqual(constraints("tai nghe 500k")[("product_type", "eq")], "tai nghe")

    def test_non_search_turns_are_left_to_the_model(self):
        for message in [
            "chính sách đổi trả thế nào",
            "so sánh 2 cái đầu",
            "cái thứ hai giá bao nhiêu",
            "xin chào",
            "màu đen",
            "dưới 500k",
            "tôi muốn mua cái này",
            "cái gì cũng được",
            "kiểm tra đơn hàng của tôi",
        ]:
            self.assertIsNone(parse_search_turn(message), message)
        for message in ["viết cho tôi một bài thơ về mùa thu", "thời tiết hà nội hôm nay thế nào"]:
            self.assertIsNone(parse_search_turn(message, strict=False), message)
        self.assertIsNotNone(parse_search_turn("bút viết bi", strict=False))

    def test_variant_words_with_a_product_in_focus_are_not_a_new_search(self):
        self.assertIsNone(parse_search_turn("áo màu đen size L", active_product_id="a" * 24))
        self.assertIsNotNone(
            parse_search_turn("tìm áo màu đen size L", active_product_id="a" * 24)
        )

    def test_strictness_sets_confidence(self):
        self.assertIsNone(parse_search_turn("quà sinh nhật cho bạn gái"))
        loose = parse_search_turn("quà sinh nhật cho bạn gái", strict=False)
        self.assertEqual(loose.confidence, LOOSE_CONFIDENCE)
        self.assertEqual(parse_search_turn("laptop văn phòng").confidence, STRICT_CONFIDENCE)
        # Only function words: nothing to search for even as a fallback.
        self.assertIsNone(parse_search_turn("cái gì cũng được", strict=False))

    def test_policy_questions_are_recognised_but_personal_ones_are_not(self):
        for message in ["chính sách đổi trả thế nào", "giao hàng mất bao lâu", "phí ship bao nhiêu"]:
            self.assertEqual(parse_policy_turn(message).tasks[0].intent, "policy", message)
        for message in ["đơn hàng của tôi giao chưa", "sản phẩm này bảo hành bao lâu", "tai nghe bluetooth",
                        "tìm balo laptop và cho hỏi chính sách bảo hành"]:
            self.assertIsNone(parse_policy_turn(message), message)


if __name__ == "__main__":
    unittest.main()


class ReconcileTurnTests(unittest.TestCase):
    def turn(self, message, *constraints):
        from app.schemas import SemanticTask, SemanticTurn

        return SemanticTurn(
            tasks=[SemanticTask(intent="product_search", query=message, constraints=list(constraints))],
            confidence=1,
        )

    def keyed(self, turn):
        return {(item.key, item.operator): item.value for item in turn.tasks[0].constraints}

    def test_price_units_dropped_by_the_model_are_restored(self):
        from app.schemas import SemanticConstraint as C
        from app.search_parser import reconcile_turn

        message = "laptop ram 16gb dưới 20 triệu"
        fixed = reconcile_turn(self.turn(message, C(key="price", operator="lt", value=20.0)), message)
        self.assertEqual(self.keyed(fixed), {("price", "lte"): 20_000_000})

    def test_negated_colour_is_removed_and_brand_added(self):
        from app.schemas import SemanticConstraint as C
        from app.search_parser import reconcile_turn

        message = "áo khoác sony không phải màu đen"
        fixed = reconcile_turn(self.turn(message, C(key="color", value=["đen", "xám"])), message)
        self.assertEqual(self.keyed(fixed), {("color", "eq"): ["xám"], ("brand", "eq"): "sony"})
        self.assertNotIn("color", str(constraints("áo khoác không phải màu đen")))

    def test_turn_without_textual_evidence_is_unchanged(self):
        from app.schemas import SemanticConstraint as C
        from app.search_parser import reconcile_turn

        original = self.turn("loại nào rẻ hơn", C(key="price", operator="lte", value=100.0))
        self.assertIs(reconcile_turn(original, "loại nào rẻ hơn"), original)
