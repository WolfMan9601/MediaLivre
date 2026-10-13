import functools
import http.server
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from medialivre import DownloadWorker


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


if __name__ == "__main__":
    unittest.main()
