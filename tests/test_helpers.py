import unittest
import io
import json
from pathlib import Path
from unittest.mock import patch

from medialivre import (
    DownloadWorker,
    SkipCurrentItem,
    UpdateCheckWorker,
    browser_cookie_options,
    collection_items,
    collection_label,
    container_options,
    is_instagram_stories_url,
    is_collection_url,
    is_instagram_url,
    is_http_url,
    media_processing_options,
    playlist_enabled,
    progress_details,
    quality_format,
    version_tuple,
    user_facing_download_error,
)


class UrlValidationTests(unittest.TestCase):
    def test_release_versions_are_comparable(self):
        self.assertEqual(version_tuple("v0.8.0"), (0, 8, 0))
        self.assertGreater(version_tuple("v0.9.0"), version_tuple("0.8.0"))
        self.assertGreater(version_tuple("1.0"), version_tuple("0.99.9"))

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

    def test_detects_instagram_story_collections_and_single_stories(self):
        story_urls = [
            "https://www.instagram.com/stories/artist/",
            "https://instagram.com/stories/artist?hl=pt",
            "https://www.instagram.com/stories/highlights/18090946048123978/",
        ]
        for url in story_urls:
            with self.subTest(url=url):
                self.assertTrue(is_instagram_stories_url(url))
                self.assertTrue(is_collection_url(url))
                self.assertTrue(playlist_enabled(url, True))
                self.assertEqual(collection_label(url), "Stories do Instagram")
        single_story = "https://www.instagram.com/stories/artist/3570766765028588805/"
        self.assertFalse(is_instagram_stories_url(single_story))
        self.assertFalse(is_collection_url(single_story))
        self.assertFalse(playlist_enabled(single_story, True))

    def test_browser_cookies_are_only_enabled_for_instagram(self):
        story_url = "https://www.instagram.com/stories/artist/3570766765028588805/"
        self.assertTrue(is_instagram_url(story_url))
        self.assertEqual(
            browser_cookie_options(story_url, "chrome"),
            {"cookiesfrombrowser": ("chrome", None, None, None)},
        )
        self.assertEqual(browser_cookie_options("https://youtube.com/watch?v=1", "chrome"), {})
        with self.assertRaises(ValueError):
            browser_cookie_options(story_url, "unknown")

    def test_instagram_login_error_explains_local_browser_session(self):
        message = user_facing_download_error(
            "ERROR: You need to log in to access this content. Use --cookies-from-browser",
            "https://www.instagram.com/stories/artist/123/",
        )
        self.assertIn("sessão autenticada", message)
        self.assertIn("sessão local do navegador", message)
        self.assertIn("não guarda a sua palavra-passe nem os cookies", message)

    def test_instagram_cookie_database_error_explains_chrome_lock(self):
        message = user_facing_download_error(
            "ERROR: Could not copy Chrome cookie database. See https://github.com/yt-dlp/yt-dlp/issues/7271",
            "https://www.instagram.com/stories/artist/123/",
        )
        self.assertIn("Feche completamente o Chrome", message)
        self.assertIn("Gestor de Tarefas", message)
        self.assertIn("Edge/Firefox/Vivaldi", message)

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


class UpdateCheckTests(unittest.TestCase):
    def test_detects_new_release_and_installer_asset(self):
        payload = [{
            "tag_name": "v0.9.0",
            "name": "MediaLivre 0.9.0",
            "html_url": "https://github.com/WolfMan9601/MediaLivre/releases/tag/v0.9.0",
            "assets": [{
                "name": "MediaLivre-Setup-0.9.0-win64.exe",
                "browser_download_url": "https://github.com/WolfMan9601/MediaLivre/releases/download/v0.9.0/MediaLivre-Setup-0.9.0-win64.exe",
            }],
        }]
        events = []
        worker = UpdateCheckWorker("WolfMan9601/MediaLivre", "0.8.0")
        worker.releases.connect(lambda releases: events.append(releases))
        with patch("medialivre.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            worker.run()
        self.assertEqual(events[0][0]["version"], "v0.9.0")
        self.assertTrue(events[0][0]["installer_url"].endswith("MediaLivre-Setup-0.9.0-win64.exe"))


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
        self.assertFalse(audio["postprocessors"][-1]["already_have_thumbnail"])
        avi = media_processing_options(True, False, "AVI")
        self.assertEqual(
            [pp["key"] for pp in avi["postprocessors"]],
            ["FFmpegVideoConvertor"],
        )
        automatic = media_processing_options(True, False, "Automático")
        self.assertNotIn("postprocessors", automatic)
        disabled = media_processing_options(False, False, "MP4")
        self.assertNotIn("writethumbnail", disabled)

    def test_worker_adds_browser_cookies_for_instagram_story(self):
        worker = DownloadWorker(
            "https://www.instagram.com/stories/artist/123/",
            Path("."),
            "Melhor disponível",
            False,
            False,
            cookies_browser="edge",
        )
        self.assertEqual(
            worker._download_options()["cookiesfrombrowser"],
            ("edge", None, None, None),
        )


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
