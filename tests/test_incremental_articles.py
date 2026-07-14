from __future__ import annotations

import unittest
from unittest.mock import patch

from sentinel.collectors import articles, html_links, llm_fallback
from sentinel.collectors.sources import Source


class CandidateFilteringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = Source(
            id="example-blog",
            name="Example Blog",
            home_url="https://example.com/blog/",
            collect_mode="html_llm",
        )

    def test_same_site_ad_is_filtered_before_llm(self) -> None:
        url = "https://example.com/misc.php?do=tad&rad=uc_255_thread"
        self.assertTrue(
            html_links.looks_like_promotion(
                url, "Unlock the Power of Advertising: Rent This Thread!"
            )
        )

    def test_candidate_context_is_local_and_bounded(self) -> None:
        html = """
        <div class="card">
          <a href="/blog/research">Kernel research</a>
          <span>Technical analysis of a driver vulnerability.</span>
        </div>
        """
        candidates = html_links.extract_candidates(
            html,
            page_url=self.source.home_url,
            home_url=self.source.home_url,
        )
        self.assertEqual(len(candidates), 1)
        self.assertIn("driver vulnerability", candidates[0]["context"])

    def test_llm_only_receives_never_seen_candidates(self) -> None:
        html = """
        <a href="/blog/old">Old technical article</a>
        <a href="/blog/new">New technical article</a>
        <a href="/misc.php?do=tad&rad=x">Rent This Thread!</a>
        """

        def select(**kwargs):
            self.assertEqual(
                [c["url"] for c in kwargs["candidates"]],
                ["https://example.com/blog/new"],
            )
            return [kwargs["candidates"][0]]

        with (
            patch("sentinel.collectors.llm_fallback.llm.configured", return_value=True),
            patch(
                "sentinel.collectors.llm_fallback.llm.select_articles_from_page",
                side_effect=select,
            ),
        ):
            picked, err, candidates = llm_fallback._denoise_with_html(
                self.source,
                self.source.home_url,
                html,
                use_llm=True,
                known_urls={"https://example.com/blog/old"},
            )

        self.assertIsNone(err)
        self.assertEqual([x["url"] for x in picked], ["https://example.com/blog/new"])
        self.assertEqual(len(candidates), 2)

    def test_existing_state_without_candidate_state_becomes_baseline(self) -> None:
        old_url = "https://example.com/blog/old"
        new_url = "https://example.com/blog/new"
        state = {
            "sources": {
                self.source.id: {
                    "seen": {old_url: {"title": "Old"}},
                    "last_ok_at": "2026-07-13T00:00:00+00:00",
                }
            }
        }

        def collect(_source, **kwargs):
            self.assertTrue(kwargs["baseline_only"])
            self.assertIn(old_url, kwargs["known_urls"])
            return [], None, "http", [
                {"url": old_url, "title": "Old technical article"},
                {"url": new_url, "title": "New-looking historical article"},
            ]

        with patch("sentinel.collectors.articles.llm_fallback.collect", side_effect=collect):
            result = articles.collect_one(self.source, state)

        self.assertTrue(result["ok"])
        self.assertEqual(result["new_articles"], [])
        records = state["sources"][self.source.id]["candidates"]
        self.assertTrue(records[old_url]["baseline"])
        self.assertTrue(records[new_url]["baseline"])


if __name__ == "__main__":
    unittest.main()
