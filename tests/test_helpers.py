import unittest

from medialivre import container_options, is_http_url, quality_format


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

    def test_mp4_selects_compatible_streams(self):
        self.assertEqual(
            quality_format("720p", False, "MP4"),
            "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]",
        )

    def test_best_available_and_audio_only(self):
        self.assertEqual(quality_format("Melhor disponível", False), "bestvideo+bestaudio/best")
        self.assertEqual(quality_format("1080p", True), "bestaudio/best")

    def test_video_container_postprocessors(self):
        self.assertEqual(container_options("Automático"), {})
        self.assertEqual(container_options("MP4"), {"merge_output_format": "mp4"})
        self.assertEqual(
            container_options("MKV")["postprocessors"],
            [{"key": "FFmpegVideoConvertor", "preferedformat": "mkv"}],
        )
        avi = container_options("AVI")
        self.assertEqual(avi["postprocessors"], [{"key": "FFmpegVideoConvertor", "preferedformat": "avi"}])
        self.assertIn("-c:a", avi["postprocessor_args"]["videoconvertor+ffmpeg_o"])


if __name__ == "__main__":
    unittest.main()
