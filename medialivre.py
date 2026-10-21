from __future__ import annotations

import os
import json
import re
import hashlib
import mimetypes
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from html.parser import HTMLParser
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QUrl, QDateTime, QTimer, QLockFile, QSettings, QProcess
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QCheckBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QScrollArea,
)
from yt_dlp import YoutubeDL
from yt_dlp.extractor import gen_extractors
from yt_dlp.utils import DownloadError
from download_scheduler import ScheduleStore, ScheduledDownload, default_database_path
from urllib.request import Request, urlopen

APP_NAME = "MediaLivre"
APP_VERSION = "0.14.0"
UPDATE_REPOSITORY = os.environ.get("MEDIALIVRE_UPDATE_REPOSITORY", "WolfMan9601/MediaLivre")

DIRECT_MEDIA_EXTENSIONS = {
    ".3gp", ".aac", ".avi", ".flac", ".m4a", ".m4v", ".mkv", ".mov",
    ".mp3", ".mp4", ".mpeg", ".mpg", ".oga", ".ogg", ".ogv", ".opus",
    ".wav", ".webm", ".wmv",
}


class _EmbeddedMediaParser(HTMLParser):
    """Read only standard media element URLs from a public HTML page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in {"audio", "source", "video"}:
            return
        attributes = {key.lower(): value for key, value in attrs}
        source = attributes.get("src")
        if source:
            self.sources.append(source.strip())


def _filename_from_content_disposition(value: str) -> str:
    match = re.search(r"filename\*=[^']*''([^;]+)|filename=\"?([^\";]+)", value or "", re.I)
    if not match:
        return ""
    return unquote((match.group(1) or match.group(2)).strip())


def _media_extension(url: str, content_type: str = "", filename: str = "") -> str:
    for candidate in (filename, urlparse(url).path):
        suffix = Path(unquote(candidate)).suffix.lower()
        if suffix in DIRECT_MEDIA_EXTENSIONS:
            return suffix
    guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip().lower())
    return guessed.lower() if guessed and guessed.lower() in DIRECT_MEDIA_EXTENSIONS else ""


def probe_direct_media_url(value: str, _visited: tuple[str, ...] = ()) -> dict | None:
    """Probe a public URL and return a direct media target or a standard HTML media source."""
    if not is_http_url(value) or value in _visited:
        return None
    request = Request(
        value,
        headers={
            "Accept": "video/*, audio/*, application/octet-stream, text/html;q=0.8",
            "Range": "bytes=0-65535",
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            final_url = str(response.geturl() or value)
            content_type = str(response.headers.get("Content-Type") or "").lower()
            content_disposition = str(response.headers.get("Content-Disposition") or "")
            filename = _filename_from_content_disposition(content_disposition)
            extension = _media_extension(final_url, content_type, filename)
            media_type = content_type.split(";", 1)[0].strip()
            if media_type.startswith(("audio/", "video/")) or (
                media_type == "application/octet-stream" and extension
            ) or extension and media_type in {"", "application/octet-stream"}:
                return {
                    "url": final_url,
                    "filename": filename or Path(unquote(urlparse(final_url).path)).name,
                    "extension": extension,
                    "content_type": media_type,
                }
            if not media_type.startswith("text/html"):
                return None
            html = response.read(1024 * 1024).decode("utf-8", errors="replace")
    except Exception:
        return None

    parser = _EmbeddedMediaParser()
    try:
        parser.feed(html)
    except Exception:
        return None
    visited = (*_visited, value, final_url)
    for source in parser.sources:
        candidate = urljoin(final_url, source)
        result = probe_direct_media_url(candidate, visited)
        if result:
            return result
    return None


def resource_path(*parts: str) -> Path:
    """Locate bundled resources both from source and from a PyInstaller build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def is_http_url(value: str) -> bool:
    """Accept only absolute HTTP(S) URLs with a host; do not accept local paths."""
    try:
        parsed = urlparse(value.strip())
        return (
            parsed.scheme.lower() in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


@lru_cache(maxsize=256)
def matching_extractors(value: str) -> tuple[str, ...]:
    """Return specific yt-dlp extractors that recognize a URL, excluding generic."""
    if not is_http_url(value):
        return ()
    matches: list[str] = []
    for extractor in gen_extractors():
        name = str(getattr(extractor, "IE_NAME", "") or "")
        if not name or name == "generic":
            continue
        try:
            if extractor.suitable(value):
                matches.append(name)
        except Exception:
            continue
    return tuple(dict.fromkeys(matches))


def user_facing_download_error(message: str, url: str) -> str:
    """Turn common yt-dlp failures into actionable, non-misleading guidance."""
    clean = str(message or "").strip() or "Falha desconhecida na transferência."
    lowered = clean.lower()
    if "unsupported url" in lowered or "no suitable extractor" in lowered:
        try:
            host = (urlparse(url).hostname or url).lower()
        except ValueError:
            host = url
        extractors = matching_extractors(url)
        if extractors:
            known = ", ".join(extractors[:3])
            return (
                f"A página {host} foi reconhecida por {known}, mas o conteúdo não pôde ser extraído. "
                "Tente a opção Automático e confirme que tem autorização para transferir o conteúdo."
            )
        return (
            f"A página {host} não tem um extrator específico no yt-dlp instalado. "
            "Isto não é uma falha de MP4 ou FFmpeg. Para conteúdo que criou, possui ou está autorizado "
            "a transferir, use o download oficial do serviço, cole uma URL direta HTTP(S) do ficheiro/stream "
            "ou uma página pública que contenha uma tag <video>, <audio> ou <source> direta. "
            "O MediaLivre não contorna DRM, paywalls, autenticação ou controlos de acesso."
        )
    if "requested format is not available" in lowered:
        return (
            "A fonte não disponibilizou o formato solicitado. Tente Formato do vídeo = Automático e "
            "Qualidade = Melhor disponível."
        )
    if "http error 403" in lowered or "forbidden" in lowered:
        return (
            "A origem recusou a transferência (HTTP 403). Verifique se o conteúdo é público e se tem "
            "autorização; o MediaLivre não tenta contornar bloqueios ou autenticação."
        )
    return clean


def should_try_direct_media(message: str) -> bool:
    lowered = str(message or "").lower()
    return "unsupported url" in lowered or "no suitable extractor" in lowered


def collection_label(value: str) -> str:
    """Return a user-facing name for the collection represented by a URL."""
    try:
        parsed = urlparse(value.strip())
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower().rstrip("/")
        if "instagram.com" in host and path and "/" not in path.strip("/"):
            return "Perfil do Instagram"
    except ValueError:
        pass
    return "Playlist/canal"


def is_collection_url(value: str) -> bool:
    """Detect playlist/channel/profile URLs so collections are not reduced to one item."""
    try:
        parsed = urlparse(value.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme.lower() not in {"http", "https"} or not host:
            return False
        path = parsed.path.lower().rstrip("/")
        query = parsed.query.lower()
        if "list=" in query or "/playlist" in path:
            return True
        if "youtube.com" in host or host == "youtu.be":
            return (
                "/channel/" in path
                or path.startswith("/c/")
                or path.startswith("/user/")
                or (path.startswith("/@") and "/watch" not in path)
            )
        if "tiktok.com" in host:
            return path.startswith("/@") and "/video/" not in path
        if "instagram.com" in host:
            parts = [part for part in path.split("/") if part]
            return len(parts) == 1 and parts[0] not in {"reel", "reels", "p", "tv"}
        return False
    except ValueError:
        return False


def playlist_enabled(url: str, requested: bool) -> bool:
    """Expand a collection only when the user left collection downloads enabled."""
    return bool(requested and is_collection_url(url))


def collection_items(info: dict) -> list[dict]:
    """Normalize flat yt-dlp collection entries for the picker and worker."""
    items: list[dict] = []
    for position, entry in enumerate(info.get("entries") or [], start=1):
        if not entry:
            continue
        item_url = (
            entry.get("webpage_url")
            or entry.get("original_url")
            or entry.get("url")
            or ""
        )
        if not isinstance(item_url, str) or not item_url.startswith(("http://", "https://")):
            continue
        try:
            index = int(entry.get("playlist_index") or position)
        except (TypeError, ValueError):
            index = position
        items.append({
            "index": index,
            "id": str(entry.get("id") or index),
            "title": str(entry.get("title") or f"Item {index}"),
            "url": item_url,
        })
    return items


def version_tuple(value: str) -> tuple[int, ...]:
    """Convert a vMAJOR.MINOR.PATCH tag into a comparable tuple."""
    value = value.strip().lower().removeprefix("v")
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", value)
    if not match:
        return (0,)
    return tuple(int(part or 0) for part in match.groups())


def extract_sha256(text: str) -> str | None:
    """Extract the first standard SHA-256 digest from a checksum asset."""
    match = re.search(r"\b([0-9a-fA-F]{64})\b", text or "")
    return match.group(1).lower() if match else None


def installer_launch_arguments() -> list[str]:
    """Return Inno Setup arguments for a silent update that relaunches the app."""
    return ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS", "/NORESTART"]


def start_installer_process(path: str) -> bool:
    """Start the downloaded installer and correctly unwrap PySide6's (ok, pid) result."""
    installer = Path(path)
    if not installer.is_file():
        return False
    result = QProcess.startDetached(
        str(installer),
        installer_launch_arguments(),
        str(installer.parent),
    )
    if isinstance(result, tuple):
        return bool(result[0])
    return bool(result)


class UpdateCheckWorker(QObject):
    releases = Signal(object)
    failed = Signal(str)

    def __init__(self, repository: str, current_version: str) -> None:
        super().__init__()
        self.repository = repository
        self.current_version = current_version

    @Slot()
    def run(self) -> None:
        try:
            endpoint = f"https://api.github.com/repos/{self.repository}/releases?per_page=50"
            request = Request(
                endpoint,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"{APP_NAME}/{self.current_version}",
                },
            )
            with urlopen(request, timeout=10) as response:
                payload = json.load(response)
            normalized = []
            for release in payload if isinstance(payload, list) else []:
                if release.get("draft"):
                    continue
                version = str(release.get("tag_name") or "").strip()
                release_url = str(release.get("html_url") or "").strip()
                if not version or not release_url:
                    continue
                installer_url = ""
                checksum_url = ""
                installer_name = ""
                for asset in release.get("assets") or []:
                    name = str(asset.get("name") or "").lower()
                    if name.startswith("medialivre-setup-") and name.endswith(".exe"):
                        installer_url = str(asset.get("browser_download_url") or "")
                        installer_name = name
                for asset in release.get("assets") or []:
                    name = str(asset.get("name") or "").lower()
                    if installer_name and name == f"{installer_name}.sha256":
                        checksum_url = str(asset.get("browser_download_url") or "")
                        break
                normalized.append({
                    "version": version,
                    "name": str(release.get("name") or version),
                    "release_url": release_url,
                    "installer_url": installer_url,
                    "checksum_url": checksum_url,
                    "prerelease": bool(release.get("prerelease")),
                    "published_at": str(release.get("published_at") or ""),
                })
            normalized.sort(
                key=lambda item: (version_tuple(item["version"]), item["published_at"]),
                reverse=True,
            )
            self.releases.emit(normalized)
        except Exception as exc:
            self.failed.emit(str(exc).strip() or exc.__class__.__name__)


class InstallerDownloadWorker(QObject):
    progress = Signal(int)
    status = Signal(str)
    completed = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, installer_url: str, checksum_url: str, target_path: Path) -> None:
        super().__init__()
        self.installer_url = installer_url
        self.checksum_url = checksum_url
        self.target_path = target_path
        self.cancel_requested = threading.Event()

    def cancel(self) -> None:
        self.cancel_requested.set()

    @Slot()
    def run(self) -> None:
        partial_path = self.target_path.with_name(f".{self.target_path.name}.part")
        try:
            if not self.checksum_url:
                raise ValueError("A Release não publicou o checksum SHA-256 deste instalador.")
            self.target_path.parent.mkdir(parents=True, exist_ok=True)
            partial_path.unlink(missing_ok=True)
            request = Request(
                self.installer_url,
                headers={"Accept": "application/octet-stream", "User-Agent": f"{APP_NAME}/{APP_VERSION}"},
            )
            self.status.emit("A descarregar o instalador…")
            digest = hashlib.sha256()
            with urlopen(request, timeout=30) as response, partial_path.open("wb") as output:
                try:
                    total = int(response.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    total = 0
                downloaded = 0
                while True:
                    if self.cancel_requested.is_set():
                        partial_path.unlink(missing_ok=True)
                        self.cancelled.emit()
                        return
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if total:
                        self.progress.emit(max(0, min(100, int(downloaded * 100 / total))))
            if self.cancel_requested.is_set():
                partial_path.unlink(missing_ok=True)
                self.cancelled.emit()
                return
            self.status.emit("A validar a assinatura SHA-256…")
            checksum_request = Request(
                self.checksum_url,
                headers={"Accept": "text/plain", "User-Agent": f"{APP_NAME}/{APP_VERSION}"},
            )
            with urlopen(checksum_request, timeout=15) as response:
                expected = extract_sha256(response.read().decode("utf-8", errors="replace"))
            if not expected:
                raise ValueError("O ficheiro de checksum não contém um SHA-256 válido.")
            if digest.hexdigest().lower() != expected:
                raise ValueError("A validação SHA-256 do instalador falhou; o ficheiro não será executado.")
            self.target_path.unlink(missing_ok=True)
            partial_path.replace(self.target_path)
            self.progress.emit(100)
            self.completed.emit(str(self.target_path))
        except Exception as exc:
            partial_path.unlink(missing_ok=True)
            if self.cancel_requested.is_set():
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc).strip() or exc.__class__.__name__)


def ffmpeg_location() -> Path | None:
    """Find the bundled FFmpeg directory before falling back to PATH."""
    candidates: list[Path] = []
    configured = os.environ.get("MEDIALIVRE_FFMPEG_DIR")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend([
        Path(sys.executable).resolve().parent / "ffmpeg" / "bin",
        resource_path("ffmpeg", "bin"),
        resource_path("third_party", "ffmpeg", "bin"),
        Path(__file__).resolve().parent / "third_party" / "ffmpeg" / "bin",
    ])
    for candidate in candidates:
        if (candidate / "ffmpeg.exe").is_file() and (candidate / "ffprobe.exe").is_file():
            return candidate
        if (candidate / "ffmpeg").is_file() and (candidate / "ffprobe").is_file():
            return candidate
    return None


def quality_format(quality: str, audio_only: bool, container: str = "Automático") -> str:
    if audio_only:
        return "bestaudio/best"
    max_height = {"1080p": 1080, "720p": 720, "480p": 480}.get(quality)
    height = f"[height<={max_height}]" if max_height else ""
    if container == "MP4":
        # Prefer H.264/AVC + AAC/M4A for broad Windows player compatibility.
        # Fall back only to an MP4 that still contains video, never to audio-only.
        return (
            f"bestvideo[vcodec^=avc1][ext=mp4]{height}+bestaudio[ext=m4a]/"
            f"best[vcodec^=avc1][ext=mp4]{height}/"
            f"bestvideo[ext=mp4]{height}+bestaudio[ext=m4a]/"
            f"best[ext=mp4]{height}"
        )
    return f"bestvideo{height}+bestaudio/best{height}"


def container_options(container: str) -> dict:
    """Return yt-dlp/FFmpeg settings for the selected final video container."""
    if container == "MKV":
        return {
            "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mkv"}],
        }
    if container == "AVI":
        return {
            "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "avi"}],
            "postprocessor_args": {
                "videoconvertor+ffmpeg_o": ["-c:a", "libmp3lame", "-b:a", "192k"],
            },
        }
    if container == "MP4":
        return {"merge_output_format": "mp4"}
    return {}


def media_processing_options(download_thumbnail: bool, audio_only: bool, container: str) -> dict:
    """Embed cover art in MP3; video downloads intentionally produce only the video file."""
    options: dict = {}
    postprocessors = []
    embed_audio_cover = bool(download_thumbnail and audio_only)
    if embed_audio_cover:
        options["writethumbnail"] = True
        postprocessors.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg"})
    if audio_only:
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        })
    else:
        video_options = container_options(container)
        postprocessors.extend(video_options.pop("postprocessors", []))
        if container == "MP4":
            postprocessors.append({"key": "FFmpegVideoConvertor", "preferedformat": "mp4"})
            video_options["postprocessor_args"] = {
                "videoconvertor+ffmpeg_o": [
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                ],
            }
        options.update(video_options)
    if embed_audio_cover:
        # False tells yt-dlp to remove the temporary JPG after embedding it in MP3.
        postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})
    if postprocessors:
        options["postprocessors"] = postprocessors
    return options


def progress_details(data: dict) -> tuple[int, int, str, str]:
    """Return overall percent, current-item percent, item label and batch label."""
    info = data.get("info_dict") or {}
    status = data.get("status")
    total_bytes = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
    downloaded = data.get("downloaded_bytes") or 0
    item_percent = 100 if status == "finished" else (
        int(downloaded * 100 / total_bytes) if total_bytes else 0
    )
    item_percent = max(0, min(100, item_percent))

    def number(value):
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    index = number(info.get("playlist_index"))
    count = number(info.get("n_entries")) or number(info.get("playlist_count"))
    title = str(info.get("title") or "A preparar o item…")
    playlist = str(info.get("playlist_title") or info.get("playlist") or "Lista")
    if index and count and count > 0:
        overall = int(((index - 1 + item_percent / 100) / count) * 100)
        item_label = f"Item {index}/{count} · {title}"
        batch_label = f"{playlist} · item {index} de {count}"
    elif index:
        overall = item_percent
        item_label = f"Item {index} · {title}"
        batch_label = f"{playlist} · item {index} (total por determinar)"
    else:
        overall = item_percent
        item_label = title
        batch_label = "Progresso geral"
    return max(0, min(100, overall)), item_percent, item_label, batch_label


class CollectionInspectWorker(QObject):
    found = Signal(object, str)
    failed = Signal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    @Slot()
    def run(self) -> None:
        try:
            options = {
                "extract_flat": True,
                "skip_download": True,
                "noplaylist": False,
                "ignoreerrors": True,
                "quiet": True,
                "no_warnings": False,
                "socket_timeout": 20,
            }
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(self.url, download=False)
            items = collection_items(info or {})
            if not items:
                raise ValueError(f"Não foram encontrados itens disponíveis nesta {collection_label(self.url)}.")
            title = str((info or {}).get("title") or (info or {}).get("playlist_title") or collection_label(self.url))
            self.found.emit(items, title)
        except Exception as exc:
            self.failed.emit(user_facing_download_error(str(exc), self.url))


class CollectionSelectionDialog(QDialog):
    def __init__(self, title: str, items: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Escolher itens para transferir")
        self.setMinimumSize(720, 500)
        layout = QVBoxLayout(self)
        heading = QLabel(
            f"{title}\nDesmarque os itens que não pretende baixar. "
            "Pode saltar o item atual durante a transferência."
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.items_list = QListWidget()
        self.items_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for item in items:
            row = QListWidgetItem(f"{item['index']}. {item['title']}")
            row.setData(Qt.ItemDataRole.UserRole, item)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Checked)
            row.setToolTip(item["url"])
            self.items_list.addItem(row)
        layout.addWidget(self.items_list, 1)
        actions = QHBoxLayout()
        select_all = QPushButton("Selecionar todos")
        clear_all = QPushButton("Limpar seleção")
        select_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        clear_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        actions.addWidget(select_all)
        actions.addWidget(clear_all)
        actions.addStretch()
        layout.addLayout(actions)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_selected)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, state: Qt.CheckState) -> None:
        for index in range(self.items_list.count()):
            self.items_list.item(index).setCheckState(state)

    def _accept_if_selected(self) -> None:
        if not self.selected_items():
            QMessageBox.warning(self, "Nenhum item selecionado", "Marque pelo menos um item para continuar.")
            return
        self.accept()

    def selected_items(self) -> list[dict]:
        selected: list[dict] = []
        for index in range(self.items_list.count()):
            row = self.items_list.item(index)
            if row.checkState() == Qt.CheckState.Checked:
                selected.append(row.data(Qt.ItemDataRole.UserRole))
        return selected


class ReleaseSelectionDialog(QDialog):
    def __init__(self, releases: list[dict], current_version: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Atualizações do MediaLivre")
        self.setMinimumWidth(560)
        self.releases = releases
        layout = QVBoxLayout(self)
        heading = QLabel(
            f"Versão instalada: {current_version}\n"
            "Escolha uma Release. A app descarrega, valida e inicia automaticamente o instalador oficial."
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.release_combo = QComboBox()
        for release in releases:
            suffix = " (pré-lançamento)" if release.get("prerelease") else ""
            current = " (atual)" if version_tuple(release["version"]) == version_tuple(current_version) else ""
            asset = (
                " · atualização automática disponível"
                if release.get("installer_url") and release.get("checksum_url")
                else " · sem instalador validado"
            )
            self.release_combo.addItem(
                f"{release['version']}{suffix}{current}{asset}",
                release,
            )
        layout.addWidget(self.release_combo)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self.release_combo.currentIndexChanged.connect(self._update_detail)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.open_button = buttons.addButton("Atualizar automaticamente", QDialogButtonBox.ButtonRole.AcceptRole)
        self.open_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_detail(0)

    def _update_detail(self, index: int) -> None:
        release = self.release_combo.itemData(index) or {}
        if release.get("installer_url") and release.get("checksum_url"):
            target = "descarregará e validará o instalador automaticamente"
            self.open_button.setText("Atualizar automaticamente")
        else:
            target = "abrirá a página da Release (sem instalador e checksum validados)"
            self.open_button.setText("Abrir página da Release")
        self.detail.setText(f"{release.get('name', release.get('version', ''))}\nAção: {target}.")

    def selected_release(self) -> dict | None:
        return self.release_combo.currentData()


class SkipCurrentItem(Exception):
    """Internal control flow used to skip the active playlist entry."""


class DirectMediaCancelled(Exception):
    """Internal control flow for cancelling a direct HTTP media transfer."""


class DirectMediaUnavailable(Exception):
    """The URL did not resolve to a standard public direct media resource."""


def _safe_direct_stem(value: str) -> str:
    stem = Path(unquote(value or "")).stem or "media"
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem).strip(" .")
    return (stem[:140] or "media")


class DownloadWorker(QObject):
    progress = Signal(int, str)
    item_progress = Signal(int, str)
    item_started = Signal(str)
    log_line = Signal(str)
    completed = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, url: str, destination: Path, quality: str,
                 audio_only: bool, allow_playlist: bool, container: str = "Automático",
                 download_thumbnail: bool = True, selected_items: list[dict] | None = None) -> None:
        super().__init__()
        self.url = url
        self.destination = destination
        self.quality = quality
        self.audio_only = audio_only
        self.allow_playlist = allow_playlist
        self.container = container
        self.download_thumbnail = download_thumbnail
        self.selected_items = selected_items
        self.cancel_requested = threading.Event()
        self.skip_requested = threading.Event()
        self.last_percent = -1
        self.last_item_key = None
        self.current_position = 1
        self.total_items = 1
        self.collection_title = collection_label(url)

    def cancel(self) -> None:
        self.cancel_requested.set()

    def skip_current_item(self) -> None:
        self.skip_requested.set()

    def _progress_hook(self, data: dict) -> None:
        if self.cancel_requested.is_set():
            raise DownloadError("Transferência cancelada pelo utilizador.")
        if self.skip_requested.is_set():
            self.skip_requested.clear()
            raise SkipCurrentItem()
        status = data.get("status")
        if status == "downloading":
            _overall, percent, item_label, batch_label = progress_details(data)
            info = data.get("info_dict") or {}
            if self.total_items > 1:
                title = str(info.get("title") or "A preparar o item…")
                item_label = f"Item {self.current_position}/{self.total_items} · {title}"
                batch_label = (
                    f"{self.collection_title} · item {self.current_position} de {self.total_items}"
                )
                overall = int(
                    ((self.current_position - 1 + percent / 100) / self.total_items) * 100
                )
            else:
                overall = _overall
            item_key = (info.get("playlist_index"), info.get("id"), info.get("title"))
            if percent != self.last_percent or item_key != self.last_item_key:
                self.last_percent = percent
                self.last_item_key = item_key
                speed = data.get("_speed_str", "")
                eta = data.get("_eta_str", "")
                detail = " · ".join(x for x in (speed, f"restam {eta}" if eta else "") if x)
                self.progress.emit(overall, " · ".join(x for x in (batch_label, detail) if x))
                self.item_progress.emit(percent, item_label)
        elif status == "finished":
            _overall, percent, item_label, batch_label = progress_details(data)
            if self.total_items > 1:
                title = str((data.get("info_dict") or {}).get("title") or item_label)
                item_label = f"Item {self.current_position}/{self.total_items} · {title}"
                batch_label = (
                    f"{self.collection_title} · item {self.current_position} de {self.total_items}"
                )
                overall = int(
                    ((self.current_position - 1 + percent / 100) / self.total_items) * 100
                )
            else:
                overall = _overall
            self.progress.emit(overall, f"{batch_label} · a preparar o ficheiro…")
            self.item_progress.emit(percent, item_label)

    def _resolve_items(self, collection_enabled: bool) -> list[dict]:
        if self.selected_items is not None:
            return list(self.selected_items)
        if not collection_enabled:
            return [{"index": 1, "id": "single", "title": self.url, "url": self.url}]
        inspect_options = {
            "extract_flat": True,
            "skip_download": True,
            "noplaylist": False,
            "ignoreerrors": True,
            "quiet": True,
            "socket_timeout": 20,
        }
        with YoutubeDL(inspect_options) as ydl:
            info = ydl.extract_info(self.url, download=False)
        items = collection_items(info or {})
        self.collection_title = str((info or {}).get("title") or collection_label(self.url))
        if not items:
            raise ValueError(f"Não foram encontrados itens disponíveis nesta {collection_label(self.url)}.")
        return items

    def _download_options(self) -> dict:
        options: dict = {
            "format": quality_format(self.quality, self.audio_only, self.container),
            "outtmpl": str(self.destination / "%(title).180B [%(id)s].%(ext)s"),
            "noplaylist": True,
            "windowsfilenames": True,
            "restrictfilenames": False,
            "continuedl": True,
            "overwrites": False,
            "progress_hooks": [self._progress_hook],
            "quiet": True,
            "no_warnings": False,
            "logger": self,
            "ignoreerrors": False,
            "socket_timeout": 20,
            "retries": 3,
            "fragment_retries": 3,
        }
        location = ffmpeg_location()
        if location:
            options["ffmpeg_location"] = str(location)
        elif self.container != "Automático" or self.audio_only:
            self.log_line.emit("Aviso: FFmpeg/ffprobe não encontrado; conversão de formato pode falhar.")
        options.update(media_processing_options(self.download_thumbnail, self.audio_only, self.container))
        return options

    def _direct_progress(self, percent: int, title: str) -> None:
        percent = max(0, min(100, int(percent)))
        if self.total_items > 1:
            overall = int(((self.current_position - 1 + percent / 100) / self.total_items) * 100)
            batch_label = f"{self.collection_title} · item {self.current_position} de {self.total_items}"
            item_label = f"Item {self.current_position}/{self.total_items} · {title}"
        else:
            overall = percent
            batch_label = "URL direta"
            item_label = title
        self.progress.emit(overall, batch_label)
        self.item_progress.emit(percent, item_label)

    def _direct_ffmpeg_binary(self) -> str | None:
        location = ffmpeg_location()
        if location:
            for name in ("ffmpeg.exe", "ffmpeg"):
                candidate = location / name
                if candidate.is_file():
                    return str(candidate)
        return shutil.which("ffmpeg")

    def _convert_direct_media(self, source: Path, target: Path) -> None:
        binary = self._direct_ffmpeg_binary()
        if not binary:
            raise DirectMediaUnavailable(
                "FFmpeg não foi encontrado para converter esta URL direta. "
                "Instale FFmpeg ou use Formato do vídeo = Automático."
            )
        if self.audio_only:
            command = [binary, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-vn", "-codec:a", "libmp3lame", "-b:a", "192k", str(target)]
        elif self.container == "MP4":
            command = [binary, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(target)]
        elif self.container == "MKV":
            command = [binary, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-map", "0", "-c", "copy", str(target)]
        elif self.container == "AVI":
            command = [binary, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-c:v", "libxvid", "-c:a", "libmp3lame", "-b:a", "192k", str(target)]
        else:
            source.replace(target)
            return
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        while process.poll() is None:
            if self.cancel_requested.is_set():
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise DirectMediaCancelled()
            time.sleep(0.1)
        error = (process.stderr.read() if process.stderr else "").strip()
        if process.returncode:
            raise DirectMediaUnavailable(error or "O FFmpeg não conseguiu converter a URL direta.")

    def _download_direct_media(self, url: str, title: str) -> Path:
        info = probe_direct_media_url(url)
        if not info:
            raise DirectMediaUnavailable(
                "A URL não devolveu um ficheiro de áudio/vídeo público nem uma tag HTML "
                "<video>, <audio> ou <source> utilizável."
            )
        source_extension = info.get("extension") or ""
        if not source_extension:
            raise DirectMediaUnavailable("O tipo do ficheiro direto não pôde ser identificado com segurança.")
        filename = str(info.get("filename") or "")
        stem = _safe_direct_stem(filename or title or "media")
        target_extension = ".mp3" if self.audio_only else {
            "MP4": ".mp4",
            "MKV": ".mkv",
            "AVI": ".avi",
        }.get(self.container, source_extension)
        target = self.destination / f"{stem}{target_extension}"
        if target.exists():
            self.log_line.emit(f"Ficheiro já existe; item ignorado: {target.name}")
            self._direct_progress(100, title or target.name)
            return target
        source_handle = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{stem}.",
            suffix=f".source{source_extension}",
            dir=self.destination,
            delete=False,
        )
        source = Path(source_handle.name)
        source_handle.close()
        converted = target.with_name(f".{target.name}.part")
        try:
            request = Request(
                str(info["url"]),
                headers={"Accept": "*/*", "User-Agent": f"{APP_NAME}/{APP_VERSION}"},
            )
            self.log_line.emit(f"URL direta detetada: {info['url']}")
            with urlopen(request, timeout=30) as response, source.open("wb") as output:
                try:
                    total = int(response.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    total = 0
                downloaded = 0
                while True:
                    if self.cancel_requested.is_set():
                        raise DirectMediaCancelled()
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        self._direct_progress(int(downloaded * 100 / total), title or target.name)
            if self.cancel_requested.is_set():
                raise DirectMediaCancelled()
            if self.audio_only or self.container in {"MP4", "MKV", "AVI"}:
                converted.unlink(missing_ok=True)
                self._convert_direct_media(source, converted)
                converted.replace(target)
            else:
                source.replace(target)
            self._direct_progress(100, title or target.name)
            return target
        finally:
            source.unlink(missing_ok=True)
            converted.unlink(missing_ok=True)

    @Slot()
    def run(self) -> None:
        try:
            self.destination.mkdir(parents=True, exist_ok=True)
            collection_enabled = playlist_enabled(self.url, self.allow_playlist)
            items = self._resolve_items(collection_enabled)
            if not items:
                raise ValueError("Nenhum item foi selecionado para transferência.")
            self.total_items = len(items)
            options = self._download_options()
            if collection_enabled:
                self.log_line.emit(
                    f"{collection_label(self.url)}: {self.total_items} item(ns) selecionado(s) para transferência."
                )
            output_format = "MP3" if self.audio_only else (self.container or "Automático")
            cover_status = "incorporada no MP3" if self.audio_only and self.download_thumbnail else "não (vídeo sem JPG separado)"
            self.log_line.emit(f"Formato selecionado: {output_format}. Capa: {cover_status}.")
            failures: list[str] = []
            completed_items = 0
            with YoutubeDL(options) as ydl:
                for position, item in enumerate(items, start=1):
                    if self.cancel_requested.is_set():
                        self.cancelled.emit()
                        return
                    self.current_position = position
                    self.last_percent = -1
                    self.last_item_key = None
                    self.skip_requested.clear()
                    self.log_line.emit(f"A iniciar item {position}/{self.total_items}: {item['title']}")
                    self.item_started.emit(str(item["title"]))
                    try:
                        ydl.download([item["url"]])
                    except SkipCurrentItem:
                        self.log_line.emit(f"Item ignorado: {item['title']}")
                        self.progress.emit(
                            int(position * 100 / self.total_items),
                            f"Item {position}/{self.total_items} ignorado",
                        )
                        self.item_progress.emit(100, f"Item {position}/{self.total_items} · ignorado")
                        continue
                    except DownloadError as exc:
                        if self.cancel_requested.is_set():
                            self.cancelled.emit()
                            return
                        message = user_facing_download_error(str(exc), item["url"])
                        direct_error = None
                        if should_try_direct_media(str(exc)):
                            try:
                                self._download_direct_media(item["url"], str(item["title"]))
                                completed_items += 1
                                self.log_line.emit(
                                    f"Transferência direta concluída: {item['title']}"
                                )
                                continue
                            except DirectMediaCancelled:
                                self.cancelled.emit()
                                return
                            except DirectMediaUnavailable as direct_exc:
                                direct_error = str(direct_exc).strip()
                        if direct_error:
                            message = f"{message}\nTentativa de URL direta: {direct_error}"
                        failures.append(f"{item['title']}: {message}")
                        self.log_line.emit(f"Erro no item {position}/{self.total_items}: {message}")
                        if self.total_items == 1:
                            raise DownloadError(message)
                        continue
                    completed_items += 1
            if self.cancel_requested.is_set():
                self.cancelled.emit()
            elif failures and completed_items == 0:
                self.failed.emit("Nenhum item foi transferido com sucesso.\n" + "\n".join(failures))
            else:
                self.progress.emit(100, "Concluído")
                self.completed.emit(str(self.destination))
        except Exception as exc:
            if self.cancel_requested.is_set():
                self.cancelled.emit()
            else:
                message = user_facing_download_error(str(exc), self.url)
                self.failed.emit(message)

    # yt-dlp logger protocol
    def debug(self, message: str) -> None:
        if message.startswith("[debug]"):
            return
        self.log_line.emit(message)

    def info(self, message: str) -> None:
        self.log_line.emit(message)

    def warning(self, message: str) -> None:
        self.log_line.emit(f"Aviso: {message}")

    def error(self, message: str) -> None:
        self.log_line.emit(f"Erro: {message}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} · Transferências de media")
        self.setMinimumSize(680, 520)
        self.resize(940, 760)
        self.thread: QThread | None = None
        self.worker: DownloadWorker | None = None
        self.selection_thread: QThread | None = None
        self.selection_worker: CollectionInspectWorker | None = None
        self.update_thread: QThread | None = None
        self.update_worker: UpdateCheckWorker | None = None
        self.install_update_thread: QThread | None = None
        self.install_update_worker: InstallerDownloadWorker | None = None
        self.install_update_progress: QProgressDialog | None = None
        self.available_releases: list[dict] = []
        self._manual_update_check = False
        self._selection_start_after = False
        self._prepared_items_url: str | None = None
        self._prepared_items: list[dict] | None = None
        self._active_schedule_id: str | None = None
        self._close_when_idle = False
        self.destination = Path.home() / "Downloads"
        self.schedule_store = ScheduleStore()
        self.schedule_store.recover_interrupted_jobs()
        self._build_ui()
        self._apply_style()
        self._refresh_scheduled_jobs()
        self.schedule_timer = QTimer(self)
        self.schedule_timer.timeout.connect(self._run_due_schedules)
        self.schedule_timer.start(5000)
        QTimer.singleShot(0, self._run_due_schedules)
        QTimer.singleShot(1500, self._check_for_updates)

    def _build_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setObjectName("mainScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root = QWidget()
        root.setObjectName("pageContent")
        scroll.setWidget(root)
        self.setCentralWidget(scroll)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        brand = QVBoxLayout()
        title = QLabel("MediaLivre")
        title.setObjectName("title")
        subtitle = QLabel("Transferências de YouTube, TikTok, Instagram e outras fontes suportadas.")
        subtitle.setObjectName("subtitle")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand)
        header.addStretch()
        self.update_button = QPushButton("Atualizações")
        self.update_button.setToolTip("Consultar Releases e escolher a versão para instalar.")
        self.update_button.clicked.connect(self._open_update_center)
        header.addWidget(self.update_button)
        version = QLabel(f"VERSÃO {APP_VERSION}")
        version.setObjectName("version")
        header.addWidget(version, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 20)
        card_layout.setSpacing(11)

        url_label = QLabel("LIGAÇÃO DO VÍDEO OU ÁUDIO")
        url_label.setObjectName("fieldLabel")
        card_layout.addWidget(url_label)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://…")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.returnPressed.connect(lambda: self.start_download())
        card_layout.addWidget(self.url_input)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        qbox = QVBoxLayout()
        qlabel = QLabel("QUALIDADE")
        qlabel.setObjectName("fieldLabel")
        self.quality = QComboBox()
        self.quality.addItems(["Melhor disponível", "1080p", "720p", "480p"])
        qbox.addWidget(qlabel)
        qbox.addWidget(self.quality)
        controls.addLayout(qbox, 1)

        fbox = QVBoxLayout()
        flabel = QLabel("FORMATO DO VÍDEO")
        flabel.setObjectName("fieldLabel")
        self.video_format = QComboBox()
        self.video_format.addItems(["Automático", "MP4", "MKV", "AVI"])
        fbox.addWidget(flabel)
        fbox.addWidget(self.video_format)
        controls.addLayout(fbox, 1)

        self.audio_only = QCheckBox("Extrair apenas áudio (MP3)")
        self.audio_only.toggled.connect(self._toggle_audio)
        self.thumbnail_check = QCheckBox("Incorporar capa no MP3 (sem imagem JPG separada)")
        self.thumbnail_check.setChecked(False)
        self.thumbnail_check.setEnabled(False)
        self.thumbnail_check.setToolTip(
            "Quando o áudio MP3 está ativo, incorpora a capa no quadrado da música e remove o JPG temporário."
        )
        card_layout.addLayout(controls)
        card_layout.addWidget(self.audio_only)
        card_layout.addWidget(self.thumbnail_check)

        destination_label = QLabel("PASTA DE DESTINO")
        destination_label.setObjectName("fieldLabel")
        card_layout.addWidget(destination_label)
        dest_row = QHBoxLayout()
        self.destination_text = QLineEdit(str(self.destination))
        self.destination_text.setReadOnly(True)
        self.browse_button = QPushButton("Escolher pasta")
        self.browse_button.clicked.connect(self.choose_destination)
        dest_row.addWidget(self.destination_text, 1)
        dest_row.addWidget(self.browse_button)
        card_layout.addLayout(dest_row)

        self.playlist_check = QCheckBox("Transferir playlists e canais completos")
        self.playlist_check.setChecked(True)
        self.playlist_check.setToolTip(
            "Ao iniciar uma playlist, canal ou perfil suportado, poderá escolher exatamente quais itens baixar."
        )
        playlist_row = QHBoxLayout()
        playlist_row.addWidget(self.playlist_check, 1)
        self.choose_items_button = QPushButton("Escolher itens")
        self.choose_items_button.setToolTip("Ler a playlist, canal ou perfil e selecionar itens específicos.")
        self.choose_items_button.clicked.connect(self._choose_collection_items)
        playlist_row.addWidget(self.choose_items_button)
        card_layout.addLayout(playlist_row)

        layout.addWidget(card)

        schedule_card = QFrame()
        schedule_card.setObjectName("card")
        schedule_layout = QVBoxLayout(schedule_card)
        schedule_layout.setContentsMargins(16, 12, 16, 12)
        schedule_layout.setSpacing(8)
        schedule_title = QLabel("AGENDAMENTO · HORA LOCAL")
        schedule_title.setObjectName("fieldLabel")
        schedule_layout.addWidget(schedule_title)
        schedule_row = QHBoxLayout()
        self.schedule_time = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.schedule_time.setCalendarPopup(True)
        self.schedule_time.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.schedule_time.setMinimumDateTime(QDateTime.currentDateTime().addSecs(30))
        self.schedule_button = QPushButton("Agendar este download")
        self.schedule_button.clicked.connect(self._schedule_current_download)
        schedule_row.addWidget(self.schedule_time, 1)
        schedule_row.addWidget(self.schedule_button)
        schedule_layout.addLayout(schedule_row)
        self.scheduled_list = QListWidget()
        self.scheduled_list.setObjectName("scheduledList")
        self.scheduled_list.setMinimumHeight(58)
        self.scheduled_list.setMaximumHeight(95)
        self.scheduled_list.currentItemChanged.connect(self._update_schedule_actions)
        self.schedule_empty_label = QLabel("Nenhum download agendado.")
        self.schedule_empty_label.setObjectName("emptyState")
        self.schedule_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        schedule_layout.addWidget(self.schedule_empty_label)
        schedule_layout.addWidget(self.scheduled_list)
        schedule_actions = QHBoxLayout()
        self.cancel_schedule_button = QPushButton("Cancelar agendamento selecionado")
        self.cancel_schedule_button.setEnabled(False)
        self.cancel_schedule_button.clicked.connect(self._cancel_selected_schedule)
        schedule_actions.addStretch()
        schedule_actions.addWidget(self.cancel_schedule_button)
        schedule_layout.addLayout(schedule_actions)
        layout.addWidget(schedule_card)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("Iniciar transferência")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(lambda _checked=False: self.start_download())
        self.skip_button = QPushButton("Saltar item")
        self.skip_button.setEnabled(False)
        self.skip_button.setToolTip("Ignorar apenas o item atual e continuar com os seguintes.")
        self.skip_button.clicked.connect(self.skip_current_item)
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_download)
        self.open_button = QPushButton("Abrir pasta")
        self.open_button.clicked.connect(self.open_destination)
        action_row.addWidget(self.start_button, 1)
        action_row.addWidget(self.skip_button)
        action_row.addWidget(self.cancel_button)
        action_row.addWidget(self.open_button)
        layout.addLayout(action_row)

        status_row = QHBoxLayout()
        self.status_label = QLabel("Pronto para começar")
        self.status_label.setObjectName("status")
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("percent")
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.percent_label)
        layout.addLayout(status_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        item_row = QHBoxLayout()
        item_heading = QLabel("ITEM ATUAL")
        item_heading.setObjectName("fieldLabel")
        self.item_label = QLabel("À espera de item")
        self.item_label.setObjectName("itemLabel")
        self.item_label.setTextFormat(Qt.TextFormat.PlainText)
        self.item_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.item_percent = QLabel("0%")
        self.item_percent.setObjectName("percent")
        item_row.addWidget(item_heading)
        item_row.addWidget(self.item_label, 1)
        item_row.addWidget(self.item_percent)
        layout.addLayout(item_row)
        self.item_progress_bar = QProgressBar()
        self.item_progress_bar.setRange(0, 100)
        self.item_progress_bar.setValue(0)
        self.item_progress_bar.setTextVisible(False)
        layout.addWidget(self.item_progress_bar)

        log_label = QLabel("ATIVIDADE")
        log_label.setObjectName("fieldLabel")
        layout.addWidget(log_label)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("O progresso e as mensagens da transferência aparecem aqui.")
        self.log.document().setMaximumBlockCount(250)
        self.log.setMinimumHeight(105)
        layout.addWidget(self.log, 1)

        notice = QLabel(
            "Use apenas com conteúdos que tem direito ou autorização para transferir. "
            "O MediaLivre não contorna DRM, autenticação ou controlos de acesso."
        )
        notice.setObjectName("notice")
        notice.setWordWrap(True)
        layout.addWidget(notice)

    def _choose_collection_items(self) -> None:
        url = self.url_input.text().strip()
        if not is_http_url(url):
            QMessageBox.warning(self, "Ligação inválida", "Introduza uma ligação HTTP(S) antes de escolher itens.")
            return
        if not is_collection_url(url):
            QMessageBox.information(
                self,
                "Não é uma coleção",
                "Esta ligação parece ser um item individual, como um vídeo. Pode iniciar o download diretamente.",
            )
            return
        self._begin_collection_selection(url, start_after=False)

    def _begin_collection_selection(self, url: str, start_after: bool) -> None:
        if self.selection_thread and self.selection_thread.isRunning():
            return
        if self.thread and self.thread.isRunning():
            return
        self._selection_start_after = start_after
        self.status_label.setText("A ler a coleção…")
        self._set_busy(True)
        self.selection_thread = QThread(self)
        self.selection_worker = CollectionInspectWorker(url)
        self.selection_worker.moveToThread(self.selection_thread)
        self.selection_thread.started.connect(self.selection_worker.run)
        self.selection_worker.found.connect(self._on_collection_found)
        self.selection_worker.failed.connect(self._on_collection_failed)
        self.selection_worker.found.connect(self.selection_thread.quit)
        self.selection_worker.failed.connect(self.selection_thread.quit)
        self.selection_thread.finished.connect(self._selection_thread_finished)
        self.selection_thread.start()

    @Slot(object, str)
    def _on_collection_found(self, items: list[dict], title: str) -> None:
        url = self.url_input.text().strip()
        dialog = CollectionSelectionDialog(title, items, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        selected = dialog.selected_items() if accepted else []
        start_after = self._selection_start_after
        self._selection_start_after = False
        self._set_busy(False)
        if not selected:
            self._prepared_items_url = None
            self._prepared_items = None
            self.status_label.setText("Seleção cancelada")
            return
        if start_after:
            self.start_download(selected_items=selected)
        else:
            self._prepared_items_url = url
            self._prepared_items = selected
            self.status_label.setText(f"{len(selected)} item(ns) selecionado(s); pronto para começar")
            self._append_log(f"Seleção guardada: {len(selected)} de {len(items)} item(ns).")

    @Slot(str)
    def _on_collection_failed(self, message: str) -> None:
        self._selection_start_after = False
        self._set_busy(False)
        self.status_label.setText("Não foi possível ler a coleção")
        self._append_log(f"Erro ao ler a coleção: {message}")
        QMessageBox.warning(self, "Coleção indisponível", message)

    @Slot()
    def _selection_thread_finished(self) -> None:
        if self.selection_worker:
            self.selection_worker.deleteLater()
        if self.selection_thread:
            self.selection_thread.deleteLater()
        self.selection_worker = None
        self.selection_thread = None

    def _check_for_updates(self) -> None:
        settings = QSettings(APP_NAME, APP_NAME)
        try:
            last_checked = int(settings.value("updates/last_checked", 0))
        except (TypeError, ValueError):
            last_checked = 0
        now = int(datetime.now(timezone.utc).timestamp())
        if now - last_checked < 24 * 60 * 60:
            return
        settings.setValue("updates/last_checked", now)
        self._start_update_check(manual=False)

    @Slot()
    def _open_update_center(self) -> None:
        self._start_update_check(manual=True)

    def _start_update_check(self, manual: bool) -> None:
        if self.update_thread and self.update_thread.isRunning():
            return
        self._manual_update_check = manual
        self.update_button.setEnabled(False)
        self.update_button.setText("A verificar…")
        self.update_thread = QThread(self)
        self.update_worker = UpdateCheckWorker(UPDATE_REPOSITORY, APP_VERSION)
        self.update_worker.moveToThread(self.update_thread)
        self.update_thread.started.connect(self.update_worker.run)
        self.update_worker.releases.connect(self._on_releases_ready)
        self.update_worker.failed.connect(self._update_check_failed)
        self.update_worker.releases.connect(self.update_thread.quit)
        self.update_worker.failed.connect(self.update_thread.quit)
        self.update_thread.finished.connect(self._update_thread_finished)
        self.update_thread.start()

    @Slot(object)
    def _on_releases_ready(self, releases: list[dict]) -> None:
        self.available_releases = list(releases)
        newer = [
            release for release in releases
            if version_tuple(release["version"]) > version_tuple(APP_VERSION)
        ]
        if newer:
            latest = newer[0]["version"]
            self.update_button.setText(f"Atualização {latest}")
            self.update_button.setToolTip("Existe uma versão nova. Clique para escolher qualquer Release disponível.")
        else:
            self.update_button.setText("Atualizações")
            self.update_button.setToolTip("Consultar Releases e escolher a versão para instalar.")
        if self._manual_update_check:
            self._show_release_selector(releases)

    def _show_release_selector(self, releases: list[dict]) -> None:
        if not releases:
            QMessageBox.information(
                self,
                "Atualizações",
                "Não foram encontradas Releases publicadas no repositório.",
            )
            return
        dialog = ReleaseSelectionDialog(releases, APP_VERSION, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        release = dialog.selected_release() or {}
        installer_url = str(release.get("installer_url") or "")
        if installer_url and release.get("checksum_url"):
            self._start_installer_download(release)
        elif release.get("release_url"):
            QDesktopServices.openUrl(QUrl(str(release["release_url"])))

    def _start_installer_download(self, release: dict) -> None:
        if self.install_update_thread and self.install_update_thread.isRunning():
            return
        if self.thread and self.thread.isRunning():
            QMessageBox.information(
                self,
                "Transferência em curso",
                "Conclua ou cancele a transferência atual antes de atualizar o MediaLivre.",
            )
            return
        installer_url = str(release.get("installer_url") or "")
        if not installer_url:
            return
        installer_name = Path(urlparse(installer_url).path).name
        if not installer_name.lower().endswith(".exe"):
            release_version = str(release.get("version") or "0.0.0").lstrip("vV")
            installer_name = f"MediaLivre-Setup-{release_version}.exe"
        target_path = Path(tempfile.gettempdir()) / installer_name
        self.install_update_progress = QProgressDialog(
            "A preparar a atualização…",
            "Cancelar",
            0,
            100,
            self,
        )
        self.install_update_progress.setWindowTitle("Atualização do MediaLivre")
        self.install_update_progress.setAutoClose(False)
        self.install_update_progress.setAutoReset(False)
        self.install_update_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.install_update_progress.show()
        self.update_button.setEnabled(False)
        self.update_button.setText("A atualizar…")
        self.install_update_thread = QThread(self)
        self.install_update_worker = InstallerDownloadWorker(
            installer_url,
            str(release.get("checksum_url") or ""),
            target_path,
        )
        self.install_update_worker.moveToThread(self.install_update_thread)
        self.install_update_thread.started.connect(self.install_update_worker.run)
        self.install_update_worker.progress.connect(self.install_update_progress.setValue)
        self.install_update_worker.status.connect(self.install_update_progress.setLabelText)
        self.install_update_worker.completed.connect(self._on_installer_downloaded)
        self.install_update_worker.failed.connect(self._on_installer_download_failed)
        self.install_update_worker.cancelled.connect(self._on_installer_download_cancelled)
        self.install_update_worker.completed.connect(self.install_update_thread.quit)
        self.install_update_worker.failed.connect(self.install_update_thread.quit)
        self.install_update_worker.cancelled.connect(self.install_update_thread.quit)
        self.install_update_thread.finished.connect(self._install_update_thread_finished)
        self.install_update_progress.canceled.connect(self.install_update_worker.cancel)
        self.install_update_thread.start()

    @Slot(str)
    def _on_installer_downloaded(self, path: str) -> None:
        if self.install_update_progress:
            self.install_update_progress.setLabelText("A iniciar o instalador; o MediaLivre será fechado…")
            self.install_update_progress.setCancelButton(None)
            self.install_update_progress.setValue(100)
        self._append_log(f"Instalador validado; a iniciar atualização: {path}")
        started = start_installer_process(path)
        if not started:
            if self.install_update_progress:
                self.install_update_progress.close()
            QMessageBox.warning(
                self,
                "Atualização não iniciada",
                "O instalador foi descarregado e validado, mas o Windows não conseguiu iniciá-lo automaticamente. "
                f"Pode executá-lo manualmente em:\n{path}",
            )
            return
        QTimer.singleShot(400, QApplication.instance().quit)

    @Slot(str)
    def _on_installer_download_failed(self, message: str) -> None:
        if self.install_update_progress:
            self.install_update_progress.close()
        QMessageBox.warning(
            self,
            "Atualização não concluída",
            f"Não foi possível descarregar ou validar o instalador.\n\n{message}",
        )

    @Slot()
    def _on_installer_download_cancelled(self) -> None:
        if self.install_update_progress:
            self.install_update_progress.close()

    @Slot()
    def _install_update_thread_finished(self) -> None:
        if self.install_update_worker:
            self.install_update_worker.deleteLater()
        if self.install_update_thread:
            self.install_update_thread.deleteLater()
        self.install_update_worker = None
        self.install_update_thread = None
        if self.install_update_progress:
            self.install_update_progress.deleteLater()
        self.install_update_progress = None
        self.update_button.setEnabled(True)
        self.update_button.setText("Atualizações")

    @Slot(str)
    def _update_check_failed(self, message: str) -> None:
        if self._manual_update_check:
            QMessageBox.warning(
                self,
                "Atualizações indisponíveis",
                f"Não foi possível consultar as Releases agora.\n\n{message}",
            )
        self.update_button.setText("Atualizações")
        self.update_button.setToolTip("Consultar Releases e escolher a versão para instalar.")

    @Slot()
    def _update_thread_finished(self) -> None:
        if self.update_worker:
            self.update_worker.deleteLater()
        if self.update_thread:
            self.update_thread.deleteLater()
        self.update_worker = None
        self.update_thread = None
        self._manual_update_check = False
        if not (self.install_update_thread and self.install_update_thread.isRunning()):
            self.update_button.setEnabled(True)

    def _schedule_current_download(self) -> None:
        url = self.url_input.text().strip()
        if not is_http_url(url):
            QMessageBox.warning(self, "Ligação inválida", "Introduza uma ligação HTTP(S) antes de agendar.")
            return
        run_at = datetime.fromtimestamp(
            self.schedule_time.dateTime().toSecsSinceEpoch(), timezone.utc
        )
        if run_at <= datetime.now(timezone.utc):
            QMessageBox.warning(self, "Horário inválido", "Escolha uma data/hora futura.")
            return
        options = {
            "quality": self.quality.currentText(),
            "container": self.video_format.currentText(),
            "audio_only": self.audio_only.isChecked(),
            "download_thumbnail": self.thumbnail_check.isChecked(),
            "allow_playlist": self.playlist_check.isChecked(),
            "destination": str(self.destination),
        }
        try:
            job = self.schedule_store.add(url, run_at, options)
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            QMessageBox.critical(self, "Não foi possível agendar", str(exc))
            return
        self._refresh_scheduled_jobs()
        self._append_log(f"Agendado para {job.run_at_local:%Y-%m-%d %H:%M} (hora local): {url}")
        QMessageBox.information(
            self,
            "Download agendado",
            "O trabalho foi guardado neste computador. O MediaLivre irá executá-lo quando chegar a hora, "
            "se estiver aberto; se for fechado, tentará iniciá-lo na próxima vez que abrir.",
        )

    def _refresh_scheduled_jobs(self) -> None:
        self.scheduled_list.clear()
        state_labels = {
            "pending": "PENDENTE",
            "running": "EM EXECUÇÃO",
            "completed": "CONCLUÍDO",
            "failed": "FALHOU",
            "cancelled": "CANCELADO",
        }
        for job in self.schedule_store.list_recent(40):
            when = job.run_at_local.strftime("%Y-%m-%d %H:%M")
            url = job.url if len(job.url) <= 58 else job.url[:55] + "…"
            item = QListWidgetItem(f"{when} · {state_labels.get(job.state, job.state)} · {url}")
            item.setData(Qt.ItemDataRole.UserRole, job.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, job.state)
            item.setToolTip(job.last_error or job.url)
            self.scheduled_list.addItem(item)
        has_jobs = self.scheduled_list.count() > 0
        self.schedule_empty_label.setVisible(not has_jobs)
        self.scheduled_list.setVisible(has_jobs)
        self._update_schedule_actions(self.scheduled_list.currentItem(), None)

    @Slot(object, object)
    def _update_schedule_actions(self, current, _previous) -> None:
        can_cancel = bool(
            current
            and current.data(Qt.ItemDataRole.UserRole + 1) == "pending"
        )
        self.cancel_schedule_button.setEnabled(can_cancel)

    @Slot()
    def _cancel_selected_schedule(self) -> None:
        item = self.scheduled_list.currentItem()
        if not item:
            return
        job_id = item.data(Qt.ItemDataRole.UserRole)
        if self.schedule_store.cancel(job_id):
            self._append_log("Agendamento pendente cancelado.")
            self._refresh_scheduled_jobs()

    def _run_due_schedules(self) -> None:
        if self._active_schedule_id or (self.thread and self.thread.isRunning()):
            return
        try:
            job = self.schedule_store.claim_next_due()
        except Exception as exc:
            self._append_log(f"Erro ao consultar a fila de agendamentos: {exc}")
            return
        if job is None:
            return
        self._refresh_scheduled_jobs()
        self._append_log(f"A iniciar agendamento {job.id}.")
        self.start_download(job)

    def _finish_active_schedule(self, state: str, error: str | None = None) -> None:
        if not self._active_schedule_id:
            return
        try:
            self.schedule_store.finish(self._active_schedule_id, state, error)
        except sqlite3.Error as exc:
            self._append_log(f"Não foi possível guardar o estado do agendamento: {exc}")
        self._active_schedule_id = None
        try:
            self._refresh_scheduled_jobs()
        except sqlite3.Error as exc:
            self._append_log(f"Não foi possível atualizar a lista de agendamentos: {exc}")

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow { background: #10151c; color: #e7edf5; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
            QWidget#pageContent { background: #10151c; color: #e7edf5; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
            QScrollArea#mainScrollArea { background: #10151c; border: 0; }
            QLabel#title { color: #f5f8fc; font-size: 29px; font-weight: 700; }
            QLabel#subtitle { color: #95a4b6; font-size: 14px; }
            QLabel#version { color: #91a7bd; font-size: 10px; font-weight: 700; letter-spacing: 1px; padding: 8px; }
            QFrame#card { background: #171d32; border: 1px solid #303d6c; border-radius: 12px; }
            QLabel#fieldLabel { color: #f1bd36; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
            QLineEdit, QComboBox, QDateTimeEdit { background: #0e1426; border: 1px solid #35436f; border-radius: 7px; padding: 8px 10px; color: #f1f5f9; selection-background-color: #eaa22f; min-height: 20px; }
            QLineEdit:focus, QComboBox:focus, QDateTimeEdit:focus { border: 1px solid #ffc61b; }
            QComboBox::drop-down { border: 0; width: 26px; }
            QDateTimeEdit::drop-down { border: 0; width: 28px; }
            QListWidget#scheduledList { background: #0b1016; border: 1px solid #293543; border-radius: 7px; padding: 4px; color: #b9c7d5; outline: 0; }
            QListWidget#scheduledList::item { padding: 7px 8px; border-radius: 4px; }
            QListWidget#scheduledList::item:hover { background: #172536; }
            QListWidget#scheduledList::item:selected { background: #293b7a; color: #ffffff; }
            QLabel#emptyState { color: #718397; padding: 9px; }
            QScrollBar:vertical { background: #10151c; width: 12px; margin: 0; }
            QScrollBar::handle:vertical { background: #344253; min-height: 28px; border-radius: 5px; }
            QScrollBar::handle:vertical:hover { background: #4b6075; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QPushButton { background: #202b55; border: 1px solid #3b4d88; border-radius: 7px; padding: 10px 14px; color: #eef4fa; font-weight: 600; }
            QPushButton:hover { background: #2d3c73; border-color: #ffc61b; }
            QPushButton:disabled { color: #69798a; background: #1a2034; }
            QPushButton#primary { background: #eaa22f; border: 1px solid #ffc61b; color: #151b38; }
            QPushButton#primary:hover { background: #ffc61b; }
            QCheckBox { color: #c2ceda; spacing: 8px; }
            QCheckBox::indicator { width: 17px; height: 17px; }
            QProgressBar { background: #1a2442; border: 0; border-radius: 4px; min-height: 9px; max-height: 9px; }
            QProgressBar::chunk { background: #ffc61b; border-radius: 4px; }
            QTextEdit { background: #0b1016; border: 1px solid #303d6c; border-radius: 8px; padding: 10px; color: #c4cede; font-family: Consolas, monospace; font-size: 11px; }
            QLabel#status { color: #aebdcb; }
            QLabel#percent { color: #ffc61b; font-weight: 700; }
            QLabel#itemLabel { color: #c2ceda; }
            QLabel#notice { color: #8697a8; font-size: 11px; }
        """)

    @Slot(bool)
    def _toggle_audio(self, enabled: bool) -> None:
        self.quality.setEnabled(not enabled)
        self.video_format.setEnabled(not enabled)
        self.thumbnail_check.setEnabled(enabled)
        if enabled:
            self.thumbnail_check.setChecked(True)
        else:
            self.thumbnail_check.setChecked(False)

    @Slot()
    def choose_destination(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Escolher pasta", str(self.destination))
        if selected:
            self.destination = Path(selected)
            self.destination_text.setText(selected)

    @Slot()
    def start_download(
        self,
        scheduled_job: ScheduledDownload | None = None,
        selected_items: list[dict] | None = None,
    ) -> None:
        if scheduled_job:
            options = scheduled_job.options
            self.url_input.setText(scheduled_job.url)
            self.quality.setCurrentText(str(options.get("quality", "Melhor disponível")))
            self.video_format.setCurrentText(str(options.get("container", "Automático")))
            self.audio_only.setChecked(bool(options.get("audio_only", False)))
            self.thumbnail_check.setChecked(bool(options.get("download_thumbnail", True)))
            self.playlist_check.setChecked(bool(options.get("allow_playlist", True)))
            self.destination = Path(options.get("destination") or self.destination)
            self.destination_text.setText(str(self.destination))
        self._active_schedule_id = scheduled_job.id if scheduled_job else None
        url = scheduled_job.url if scheduled_job else self.url_input.text().strip()
        if not is_http_url(url):
            if scheduled_job:
                self.schedule_store.finish(scheduled_job.id, "failed", "A URL guardada não é válida.")
                self._active_schedule_id = None
                self._refresh_scheduled_jobs()
                self._append_log("Agendamento ignorado: a URL guardada não é válida.")
            else:
                QMessageBox.warning(self, "Ligação inválida", "Introduza uma ligação completa http:// ou https://.")
                self.url_input.setFocus()
            return
        if self.thread and self.thread.isRunning():
            return
        if scheduled_job is None and selected_items is None:
            if self._prepared_items_url == url and self._prepared_items is not None:
                selected_items = self._prepared_items
                self._prepared_items_url = None
                self._prepared_items = None
            elif playlist_enabled(url, self.playlist_check.isChecked()):
                self._begin_collection_selection(url, start_after=True)
                return
        self.log.clear()
        self.progress.setValue(0)
        self.percent_label.setText("0%")
        self.item_progress_bar.setValue(0)
        self.item_percent.setText("0%")
        self.item_label.setText("A preparar o primeiro item…")
        self.status_label.setText("A iniciar…")
        self._set_busy(True)

        self.thread = QThread(self)
        self.worker = DownloadWorker(
            url=url,
            destination=self.destination,
            quality=self.quality.currentText(),
            audio_only=self.audio_only.isChecked(),
            allow_playlist=self.playlist_check.isChecked(),
            container=self.video_format.currentText(),
            download_thumbnail=self.thumbnail_check.isChecked(),
            selected_items=selected_items,
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.item_progress.connect(self._on_item_progress)
        self.worker.item_started.connect(self._on_item_started)
        self.worker.log_line.connect(self._append_log)
        self.worker.completed.connect(self._on_completed)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.completed.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.cancelled.connect(self.thread.quit)
        self.thread.finished.connect(self._thread_finished)
        self.cancel_button.setEnabled(True)
        self.skip_button.setEnabled(bool(is_collection_url(url) or (selected_items and len(selected_items) > 1)))
        self.thread.start()

    @Slot()
    def cancel_download(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.status_label.setText("A cancelar com segurança…")
            self.cancel_button.setEnabled(False)
            self.skip_button.setEnabled(False)
            self._append_log("Cancelamento solicitado; a transferência será interrompida no próximo ponto seguro.")

    @Slot()
    def skip_current_item(self) -> None:
        if self.worker:
            self.worker.skip_current_item()
            self.skip_button.setEnabled(False)
            self.status_label.setText("A saltar o item atual…")
            self._append_log("Salto solicitado; o item atual será ignorado no próximo ponto seguro.")

    @Slot(int, str)
    def _on_progress(self, percent: int, detail: str) -> None:
        self.progress.setValue(percent)
        self.percent_label.setText(f"{percent}%")
        self.status_label.setText(detail or "A transferir…")

    @Slot(int, str)
    def _on_item_progress(self, percent: int, item_label: str) -> None:
        self.item_progress_bar.setValue(percent)
        self.item_percent.setText(f"{percent}%")
        self.item_label.setText(item_label)

    @Slot(str)
    def _on_item_started(self, _title: str) -> None:
        if self.worker and self.worker.total_items > 1 and self.cancel_button.isEnabled():
            self.skip_button.setEnabled(True)

    @Slot(str)
    def _append_log(self, text: str) -> None:
        if text:
            self.log.append(text)

    @Slot(str)
    def _on_completed(self, folder: str) -> None:
        self.progress.setValue(100)
        self.percent_label.setText("100%")
        self.status_label.setText("Transferência concluída")
        self._append_log(f"Concluído. Pasta: {folder}")
        self._finish_active_schedule("completed")
        self._set_busy(False)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.status_label.setText("A transferência não foi concluída")
        self._append_log(message)
        self._finish_active_schedule("failed", message)
        self._set_busy(False)

    @Slot()
    def _on_cancelled(self) -> None:
        self.status_label.setText("Transferência cancelada")
        self._append_log("A transferência foi cancelada.")
        self._finish_active_schedule("cancelled")
        self._set_busy(False)

    @Slot()
    def _thread_finished(self) -> None:
        if self.worker:
            self.worker.deleteLater()
        if self.thread:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None
        if self._close_when_idle:
            self._close_when_idle = False
            self.close()

    def _set_busy(self, busy: bool) -> None:
        self.start_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy and self.worker is not None)
        self.skip_button.setEnabled(busy and self.worker is not None)
        self.browse_button.setEnabled(not busy)
        self.choose_items_button.setEnabled(not busy)
        self.url_input.setEnabled(not busy)
        self.quality.setEnabled(not busy and not self.audio_only.isChecked())
        self.video_format.setEnabled(not busy and not self.audio_only.isChecked())
        self.audio_only.setEnabled(not busy)
        self.thumbnail_check.setEnabled(not busy and self.audio_only.isChecked())
        self.playlist_check.setEnabled(not busy)

    @Slot()
    def open_destination(self) -> None:
        self.destination.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.destination)))

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.thread and self.thread.isRunning():
            answer = QMessageBox.question(
                self,
                "Transferência em curso",
                "Há uma transferência ativa. Pretende cancelá-la e fechar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._close_when_idle = True
                if self.worker:
                    self.worker.cancel()
                self.status_label.setText("A cancelar antes de fechar…")
                event.ignore()
            else:
                event.ignore()
            return
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    icon_path = resource_path("assets", "medialivre.ico")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    database_path = default_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    instance_lock = QLockFile(str(database_path.parent / "medialivre-instance.lock"))
    instance_lock.setStaleLockTime(30_000)
    if not instance_lock.tryLock(0):
        QMessageBox.information(
            None,
            "MediaLivre já está aberto",
            "Já existe uma instância do MediaLivre em execução. Use essa janela para gerir os downloads agendados.",
        )
        return 0
    window = MainWindow()
    if icon_path.is_file():
        window.setWindowIcon(QIcon(str(icon_path)))
    window._instance_lock = instance_lock
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
