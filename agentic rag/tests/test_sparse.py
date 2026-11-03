import unittest

from app.sparse import document_sparse_vector, query_sparse_vector, sparse_tokens


class SparseVectorTests(unittest.TestCase):
    def test_tokens_fold_diacritics_and_keep_short_meaningful_syllables(self):
        self.assertEqual(
            sparse_tokens("Áo thun đỏ"),
            ["ao", "thun", "do", "ao_thun", "thun_do"],
        )

    def test_query_and_document_share_token_indices(self):
        document = document_sparse_vector("Điện thoại Samsung pin 5000 mAh")
        query = query_sparse_vector("điện thoại")
        self.assertTrue(set(query["indices"]) <= set(document["indices"]))
        self.assertEqual(query["values"], [1.0] * len(query["indices"]))

    def test_repeated_terms_saturate(self):
        once = document_sparse_vector("loa")
        many = document_sparse_vector("loa loa loa loa")
        self.assertLess(many["values"][0], 4 * once["values"][0])


if __name__ == "__main__":
    unittest.main()
