from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
from sentinel.run import check_artifacts, report_health, sync_github_issues


class HealthCheckTests(unittest.TestCase):
    def test_missing_artifacts_detected(self) -> None:
        issues = check_artifacts("bundles/non-existent-date.json")
        self.assertTrue(any("bundle" in msg for msg in issues))

    def test_report_health_formats_without_emojis(self) -> None:
        report = report_health([], {"sources": {}}, [], [], "2026-10-15")
        self.assertIn("Sentinel 采集健康简报", report)
        for ch in report:
            self.assertFalse(0x1F300 <= ord(ch) <= 0x1F9FF or 0x2600 <= ord(ch) <= 0x27BF)

    @patch.dict("os.environ", {"GITHUB_TOKEN": "mock-token", "GITHUB_REPOSITORY": "test/repo"})
    @patch("httpx.get")
    @patch("httpx.post")
    def test_sync_issues_does_not_duplicate(self, mock_post: MagicMock, mock_get: MagicMock) -> None:
        # Existing open issue for 'bad-blog'
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"number": 10, "title": "[alert] 采集失败: bad-blog"}],
        )
        failed = [{"id": "bad-blog", "error": "timeout"}]
        sources_dict = {"bad-blog": {"fail_streak": 5}}

        sync_github_issues(failed, sources_dict, recovered_sids=[])
        # Since 'bad-blog' already has an open issue, post should NOT be called to create an issue
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
            json=lambda: [{"number": 42, "title": "[alert] 采集失败: recovered-blog"}],
        )
        sync_github_issues(failed=[], sources_dict={}, recovered_sids=["recovered-blog"])
        # Should post closing comment and patch issue to closed
        mock_post.assert_called_once()
        mock_patch.assert_called_once()
        self.assertIn("42", mock_patch.call_args[0][0])
        self.assertEqual(mock_patch.call_args[1]["json"], {"state": "closed"})


if __name__ == "__main__":
    unittest.main()
