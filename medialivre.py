from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
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
    QPushButton,
    QCheckBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

APP_NAME = "MediaLivre"
APP_VERSION = "0.2.0"


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


def quality_format(quality: str, audio_only: bool, container: str = "Automático") -> str:
    if audio_only:
        return "bestaudio/best"
    max_height = {"1080p": 1080, "720p": 720, "480p": 480}.get(quality)
    height = f"[height<={max_height}]" if max_height else ""
    if container == "MP4":
        return f"bestvideo[ext=mp4]{height}+bestaudio[ext=m4a]/best[ext=mp4]{height}"
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


class DownloadWorker(QObject):
    progress = Signal(int, str)
    log_line = Signal(str)
    completed = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, url: str, destination: Path, quality: str,
                 audio_only: bool, allow_playlist: bool, container: str = "Automático") -> None:
        super().__init__()
        self.url = url
        self.destination = destination
        self.quality = quality
        self.audio_only = audio_only
        self.allow_playlist = allow_playlist
        self.container = container
        self.cancel_requested = threading.Event()
        self.last_percent = -1

    def cancel(self) -> None:
        self.cancel_requested.set()

    def _progress_hook(self, data: dict) -> None:
        if self.cancel_requested.is_set():
            raise DownloadError("Transferência cancelada pelo utilizador.")
        status = data.get("status")
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            current = data.get("downloaded_bytes") or 0
            percent = int(current * 100 / total) if total else 0
            percent = max(0, min(100, percent))
            if percent != self.last_percent:
                self.last_percent = percent
                speed = data.get("_speed_str", "")
                eta = data.get("_eta_str", "")
                detail = " · ".join(x for x in (speed, f"restam {eta}" if eta else "") if x)
                self.progress.emit(percent, detail)
        elif status == "finished":
            self.progress.emit(100, "A preparar o ficheiro…")

    @Slot()
    def run(self) -> None:
        try:
            self.destination.mkdir(parents=True, exist_ok=True)
            options: dict = {
                "format": quality_format(self.quality, self.audio_only, self.container),
                "outtmpl": str(self.destination / "%(title).180B [%(id)s].%(ext)s"),
                "noplaylist": not self.allow_playlist,
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
            if self.audio_only:
                options["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
            else:
                options.update(container_options(self.container))
            self.log_line.emit("A obter informações da fonte…")
            with YoutubeDL(options) as ydl:
                ydl.download([self.url])
            if self.cancel_requested.is_set():
                self.cancelled.emit()
            else:
                self.progress.emit(100, "Concluído")
                self.completed.emit(str(self.destination))
        except Exception as exc:
            if self.cancel_requested.is_set():
                self.cancelled.emit()
            else:
                message = str(exc).strip() or exc.__class__.__name__
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
        self.setMinimumSize(760, 640)
        self.resize(900, 720)
        self.thread: QThread | None = None
        self.worker: DownloadWorker | None = None
        self._close_when_idle = False
        self.destination = Path.home() / "Downloads"
        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(30, 26, 30, 22)
        layout.setSpacing(16)

        header = QHBoxLayout()
        brand = QVBoxLayout()
        title = QLabel("MediaLivre")
        title.setObjectName("title")
        subtitle = QLabel("Transferências simples. Código aberto.")
        subtitle.setObjectName("subtitle")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand)
        header.addStretch()
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
        self.url_input.returnPressed.connect(self.start_download)
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
        card_layout.addLayout(controls)
        card_layout.addWidget(self.audio_only)

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

        self.playlist_check = QCheckBox("Permitir listas de reprodução (pode transferir muitos itens)")
        self.playlist_check.setChecked(False)
        card_layout.addWidget(self.playlist_check)
        layout.addWidget(card)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("Iniciar transferência")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start_download)
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_download)
        self.open_button = QPushButton("Abrir pasta")
        self.open_button.clicked.connect(self.open_destination)
        action_row.addWidget(self.start_button, 1)
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

        log_label = QLabel("ATIVIDADE")
        log_label.setObjectName("fieldLabel")
        layout.addWidget(log_label)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("O progresso e as mensagens da transferência aparecem aqui.")
        self.log.document().setMaximumBlockCount(250)
        layout.addWidget(self.log, 1)

        notice = QLabel(
            "Use apenas com conteúdos que tem direito ou autorização para transferir. "
            "O MediaLivre não contorna DRM, autenticação ou controlos de acesso."
        )
        notice.setObjectName("notice")
        notice.setWordWrap(True)
        layout.addWidget(notice)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #10151c; color: #e7edf5; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
            QLabel#title { color: #f5f8fc; font-size: 29px; font-weight: 700; }
            QLabel#subtitle { color: #95a4b6; font-size: 14px; }
            QLabel#version { color: #91a7bd; font-size: 10px; font-weight: 700; letter-spacing: 1px; padding: 8px; }
            QFrame#card { background: #171f29; border: 1px solid #293543; border-radius: 12px; }
            QLabel#fieldLabel { color: #93a7bb; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
            QLineEdit, QComboBox { background: #0e141b; border: 1px solid #344253; border-radius: 7px; padding: 10px 11px; color: #f1f5f9; selection-background-color: #2384df; }
            QLineEdit:focus, QComboBox:focus { border: 1px solid #3b9aff; }
            QComboBox::drop-down { border: 0; width: 26px; }
            QPushButton { background: #222d39; border: 1px solid #354455; border-radius: 7px; padding: 10px 14px; color: #eef4fa; font-weight: 600; }
            QPushButton:hover { background: #2c3b4b; }
            QPushButton:disabled { color: #69798a; background: #1a222c; }
            QPushButton#primary { background: #1878d1; border: 1px solid #2589e5; color: white; }
            QPushButton#primary:hover { background: #278be5; }
            QCheckBox { color: #c2ceda; spacing: 8px; }
            QCheckBox::indicator { width: 17px; height: 17px; }
            QProgressBar { background: #1c2732; border: 0; border-radius: 4px; min-height: 9px; max-height: 9px; }
            QProgressBar::chunk { background: #29a0ff; border-radius: 4px; }
            QTextEdit { background: #0b1016; border: 1px solid #293543; border-radius: 8px; padding: 10px; color: #aebdcb; font-family: Consolas, monospace; font-size: 11px; }
            QLabel#status { color: #aebdcb; }
            QLabel#percent { color: #70bdff; font-weight: 700; }
            QLabel#notice { color: #8697a8; font-size: 11px; }
        """)

    @Slot(bool)
    def _toggle_audio(self, enabled: bool) -> None:
        self.quality.setEnabled(not enabled)
        self.video_format.setEnabled(not enabled)

    @Slot()
    def choose_destination(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Escolher pasta", str(self.destination))
        if selected:
            self.destination = Path(selected)
            self.destination_text.setText(selected)

    @Slot()
    def start_download(self) -> None:
        url = self.url_input.text().strip()
        if not is_http_url(url):
            QMessageBox.warning(self, "Ligação inválida", "Introduza uma ligação completa http:// ou https://.")
            self.url_input.setFocus()
            return
        if self.thread and self.thread.isRunning():
            return
        self.log.clear()
        self.progress.setValue(0)
        self.percent_label.setText("0%")
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
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.log_line.connect(self._append_log)
        self.worker.completed.connect(self._on_completed)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.completed.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.cancelled.connect(self.thread.quit)
        self.thread.finished.connect(self._thread_finished)
        self.thread.start()

    @Slot()
    def cancel_download(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.status_label.setText("A cancelar com segurança…")
            self.cancel_button.setEnabled(False)
            self._append_log("Cancelamento solicitado; a transferência será interrompida no próximo ponto seguro.")

    @Slot(int, str)
    def _on_progress(self, percent: int, detail: str) -> None:
        self.progress.setValue(percent)
        self.percent_label.setText(f"{percent}%")
        self.status_label.setText(detail or "A transferir…")

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
        self._set_busy(False)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.status_label.setText("A transferência não foi concluída")
        self._append_log(message)
        self._set_busy(False)

    @Slot()
    def _on_cancelled(self) -> None:
        self.status_label.setText("Transferência cancelada")
        self._append_log("A transferência foi cancelada.")
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
        self.cancel_button.setEnabled(busy)
        self.browse_button.setEnabled(not busy)
        self.url_input.setEnabled(not busy)
        self.quality.setEnabled(not busy and not self.audio_only.isChecked())
        self.video_format.setEnabled(not busy and not self.audio_only.isChecked())
        self.audio_only.setEnabled(not busy)
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
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
