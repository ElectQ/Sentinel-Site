from __future__ import annotations

import unittest
from unittest.mock import patch

from sentinel.collectors.content import enrich, extract_block_candidates, extract_text
from sentinel.collectors.sources import Source


class ContentExtractionTests(unittest.TestCase):
    def test_extracts_vbulletin_post_instead_of_forum_navigation(self) -> None:
        html = """
        <html><body>
          <nav>Forums Search Members Advertising</nav>
          <div id="post_message_123">
            Technical thread body with enough useful details to represent the
            original post. It explains memory scanning, reverse engineering,
            implementation constraints, and concrete engineering tradeoffs.
          </div>
          <div id="post_message_124">Short reply.</div>
          <footer>Similar Threads Contact</footer>
        </body></html>
        """
        text = extract_text(html)
        self.assertIn("Technical thread body", text)
        self.assertNotIn("Advertising", text)
        self.assertNotIn("Similar Threads", text)

    def test_llm_block_fallback_for_unknown_dom(self) -> None:
        body = (
            "A detailed technical analysis of an unusual runtime container. "
            "It explains the threat model, implementation, validation strategy, "
            "failure modes, mitigations, and reproducible engineering results. "
        ) * 3
        html = f"<html><body><div class='site-xyz-917'>{body}</div></body></html>"
        blocks = extract_block_candidates(html)
        self.assertTrue(blocks)

        source = Source(
            id="odd-site",
            name="Odd Site",
            home_url="https://example.com/",
            collect_mode="html_llm",
        )
        article = {
            "url": "https://example.com/research/odd-runtime",
            "title": "Odd runtime research",
        }
        with (
            patch(
                "sentinel.collectors.content.html_links.fetch_html",
                return_value=(article["url"], html),
            ),
            patch("sentinel.collectors.content.llm.configured", return_value=True),
            patch(
                "sentinel.collectors.content.llm.select_content_blocks",
                return_value=[0],
            ),
        ):
            result = enrich(article, source)

        self.assertEqual(result["content_status"], "ok")
        self.assertEqual(result["content_via"], "http_llm_blocks")
        self.assertIn("technical analysis", result["content"])


if __name__ == "__main__":
    unittest.main()
