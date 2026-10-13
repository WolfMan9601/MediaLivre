import unittest

from medialivre import is_http_url, quality_format


class UrlValidationTests(unittest.TestCase):
    def test_accepts_absolute_http_and_https_urls(self):
        self.assertTrue(is_http_url("https://example.com/video?id=1"))
        self.assertTrue(is_http_url("http://example.com/path"))
        self.assertTrue(is_http_url("  https://example.com/video  "))

    def test_rejects_local_paths_and_unsupported_schemes(self):
        self.assertFalse(is_http_url("C:\\Users\\me\\video.mp4"))
        self.assertFalse(is_http_url("file:///tmp/video.mp4"))
        self.assertFalse(is_http_url("javascript:alert(1)"))
        self.assertFalse(is_http_url("//example.com/video"))
        self.assertFalse(is_http_url("https:///missing-host"))
        self.assertFalse(is_http_url("https://user:password@example.com/video"))
        self.assertFalse(is_http_url(""))


class FormatSelectionTests(unittest.TestCase):
    def test_quality_limit_is_applied(self):
        self.assertEqual(
            quality_format("720p", False),
            "bestvideo[height<=720]+bestaudio/best[height<=720]",
        )
        self.assertEqual(quality_format("480p", False), "bestvideo[height<=480]+bestaudio/best[height<=480]")

    def test_best_available_and_audio_only(self):
        self.assertEqual(quality_format("Melhor disponível", False), "bestvideo+bestaudio/best")
        self.assertEqual(quality_format("1080p", True), "bestaudio/best")


if __name__ == "__main__":
    unittest.main()
