from __future__ import annotations

import unittest

from sentinel.llm import _parse_article_ids_json, _parse_ids_json


class LlmOutputTests(unittest.TestCase):
    def test_only_accepts_unique_in_range_candidate_ids(self) -> None:
        text = '{"article_ids":[2,0,2,99,-1,"1","not-an-id",true]}'
        self.assertEqual(
            _parse_article_ids_json(text, candidate_count=3),
            [2, 0, 1],
        )

    def test_rejects_legacy_or_invented_url_shape(self) -> None:
        text = '{"articles":[{"url":"https://evil.example/invented"}]}'
        self.assertEqual(_parse_article_ids_json(text, candidate_count=10), [])

    def test_content_blocks_use_the_same_bounded_id_contract(self) -> None:
        text = '{"content_block_ids":[1,1,0,8]}'
        self.assertEqual(
            _parse_ids_json(text, key="content_block_ids", candidate_count=2),
            [1, 0],
        )


if __name__ == "__main__":
    unittest.main()
