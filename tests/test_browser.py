from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from sentinel.collectors import browser


class BrowserConfigurationTests(unittest.TestCase):
    def test_missing_configured_executable_fails_before_playwright_start(self) -> None:
        browser.close()
        with patch.dict(
            os.environ,
            {"BROWSER_EXECUTABLE_PATH": "/definitely/missing/google-chrome"},
        ):
            with self.assertRaisesRegex(RuntimeError, "browser_executable_not_found"):
                browser._ensure_browser()
        self.assertIsNone(browser._playwright)


if __name__ == "__main__":
    unittest.main()
