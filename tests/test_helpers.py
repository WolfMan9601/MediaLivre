import unittest
from pathlib import Path

from medialivre import (
    DownloadWorker,
    SkipCurrentItem,
    collection_items,
    container_options,
    is_collection_url,
    is_http_url,
    media_processing_options,
    playlist_enabled,
    progress_details,
    quality_format,
)


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

    def test_detects_youtube_playlist_and_channel_urls(self):
        collection_urls = [
            "https://www.youtube.com/playlist?list=PL123",
            "https://www.youtube.com/watch?v=abc&list=PL123",
            "https://www.youtube.com/@artist/videos",
            "https://www.youtube.com/channel/UC123",
            "https://www.youtube.com/c/artist",
            "https://www.youtube.com/user/artist",
        ]
        for url in collection_urls:
            with self.subTest(url=url):
                self.assertTrue(is_collection_url(url))
        self.assertFalse(is_collection_url("https://www.youtube.com/watch?v=abc"))
        self.assertFalse(playlist_enabled("https://www.youtube.com/playlist?list=PL123", False))
        self.assertFalse(playlist_enabled("https://www.youtube.com/watch?v=abc", True))
        self.assertTrue(playlist_enabled("https://www.youtube.com/playlist?list=PL123", True))
        self.assertFalse(playlist_enabled("https://www.youtube.com/watch?v=abc", False))

    def test_detects_other_supported_sources_without_misclassifying_videos(self):
        self.assertTrue(is_http_url("https://www.tiktok.com/@artist"))
        self.assertTrue(is_collection_url("https://www.tiktok.com/@artist"))
        self.assertFalse(is_collection_url("https://www.tiktok.com/@artist/video/123"))
        self.assertTrue(is_collection_url("https://www.instagram.com/artist/"))
        self.assertFalse(is_collection_url("https://www.instagram.com/reel/ABC123/"))
        self.assertFalse(is_collection_url("https://www.instagram.com/p/ABC123/"))

    def test_normalizes_flat_collection_entries(self):
        items = collection_items({
            "entries": [
                {"playlist_index": 2, "id": "b", "title": "Segundo", "webpage_url": "https://example.com/b"},
                None,
                {"id": "c", "title": "Terceiro", "url": "https://example.com/c"},
            ]
        })
        self.assertEqual([item["index"] for item in items], [2, 3])
        self.assertEqual([item["title"] for item in items], ["Segundo", "Terceiro"])


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
            "bestvideo[vcodec^=avc1][ext=mp4][height<=720]+bestaudio[ext=m4a]/best[vcodec^=avc1][ext=mp4][height<=720]/bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]",
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

    def test_thumbnail_download_and_embed_options(self):
        audio = media_processing_options(True, True, "MP4")
        self.assertTrue(audio["writethumbnail"])
        self.assertEqual(
            [pp["key"] for pp in audio["postprocessors"]],
            ["FFmpegThumbnailsConvertor", "FFmpegExtractAudio", "EmbedThumbnail"],
        )
        avi = media_processing_options(True, False, "AVI")
        self.assertEqual(
            [pp["key"] for pp in avi["postprocessors"]],
            ["FFmpegThumbnailsConvertor", "FFmpegVideoConvertor"],
        )
        automatic = media_processing_options(True, False, "Automático")
        self.assertEqual([pp["key"] for pp in automatic["postprocessors"]], ["FFmpegThumbnailsConvertor"])
        disabled = media_processing_options(False, False, "MP4")
        self.assertNotIn("writethumbnail", disabled)


class PlaylistProgressTests(unittest.TestCase):
    def test_reports_item_percent_and_overall_playlist_percent(self):
        overall, item, item_label, batch_label = progress_details({
            "status": "downloading",
            "downloaded_bytes": 50,
            "total_bytes": 100,
            "info_dict": {
                "playlist_index": 3,
                "n_entries": 10,
                "playlist_title": "A minha lista",
                "title": "Vídeo atual",
            },
        })
        self.assertEqual((overall, item), (25, 50))
        self.assertIn("3/10", item_label)
        self.assertIn("Vídeo atual", item_label)
        self.assertIn("A minha lista", batch_label)

    def test_handles_unknown_playlist_total_and_finished_item(self):
        overall, item, item_label, batch_label = progress_details({
            "status": "finished",
            "info_dict": {"playlist_index": 4, "n_entries": "N/A", "title": "Último vídeo"},
        })
        self.assertEqual((overall, item), (100, 100))
        self.assertIn("Item 4", item_label)
        self.assertIn("total por determinar", batch_label)

    def test_worker_emits_updated_item_when_playlist_entry_changes(self):
        worker = DownloadWorker("https://example.com/list", Path("."), "720p", False, True)
        overall_events = []
        item_events = []
        worker.progress.connect(lambda percent, label: overall_events.append((percent, label)))
        worker.item_progress.connect(lambda percent, label: item_events.append((percent, label)))
        for index, title, downloaded in [(1, "Primeiro", 50), (2, "Segundo", 20)]:
            worker._progress_hook({
                "status": "downloading",
                "downloaded_bytes": downloaded,
                "total_bytes": 100,
                "info_dict": {
                    "playlist_index": index,
                    "n_entries": 2,
                    "playlist_title": "Demonstração",
                    "id": str(index),
                    "title": title,
                },
            })
        self.assertEqual([event[0] for event in overall_events], [25, 60])
        self.assertEqual([event[0] for event in item_events], [50, 20])
        self.assertIn("Primeiro", item_events[0][1])
        self.assertIn("Segundo", item_events[1][1])

    def test_skip_request_targets_only_current_item(self):
        worker = DownloadWorker("https://example.com/list", Path("."), "720p", False, True)
        worker.total_items = 2
        worker.current_position = 1
        worker.skip_current_item()
        with self.assertRaises(SkipCurrentItem):
            worker._progress_hook({"status": "downloading", "info_dict": {"title": "Primeiro"}})
        self.assertFalse(worker.skip_requested.is_set())


if __name__ == "__main__":
    unittest.main()
