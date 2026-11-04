import unittest

from app.taxonomy import (
    build_catalog_tree,
    compact_catalog_tree,
    resolve_category_ids,
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


if __name__ == "__main__":
    unittest.main()
