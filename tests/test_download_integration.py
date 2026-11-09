import functools
import http.server
import shutil
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.embedthumbnail import EmbedThumbnailPP
from yt_dlp.postprocessor.ffmpeg import FFmpegThumbnailsConvertorPP
from yt_dlp.utils import DownloadError

from medialivre import (
    DownloadWorker,
    ParallelDownloadWorker,
    ffmpeg_location,
    media_has_video_stream,
    media_processing_options,
    output_suffix_for_url,
    probe_direct_media_url,
)


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
        cls.second_source = cls.root / "segundo.mp4"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=red:s=320x240:d=2",
                "-f", "lavfi", "-i", "sine=frequency=660:duration=2",
                "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-shortest",
                str(cls.second_source),
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
        for folder, source in (("collision-a", cls.source), ("collision-b", cls.second_source)):
            collision_folder = cls.root / folder
            collision_folder.mkdir()
            shutil.copyfile(source, collision_folder / "same.mp4")

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

    def test_direct_fallback_replaces_namespaced_mp4_without_video(self):
        destination = self.root / "stale-direct-mp4"
        destination.mkdir()
        suffix = output_suffix_for_url(self.page_url)
        target = destination / f"exemplo [link-{suffix}-{suffix}].mp4"
        audio_only = self.root / "direct-audio-only.mp4"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "sine=frequency=330:duration=2",
                "-c:a", "aac", str(audio_only),
            ],
            check=True,
            capture_output=True,
        )
        shutil.copyfile(audio_only, target)
        self.assertFalse(media_has_video_stream(target))

        worker = DownloadWorker(
            self.page_url,
            destination,
            "Melhor disponível",
            audio_only=False,
            allow_playlist=False,
            container="MP4",
            output_suffix=suffix,
        )
        result = worker._download_direct_media(self.page_url, "exemplo")
        self.assertEqual(result, target)
        self.assertTrue(media_has_video_stream(result))

    def test_replaces_existing_mp4_that_has_audio_but_no_video(self):
        destination = self.root / "stale-mp4"
        first = DownloadWorker(
            self.url,
            destination,
            "Melhor disponível",
            audio_only=False,
            allow_playlist=False,
            container="MP4",
            output_suffix=output_suffix_for_url(self.url),
        )
        first_result = {"completed": [], "failed": []}
        first.completed.connect(lambda path: first_result["completed"].append(path))
        first.failed.connect(lambda error: first_result["failed"].append(error))
        first.run()
        self.assertFalse(first_result["failed"], first_result["failed"])
        output = next(destination.glob("*.mp4"))

        audio_only = self.root / "audio-only.mp4"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "sine=frequency=330:duration=1",
                "-vn", "-c:a", "aac", str(audio_only),
            ],
            check=True,
            capture_output=True,
        )
        shutil.copyfile(audio_only, output)

        second = DownloadWorker(
            self.url,
            destination,
            "Melhor disponível",
            audio_only=False,
            allow_playlist=False,
            container="MP4",
            output_suffix=output_suffix_for_url(self.url),
        )
        second_result = {"completed": [], "failed": []}
        second.completed.connect(lambda path: second_result["completed"].append(path))
        second.failed.connect(lambda error: second_result["failed"].append(error))
        second.run()
        self.assertFalse(second_result["failed"], second_result["failed"])
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(output)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("video", probe.stdout.lower())


    def test_parallel_batch_downloads_two_local_videos(self):
        destination = self.root / "parallel-batch"
        urls = [
            self.url,
            f"http://127.0.0.1:{self.server.server_port}/segundo.mp4",
        ]
        worker = ParallelDownloadWorker(
            urls,
            destination,
            "Melhor disponível",
            audio_only=False,
            allow_playlist=False,
            container="MP4",
            download_thumbnail=False,
            concurrency=2,
        )
        result = {"completed": [], "failed": [], "cancelled": []}
        worker.completed.connect(lambda path: result["completed"].append(path))
        worker.failed.connect(lambda error: result["failed"].append(error))
        worker.cancelled.connect(lambda: result["cancelled"].append(True))
        worker.run()
        self.assertFalse(result["failed"], result["failed"])
        self.assertFalse(result["cancelled"])
        self.assertEqual(len(result["completed"]), 1)
        outputs = list(destination.glob("*.mp4"))
        self.assertEqual(len(outputs), 2)
        for output in outputs:
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("video", probe.stdout.lower())


    def test_parallel_batch_keeps_same_basename_urls_as_distinct_files(self):
        destination = self.root / "parallel-name-collision"
        base = f"http://127.0.0.1:{self.server.server_port}"
        urls = [f"{base}/collision-a/same.mp4", f"{base}/collision-b/same.mp4"]
        worker = ParallelDownloadWorker(
            urls,
            destination,
            "Melhor disponível",
            audio_only=False,
            allow_playlist=False,
            container="Automático",
            download_thumbnail=False,
            concurrency=2,
        )
        result = {"completed": [], "failed": []}
        worker.completed.connect(lambda path: result["completed"].append(path))
        worker.failed.connect(lambda error: result["failed"].append(error))
        worker.run()
        self.assertFalse(result["failed"], result["failed"])
        self.assertEqual(len(result["completed"]), 1)
        outputs = list(destination.glob("*.mp4"))
        self.assertEqual(len(outputs), 2)
        self.assertTrue(all("[link-" in output.name for output in outputs))
        self.assertNotEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
        self.assertEqual(
            {output_suffix_for_url(url) for url in urls},
            {output.name.rsplit("[link-", 1)[1].split("]", 1)[0] for output in outputs},
        )

    def test_direct_media_fallback_keeps_same_basename_urls_as_distinct_files(self):
        destination = self.root / "direct-name-collision"
        destination.mkdir()
        base = f"http://127.0.0.1:{self.server.server_port}"
        urls = [f"{base}/collision-a/same.mp4", f"{base}/collision-b/same.mp4"]
        workers = [
            DownloadWorker(
                url,
                destination,
                "Melhor disponível",
                audio_only=False,
                allow_playlist=False,
                container="Automático",
                output_suffix=output_suffix_for_url(url),
                socket_timeout=8,
                retries=1,
            )
            for url in urls
        ]
        with ThreadPoolExecutor(max_workers=2) as pool:
            outputs = list(pool.map(lambda worker: worker._download_direct_media(worker.url, "same"), workers))
        self.assertEqual(len(set(outputs)), 2)
        self.assertTrue(all(output.exists() for output in outputs))
        self.assertNotEqual(outputs[0].read_bytes(), outputs[1].read_bytes())


if __name__ == "__main__":
    unittest.main()
