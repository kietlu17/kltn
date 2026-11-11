"""Brand recognition shared by the indexer payload and the query filters."""

import unittest

from app.brands import brand_in_text, canonical_brand, stated_brand
from app.indexer.documents import product_metadata


class BrandTests(unittest.TestCase):
    def test_brand_from_the_name_including_product_lines(self):
        self.assertEqual(brand_in_text("Loa Bluetooth JBL Clip 5"), "JBL")
        self.assertEqual(brand_in_text("Điện thoại iPhone 17 Pro"), "Apple")
        self.assertEqual(brand_in_text("Điện thoại Samsung Galaxy A35"), "Samsung")
        self.assertEqual(brand_in_text("Tai nghe Bluetooth Xiaomi Redmi Buds 6"), "Xiaomi")
        self.assertEqual(brand_in_text("Loa Bluetooth Harman Kardon Go + Play 3"), "Harman Kardon")
        self.assertEqual(brand_in_text("MUJI Bút Bi Bấm 0.3mm"), "MUJI")

    def test_what_an_accessory_fits_is_not_its_brand(self):
        self.assertEqual(brand_in_text("Ốp lưng dành cho iPhone 15"), "")
        self.assertEqual(brand_in_text("Túi xách chống sốc, cặp đựng laptop, macbook, máy tính"), "")
        self.assertEqual(brand_in_text("Áo thun nam cổ tròn"), "")
        self.assertEqual(brand_in_text("Vivobook là gì"), "Asus")
        self.assertEqual(brand_in_text("Áo Bra tập Gym, Yoga"), "")

    def test_what_customers_type_resolves_to_the_indexed_name(self):
        self.assertEqual(canonical_brand("iphone"), "Apple")
        self.assertEqual(canonical_brand("jbl"), "JBL")
        self.assertEqual(canonical_brand("soundcore"), "Anker")
        self.assertEqual(canonical_brand("OEM"), "")
        self.assertEqual(canonical_brand("Caliven Keni"), "Caliven Keni")

    def test_stated_brand_stops_at_the_next_label_and_skips_origin(self):
        self.assertEqual(stated_brand("Việt Nam Thương hiệu: Caliven Keni Gợi ý chọn và bảo quản"), "Caliven Keni")
        self.assertEqual(stated_brand("OEM Xuất xứ thương hiệu: Việt Nam Chất liệu: Đũi"), "")
        self.assertEqual(stated_brand("Trung Quốc Thương hiệu: OEM Gợi ý"), "")

    def test_payload_brand_without_changing_the_embedded_text(self):
        metadata = product_metadata({"_id": "a" * 24, "name": "Loa Bluetooth JBL Clip 5", "description": "Loa nhỏ"})
        self.assertEqual(metadata["brand"], "JBL")


if __name__ == "__main__":
    unittest.main()
