import unittest
import io
import json
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch
from yt_dlp.utils import DownloadError

from medialivre import (
    DownloadWorker,
    InstallerDownloadWorker,
    SkipCurrentItem,
    UpdateCheckWorker,
    collection_items,
    container_options,
    extract_sha256,
    is_collection_url,
    is_http_url,
    media_processing_options,
    matching_extractors,
    playlist_enabled,
    progress_details,
    quality_format,
    should_try_direct_media,
    start_installer_process,
    user_facing_download_error,
    version_tuple,
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

    def test_reports_specific_extractor_for_supported_source(self):
        names = matching_extractors("https://www.youtube.com/watch?v=abc123")
        self.assertTrue(any(name.lower().startswith("youtube") for name in names))

    def test_explains_generic_unsupported_page_without_promising_scraping(self):
        message = user_facing_download_error(
            "ERROR: Unsupported URL: https://boraflix.rest/filme/reza-a-lenda",
            "https://boraflix.rest/filme/reza-a-lenda",
        )
        self.assertIn("boraflix.rest", message)
        self.assertIn("não tem um extrator específico", message)
        self.assertIn("URL direta HTTP(S)", message)
        self.assertIn("não contorna DRM", message)
        self.assertNotIn("FFmpeg", message.split("Isto não é", 1)[0])

    def test_direct_media_fallback_is_limited_to_unsupported_extractor_errors(self):
        self.assertTrue(should_try_direct_media("ERROR: Unsupported URL: https://example.test/player"))
        self.assertTrue(should_try_direct_media("No suitable extractor found"))
        self.assertFalse(should_try_direct_media("ERROR: HTTP Error 403: Forbidden"))

    def test_unsupported_url_failure_is_emitted_once(self):
        logs = []
        failures = []
        worker = DownloadWorker(
            "https://boraflix.rest/filme/reza-a-lenda",
            Path(tempfile.mkdtemp()),
            "Melhor disponível",
            audio_only=False,
            allow_playlist=False,
            container="Automático",
        )
        worker.log_line.connect(logs.append)
        worker.failed.connect(failures.append)
        with patch(
            "medialivre.YoutubeDL.download",
            side_effect=DownloadError(
                "ERROR: Unsupported URL: https://boraflix.rest/filme/reza-a-lenda"
            ),
        ), patch("medialivre.probe_direct_media_url", return_value=None):
            worker.run()
        self.assertEqual(len(failures), 1)
        self.assertEqual([line for line in logs if line.startswith("Erro:")], [])
        self.assertEqual(failures[0].count("A página boraflix.rest"), 1)

    def test_facebook_reel_id_is_used_to_find_existing_output(self):
        worker = DownloadWorker(
            "https://www.facebook.com/reel/1649266366591892",
            Path(tempfile.mkdtemp()),
            "Melhor disponível",
            audio_only=False,
            allow_playlist=False,
            container="MP4",
        )
        tokens = worker._item_output_tokens({
            "id": "single",
            "url": "https://www.facebook.com/reel/1649266366591892",
        })
        self.assertIn("1649266366591892", tokens)


class UpdateCheckTests(unittest.TestCase):
    def test_detects_new_release_and_installer_asset(self):
        payload_bytes = b"installer bytes"
        checksum = hashlib.sha256(payload_bytes).hexdigest()
        payload = [{
            "tag_name": "v0.9.0",
            "name": "MediaLivre 0.9.0",
            "html_url": "https://github.com/WolfMan9601/MediaLivre/releases/tag/v0.9.0",
            "assets": [{
                "name": "MediaLivre-Setup-0.9.0-win64.exe",
                "browser_download_url": "https://github.com/WolfMan9601/MediaLivre/releases/download/v0.9.0/MediaLivre-Setup-0.9.0-win64.exe",
            }, {
                "name": "MediaLivre-Setup-0.9.0-win64.exe.sha256",
                "browser_download_url": "https://github.com/WolfMan9601/MediaLivre/releases/download/v0.9.0/MediaLivre-Setup-0.9.0-win64.exe.sha256",
            }],
        }]
        events = []
        worker = UpdateCheckWorker("WolfMan9601/MediaLivre", "0.8.0")
        worker.releases.connect(lambda releases: events.append(releases))
        with patch("medialivre.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            worker.run()
        self.assertEqual(events[0][0]["version"], "v0.9.0")
        self.assertTrue(events[0][0]["installer_url"].endswith("MediaLivre-Setup-0.9.0-win64.exe"))
        self.assertTrue(events[0][0]["checksum_url"].endswith(".exe.sha256"))

    def test_extracts_sha256_digest(self):
        digest = "a" * 64
        self.assertEqual(extract_sha256(f"{digest}  MediaLivre-Setup.exe"), digest)
        self.assertIsNone(extract_sha256("checksum ausente"))

    def test_download_worker_validates_checksum_before_completion(self):
        payload_bytes = b"installer bytes"
        checksum = hashlib.sha256(payload_bytes).hexdigest()

        class FakeResponse(io.BytesIO):
            def __init__(self, data, headers=None):
                super().__init__(data)
                self.headers = headers or {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self.close()

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "MediaLivre-Setup-test.exe"
            events = []
            worker = InstallerDownloadWorker(
                "https://example.test/MediaLivre-Setup-test.exe",
                "https://example.test/MediaLivre-Setup-test.exe.sha256",
                target,
            )
            worker.completed.connect(lambda path: events.append(("completed", path)))
            worker.failed.connect(lambda message: events.append(("failed", message)))
            with patch(
                "medialivre.urlopen",
                side_effect=[
                    FakeResponse(payload_bytes, {"Content-Length": str(len(payload_bytes))}),
                    FakeResponse(f"{checksum}  MediaLivre-Setup-test.exe".encode()),
                ],
            ):
                worker.run()
            self.assertEqual(events[0][0], "completed")
            self.assertEqual(Path(events[0][1]).read_bytes(), payload_bytes)
            self.assertFalse(target.with_name(f".{target.name}.part").exists())

    def test_download_worker_rejects_release_without_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "MediaLivre-Setup-test.exe"
            events = []
            worker = InstallerDownloadWorker(
                "https://example.test/MediaLivre-Setup-test.exe",
                "",
                target,
            )
            worker.failed.connect(lambda message: events.append(message))
            worker.run()
            self.assertIn("checksum SHA-256", events[0])
            self.assertFalse(target.exists())

    def test_start_installer_process_unwraps_qprocess_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "MediaLivre-Setup-test.exe"
            target.write_bytes(b"installer")
            with patch("medialivre.QProcess.startDetached", return_value=(False, -1)) as start:
                self.assertFalse(start_installer_process(str(target)))
            with patch("medialivre.QProcess.startDetached", return_value=(True, 1234)) as start:
                self.assertTrue(start_installer_process(str(target)))
                self.assertEqual(start.call_args.args[0], str(target))
                self.assertIn("/VERYSILENT", start.call_args.args[1])


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
