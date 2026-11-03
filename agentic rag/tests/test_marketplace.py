import unittest

from app.marketplace import _matches_audience


class MarketplaceAudienceTests(unittest.TestCase):
    def test_rejects_explicit_audience_conflicts(self):
        self.assertFalse(
            _matches_audience({"name": "MUJI Áo Thun Nữ Cổ Tròn"}, "nam")
        )
        self.assertFalse(
            _matches_audience({"name": "Áo Polo Nam Cơ Bản"}, "nu")
        )

    def test_keeps_unisex_or_products_without_an_explicit_conflict(self):
        self.assertTrue(
            _matches_audience({"name": "Vietnam Life T-shirt Collection"}, "nam")
        )
        self.assertTrue(
            _matches_audience({"name": "Áo thun unisex"}, "unisex")
        )


if __name__ == "__main__":
    unittest.main()
