import functools
import http.server
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.embedthumbnail import EmbedThumbnailPP
from yt_dlp.postprocessor.ffmpeg import FFmpegThumbnailsConvertorPP
from yt_dlp.utils import DownloadError

from medialivre import DownloadWorker, ffmpeg_location, media_processing_options, probe_direct_media_url


TOOLS_AVAILABLE = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass


@unittest.skipUnless(TOOLS_AVAILABLE, "este teste requer ffmpeg e ffprobe no PATH")
class LocalDownloadIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="medialivre-integration-")
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "exemplo.mp4"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-shortest",
                str(cls.source),
            ],
            check=True,
            capture_output=True,
        )
        handler = functools.partial(QuietHandler, directory=str(cls.root))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/exemplo.mp4"
        cls.page = cls.root / "player.html"
        cls.page.write_text(
            '<!doctype html><video controls><source src="exemplo.mp4" type="video/mp4"></video>',
            encoding="utf-8",
        )
        cls.page_url = f"http://127.0.0.1:{cls.server.server_port}/player.html"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=3)
        cls.temp.cleanup()

    def test_download_and_convert_video_containers(self):
        cases = {
            "MP4": (".mp4", "mp4"),
            "MKV": (".mkv", "matroska"),
            "AVI": (".avi", "avi"),
        }
        for container, (extension, expected_format) in cases.items():
            with self.subTest(container=container):
                destination = self.root / container.lower()
                worker = DownloadWorker(
                    self.url,
                    destination,
                    "Melhor disponível",
                    audio_only=False,
                    allow_playlist=False,
                    container=container,
                )
                result = {"completed": [], "failed": [], "cancelled": []}
                worker.completed.connect(lambda path, r=result: r["completed"].append(path))
                worker.failed.connect(lambda error, r=result: r["failed"].append(error))
                worker.cancelled.connect(lambda r=result: r["cancelled"].append(True))
                worker.run()

                self.assertFalse(result["failed"], result["failed"])
                self.assertFalse(result["cancelled"])
                self.assertTrue(result["completed"])
                outputs = [path for path in destination.iterdir() if path.suffix.lower() == extension]
                self.assertTrue(outputs, f"não foi criado arquivo {extension}")
                probe = subprocess.run(
                    [
                        "ffprobe", "-v", "error", "-show_entries", "format=format_name",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(outputs[0]),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertIn(expected_format, probe.stdout.lower())

    def test_mp3_embeds_cover_and_removes_separate_jpg(self):
        audio = self.root / "cover-test.mp3"
        cover = self.root / "cover-test.jpg"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                "-q:a", "5", str(audio),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=yellow:s=128x128",
                "-frames:v", "1", str(cover),
            ],
            check=True,
            capture_output=True,
        )
        info = {
            "filepath": str(audio),
            "ext": "mp3",
            "id": "cover-test",
            "title": "cover-test",
            "thumbnails": [{
                "filepath": str(cover),
                "ext": "jpg",
                "url": "https://example.invalid/cover.jpg",
            }],
        }
        options = media_processing_options(True, True, "MP4")
        ydl_options = {"quiet": True, "no_warnings": True}
        if ffmpeg_location():
            ydl_options["ffmpeg_location"] = str(ffmpeg_location())
        with YoutubeDL(ydl_options) as ydl:
            for pp in options["postprocessors"]:
                if pp["key"] == "FFmpegThumbnailsConvertor":
                    ydl.add_post_processor(FFmpegThumbnailsConvertorPP(ydl, format="jpg"))
                elif pp["key"] == "EmbedThumbnail":
                    ydl.add_post_processor(EmbedThumbnailPP(ydl, already_have_thumbnail=False))
            ydl.run_all_pps("post_process", info)
        self.assertTrue(audio.is_file())
        self.assertFalse(cover.exists())
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(audio)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("video", probe.stdout.lower())

    def test_generic_html_page_falls_back_to_embedded_direct_video(self):
        info = probe_direct_media_url(self.page_url)
        self.assertIsNotNone(info)
        self.assertTrue(info["url"].endswith("/exemplo.mp4"))
        destination = self.root / "generic-page"
        worker = DownloadWorker(
            self.page_url,
            destination,
            "Melhor disponível",
            audio_only=False,
            allow_playlist=False,
            container="Automático",
        )
        result = {"completed": [], "failed": [], "cancelled": []}
        worker.completed.connect(lambda path: result["completed"].append(path))
        worker.failed.connect(lambda error: result["failed"].append(error))
        worker.cancelled.connect(lambda: result["cancelled"].append(True))
        with patch(
            "medialivre.YoutubeDL.download",
            side_effect=DownloadError(f"ERROR: Unsupported URL: {self.page_url}"),
        ):
            worker.run()
        self.assertFalse(result["failed"], result["failed"])
        self.assertFalse(result["cancelled"])
        self.assertTrue(result["completed"])
        self.assertTrue((destination / "exemplo.mp4").is_file())


if __name__ == "__main__":
    unittest.main()
