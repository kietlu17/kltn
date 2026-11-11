import unittest

from app.taxonomy import (
    build_catalog_tree,
    category_path_list,
    category_paths,
    compact_catalog_tree,
    resolve_category_ids,
    resolve_category_path,
)


class CatalogTaxonomyTests(unittest.TestCase):
    def test_expands_legacy_paths_without_creating_merchant_roots(self):
        tree = build_catalog_tree(
            [
                {
                    "id": "cat-1",
                    "name": "MUJI · Quần áo › Nam › Áo thun",
                    "shopId": "muji",
                },
                {
                    "id": "cat-2",
                    "name": "MUJI · Quần áo › Nữ › Áo thun",
                    "shopId": "muji",
                },
            ]
        )
        self.assertEqual([node["name"] for node in tree], ["Quần áo"])
        self.assertEqual(
            [node["name"] for node in tree[0]["children"]], ["Nam", "Nữ"]
        )
        self.assertEqual(tree[0]["categoryIds"], ["cat-1", "cat-2"])

    def test_prefers_explicit_parent_relationships(self):
        tree = build_catalog_tree(
            [
                {"id": "root", "name": "Điện tử", "parentId": None},
                {"id": "phone", "name": "Điện thoại", "parentId": "root"},
            ]
        )
        self.assertEqual(tree[0]["path"], ["Điện tử"])
        self.assertEqual(tree[0]["children"][0]["path"], ["Điện tử", "Điện thoại"])

    def test_compaction_reports_hidden_branches(self):
        tree = build_catalog_tree(
            [
                {"id": f"cat-{index}", "name": f"Nhóm › Loại {index:02d}"}
                for index in range(5)
            ]
        )
        compact = compact_catalog_tree(tree, max_depth=2, max_children=2)
        self.assertEqual(len(compact[0]["children"]), 2)
        self.assertEqual(compact[0]["hiddenChildCount"], 3)

    def test_resolves_parent_or_specific_branch_to_descendant_categories(self):
        men_id = "a" * 24
        women_id = "b" * 24
        tree = build_catalog_tree(
            [
                {"id": men_id, "name": "Quần áo › Nam › Áo thun"},
                {"id": women_id, "name": "Quần áo › Nữ › Áo thun"},
            ]
        )
        self.assertEqual(resolve_category_ids(tree, "áo thun nam"), [men_id])
        self.assertEqual(
            resolve_category_ids(tree, "quần áo"), [men_id, women_id]
        )

    def test_tie_goes_to_the_branch_named_first(self):
        backpack, laptop = "a" * 24, "b" * 24
        tree = build_catalog_tree(
            [
                {"id": backpack, "name": "Phụ kiện › Balo"},
                {"id": laptop, "name": "Máy tính › Laptop"},
            ]
        )
        self.assertEqual(resolve_category_ids(tree, "balo laptop chống nước"), [backpack])
        self.assertEqual(resolve_category_ids(tree, "laptop kèm balo"), [laptop])


class CategoryTreeTests(unittest.TestCase):
    """The platform tree built by product-service's buildCategoryTree."""

    def setUp(self):
        self.ids = {}

        def node(name, parent=None):
            category_id = format(len(self.ids) + 1, "024x")
            self.ids[name] = category_id
            return {"id": category_id, "name": name.split("/")[-1], "parentId": self.ids.get(parent)}

        self.categories = [
            node("Thời trang"),
            node("Thời trang/Nam", "Thời trang"),
            node("Thời trang/Nữ", "Thời trang"),
            node("Thời trang/Nam/Áo Thun", "Thời trang/Nam"),          # MUJI
            node("Thời trang/Nữ/Áo Thun", "Thời trang/Nữ"),            # MUJI
            node("Thời trang/Nam/Áo thun nam", "Thời trang/Nam"),      # YODY
            node("Thời trang/Nữ/Áo thun nữ", "Thời trang/Nữ"),         # YODY
            node("Thời trang/Nam/Quần", "Thời trang/Nam"),
            node("Điện tử"),
            node("Điện tử/Laptop", "Điện tử"),
            node("Điện tử/Đồ điện gia dụng", "Điện tử"),
        ]
        self.tree = build_catalog_tree(self.categories)

    def names(self, ids):
        by_id = {value: key for key, value in self.ids.items()}
        return sorted(by_id[item] for item in ids)

    def test_a_kind_covers_every_shop_branch(self):
        self.assertEqual(self.names(resolve_category_ids(self.tree, "áo thun")), [
            "Thời trang/Nam/Áo Thun", "Thời trang/Nam/Áo thun nam",
            "Thời trang/Nữ/Áo Thun", "Thời trang/Nữ/Áo thun nữ",
        ])
        self.assertEqual(self.names(resolve_category_ids(self.tree, "áo thun nữ")), [
            "Thời trang/Nữ/Áo Thun", "Thời trang/Nữ/Áo thun nữ",
        ])

    def test_branch_names_are_not_read_as_a_product_kind(self):
        # "quần áo nữ" is women's fashion, not women's (or men's) trousers.
        self.assertEqual(self.names(resolve_category_ids(self.tree, "quần áo nữ")),
                         ["Thời trang/Nữ", "Thời trang/Nữ/Áo Thun", "Thời trang/Nữ/Áo thun nữ"])
        self.assertIn("Điện tử/Laptop", self.names(resolve_category_ids(self.tree, "đồ điện tử")))

    def test_exact_path_from_the_model(self):
        self.assertEqual(self.names(resolve_category_path(self.tree, "Thoi trang > Nu > Ao thun nu")),
                         ["Thời trang/Nữ/Áo thun nữ"])
        self.assertEqual(resolve_category_path(self.tree, "Thời trang › Trẻ em"), [])

    def test_paths_for_the_model_and_the_indexer(self):
        paths = category_path_list(self.tree)
        self.assertEqual(paths[:2], ["Thời trang", "Điện tử"])
        self.assertIn("Thời trang › Nữ › Áo thun nữ", paths)
        full = category_paths(self.categories)
        self.assertEqual(full[self.ids["Thời trang/Nữ/Áo Thun"]], "Thời trang › Nữ › Áo Thun")


if __name__ == "__main__":
    unittest.main()
