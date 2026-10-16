from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
from sentinel.run import (
    check_artifacts,
    collect_alerts,
    report_health,
    sync_github_issues,
)


class _FakeSource:
    def __init__(self, sid: str, mode: str = "rss") -> None:
        self.id = sid
        self.collect_mode = mode


class HealthCheckTests(unittest.TestCase):
    def test_missing_artifacts_detected(self) -> None:
        issues = check_artifacts("bundles/non-existent-date.json")
        self.assertTrue(any("bundle" in msg for msg in issues))

    def test_report_health_formats_without_emojis(self) -> None:
        report = report_health([], {"sources": {}}, [], [], "2026-10-15")
        self.assertIn("Sentinel 采集健康简报", report)
        for ch in report:
            self.assertFalse(0x1F300 <= ord(ch) <= 0x1F9FF or 0x2600 <= ord(ch) <= 0x27BF)

    def test_collect_alerts_path_degradation(self) -> None:
        sources = [_FakeSource("bad-rss", "rss")]
        st = {"sources": {"bad-rss": {"method": "browser_llm", "fail_streak": 0}}}
        alerts = collect_alerts(sources, st, [], [])
        self.assertTrue(
            any(a["category"] == "路径退化" and a["id"] == "bad-rss" for a in alerts)
        )

    def test_collect_alerts_no_false_positive_for_llm_modes(self) -> None:
        sources = [_FakeSource("browser-src", "browser_llm")]
        st = {"sources": {"browser-src": {"method": "browser_llm", "fail_streak": 0}}}
        alerts = collect_alerts(sources, st, [], [])
        self.assertFalse(any(a["category"] == "路径退化" for a in alerts))

    def test_collect_alerts_correlated_sources(self) -> None:
        # Same source failing with a degraded path must not produce duplicate
        # issues: one alert per (id, category) pair.
        sources = [_FakeSource("dual", "rss")]
        st = {"sources": {"dual": {"method": "llm", "fail_streak": 2}}}
        failed = [{"id": "dual", "error": "feed parse error"}]
        alerts = collect_alerts(sources, st, failed, [])
        cats = [(a["id"], a["category"]) for a in alerts]
        self.assertEqual(len(cats), len(set(cats)))

    @patch.dict("os.environ", {"GITHUB_TOKEN": "mock-token", "GITHUB_REPOSITORY": "test/repo"})
    @patch("httpx.get")
    @patch("httpx.post")
    def test_sync_issues_does_not_duplicate(self, mock_post: MagicMock, mock_get: MagicMock) -> None:
        # Existing open issue for 'bad-blog'
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{
                "number": 10,
                "title": "[alert] 路径退化: bad-blog",
                "state": "open",
            }],
        )
        alerts = [
            {"id": "bad-blog", "category": "路径退化", "detail": "RSS fell back to browser"},
            {"id": "bad-blog", "category": "反爬拦截", "detail": "challenge blocked"},
        ]

        sync_github_issues([], {}, recovered_sids=[], alerts=alerts)
        # One existing open issue for the source covers all alert categories.
        mock_post.assert_not_called()

    @patch.dict("os.environ", {"GITHUB_TOKEN": "mock-token", "GITHUB_REPOSITORY": "test/repo"})
    @patch("httpx.get")
    @patch("httpx.post")
    @patch("httpx.patch")
    def test_sync_issues_auto_closes_recovered(
        self, mock_patch: MagicMock, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"number": 42, "title": "[alert] 采集失败: recovered-blog", "state": "open"}],
        )
        sync_github_issues(failed=[], sources_dict={}, recovered_sids=["recovered-blog"])
        # Should post closing comment and patch issue to closed
        mock_post.assert_called_once()
        mock_patch.assert_called_once()
        self.assertIn("42", mock_patch.call_args[0][0])
        self.assertEqual(mock_patch.call_args[1]["json"], {"state": "closed"})

    @patch.dict("os.environ", {"GITHUB_TOKEN": "mock-token", "GITHUB_REPOSITORY": "test/repo"})
    @patch("httpx.get")
    @patch("httpx.post")
    def test_sync_issues_low_streak_no_issue(self, mock_post: MagicMock, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        alerts = [{"id": "flaky", "category": "采集失败", "detail": "连续 1 次: timeout"}]
        sync_github_issues([], {}, [], alerts=alerts)
        mock_post.assert_not_called()

    @patch.dict("os.environ", {"GITHUB_TOKEN": "mock-token", "GITHUB_REPOSITORY": "test/repo"})
    @patch("httpx.get")
    @patch("httpx.post")
    def test_sync_issues_degradation_creates_issue(self, mock_post: MagicMock, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        alerts = [
            {"id": "degraded", "category": "路径退化", "detail": "声明 rss，实际走 browser_llm"}
        ]
        sync_github_issues([], {}, [], alerts=alerts)
        mock_post.assert_called_once()
        title = mock_post.call_args[1]["json"]["title"]
        self.assertEqual(title, "[alert] 路径退化: degraded")

    @patch.dict("os.environ", {"GITHUB_TOKEN": "mock-token", "GITHUB_REPOSITORY": "test/repo"})
    @patch("httpx.get")
    @patch("httpx.post")
    def test_sync_access_block_creates_issue_on_first_occurrence(
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        alert = [{"id": "blocked", "category": "访问受限", "detail": "403 Cloudflare ban"}]
        sync_github_issues([], {}, [], alerts=alert)
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["json"]["title"], "[alert] 访问受限: blocked")

    @patch.dict("os.environ", {"GITHUB_TOKEN": "mock-token", "GITHUB_REPOSITORY": "test/repo"})
    @patch("httpx.get")
    @patch("httpx.post")
    def test_sync_issues_artifact_alert_skipped(self, mock_post: MagicMock, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        alerts = [{"id": "artifact", "category": "artifact", "detail": "bundle 缺失"}]
        sync_github_issues([], {}, [], alerts=alerts)
        mock_post.assert_not_called()

    @patch.dict("os.environ", {"GITHUB_TOKEN": "mock-token", "GITHUB_REPOSITORY": "test/repo"})
    @patch("httpx.get")
    @patch("httpx.post")
    @patch("httpx.patch")
    def test_sync_issues_keeps_open_when_still_alerting(
        self, mock_patch: MagicMock, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        # Recovered source is still alerting via another category: keep issue open
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"number": 7, "title": "[alert] 采集失败: still-bad", "state": "open"}],
        )
        alerts = [{"id": "still-bad", "category": "路径退化", "detail": "声明 rss，实际走 llm"}]
        sync_github_issues([], {}, recovered_sids=["still-bad"], alerts=alerts)
        mock_patch.assert_not_called()

    @patch.dict("os.environ", {"GITHUB_TOKEN": "mock-token", "GITHUB_REPOSITORY": "test/repo"})
    @patch("httpx.get")
    @patch("httpx.post")
    @patch("httpx.patch")
    def test_sync_reopens_closed_issue_instead_of_creating_duplicate(
        self, mock_patch: MagicMock, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"number": 11, "title": "[alert] 路径退化: recurring", "state": "closed"}],
        )
        alerts = [{"id": "recurring", "category": "路径退化", "detail": "RSS still degraded"}]
        sync_github_issues([], {}, [], alerts=alerts)
        mock_patch.assert_called_once()
        self.assertEqual(mock_patch.call_args.kwargs["json"], {"state": "open"})
        mock_post.assert_called_once()
        self.assertTrue(mock_post.call_args.args[0].endswith("/issues/11/comments"))


if __name__ == "__main__":
    unittest.main()
