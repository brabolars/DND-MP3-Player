# src/dndmusic/gui/local_output.py
"""Local speaker output — the "MP3 player" mode.

The same :class:`MixingSource` that feeds Discord can feed this machine's sound
card instead, so every feature (layers, faders, normalisation, crossfades) works
identically whether or not a bot is involved.

Built on QtMultimedia, which ships with PyQt6, so there is no extra dependency
and no PortAudio to install.  QAudioSink runs in *pull* mode: it asks a QIODevice
for bytes on its own schedule, and we answer with mixer frames.  That keeps the
timing in Qt's hands rather than ours.

This lives in ``gui/`` deliberately: it is the only audio path that needs Qt, and
the engine talks to it through a duck-typed ``start()``/``stop()`` so nothing in
``engine/`` or ``audio/`` imports Qt.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QIODevice, QIODeviceBase, QObject, pyqtSignal, pyqtSlot
from PyQt6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

from ..audio.pcm import CHANNELS, FRAME_BYTES, SAMPLE_RATE, SILENCE
from ..core.debug import DebugLogger

#: How much audio the sink is allowed to buffer.  Bigger is safer against
#: stutter, smaller makes a fader move feel more immediate.
BUFFER_FRAMES = 8

#: Sentinel for "whatever Windows/the OS currently considers default".
SYSTEM_DEFAULT = ""
SYSTEM_DEFAULT_LABEL = "System default"


class MixerDevice(QIODevice):
    """Adapts the mixer's frame-at-a-time interface to Qt's byte stream."""

    def __init__(self, source, parent=None) -> None:
        super().__init__(parent)
        self.source = source
        self._tail = b""
        self.frames_served = 0

    def readData(self, maxlen: int) -> bytes:  # noqa: N802 - Qt naming
        if maxlen <= 0:
            return b""
        chunks = []
        size = 0

        if self._tail:
            chunks.append(self._tail)
            size += len(self._tail)
            self._tail = b""

        while size < maxlen:
            frame = self.source.read() if self.source is not None else SILENCE
            if not frame:
                # The mixer has been torn down; pad so Qt doesn't treat this as
                # end-of-stream and stop the sink underneath us.
                frame = SILENCE
            self.frames_served += 1
            chunks.append(frame)
            size += len(frame)

        data = b"".join(chunks)
        if size > maxlen:
            data, self._tail = data[:maxlen], data[maxlen:]
        return data

    def writeData(self, _data) -> int:  # noqa: N802 - Qt naming
        return 0

    def bytesAvailable(self) -> int:  # noqa: N802 - Qt naming
        return FRAME_BYTES * BUFFER_FRAMES + super().bytesAvailable()

    def isSequential(self) -> bool:  # noqa: N802 - Qt naming
        return True


class LocalAudioSink(QObject):
    """Plays a MixingSource through the default output device.

    ``start()`` and ``stop()`` are called from the engine's event-loop thread,
    but QAudioSink must be created and driven on the thread that owns a Qt event
    loop — the GUI thread.  So the public methods only emit signals; the real
    work happens in the slots, which Qt delivers on this object's own thread.
    Getting this wrong produces silence with no error, which is exactly what it
    did before.
    """

    started = pyqtSignal(str)
    failed = pyqtSignal(str)
    _start_requested = pyqtSignal(object)
    _stop_requested = pyqtSignal()
    _device_requested = pyqtSignal(str)

    def __init__(self, debug: Optional[DebugLogger] = None, parent=None) -> None:
        super().__init__(parent)
        self.debug = debug
        self._sink: Optional[QAudioSink] = None
        self._device: Optional[MixerDevice] = None
        self._source = None
        #: Empty means "follow the system default".
        self.preferred_device = SYSTEM_DEFAULT
        self._start_requested.connect(self._do_start)
        self._stop_requested.connect(self._do_stop)
        self._device_requested.connect(self._do_set_device)

    @staticmethod
    def audio_format() -> QAudioFormat:
        fmt = QAudioFormat()
        fmt.setSampleRate(SAMPLE_RATE)
        fmt.setChannelCount(CHANNELS)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        return fmt

    # ── device selection ─────────────────────────────────────────────────

    @staticmethod
    def default_device_name() -> str:
        device = QMediaDevices.defaultAudioOutput()
        return device.description() if device is not None else ""

    @staticmethod
    def device_names() -> list:
        """Output devices the OS is offering right now."""
        return [d.description() for d in QMediaDevices.audioOutputs() if not d.isNull()]

    def set_device(self, name: str) -> None:
        """Choose an output.  Safe from any thread; applies live if playing."""
        self._device_requested.emit(name or SYSTEM_DEFAULT)

    @pyqtSlot(str)
    def _do_set_device(self, name: str) -> None:
        if name == self.preferred_device:
            return
        self.preferred_device = name
        self._log(f"Output device: {name or SYSTEM_DEFAULT_LABEL}", "MIX")
        # Reopen on the new device without losing the mixer, so switching
        # mid-track keeps playing rather than stopping.
        if self._sink is not None and self._source is not None:
            self._do_start(self._source)

    def _resolve_device(self):
        """The preferred device if it still exists, else the system default."""
        if self.preferred_device:
            for device in QMediaDevices.audioOutputs():
                if device.description() == self.preferred_device:
                    return device
            self._log(
                f"'{self.preferred_device}' is not available; using the default", "MIX"
            )
        return QMediaDevices.defaultAudioOutput()

    @property
    def is_running(self) -> bool:
        return self._sink is not None

    @property
    def frames_served(self) -> int:
        return self._device.frames_served if self._device else 0

    # ── thread-safe API ──────────────────────────────────────────────────

    def start(self, source) -> None:
        """Safe from any thread; the sink is built on the GUI thread."""
        self._start_requested.emit(source)

    def stop(self) -> None:
        self._stop_requested.emit()

    # ── the actual work, always on this object's thread ──────────────────

    @pyqtSlot(object)
    def _do_start(self, source) -> None:
        try:
            self._open(source)
        except Exception as exc:
            self._do_stop()
            self._log(f"Local output failed: {exc}", "ERR")
            self.failed.emit(str(exc))

    def _open(self, source) -> None:
        self._do_stop()
        self._source = source

        device = self._resolve_device()
        if device is None or device.isNull():
            raise RuntimeError("No audio output device available")

        fmt = self.audio_format()
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
            self._log(f"48k/16-bit stereo unsupported; using {fmt.sampleRate()}Hz", "MIX")

        self._sink = QAudioSink(device, fmt, self)
        self._sink.setBufferSize(FRAME_BYTES * BUFFER_FRAMES)
        self._device = MixerDevice(source, self)
        if not self._device.open(QIODeviceBase.OpenModeFlag.ReadOnly):
            raise RuntimeError("Could not open the mixer device for reading")
        self._sink.start(self._device)
        if self._sink.error() not in (
            QAudio.Error.NoError,
            QAudio.Error.UnderrunError,
        ):
            raise RuntimeError(f"QAudioSink error: {self._sink.error().name}")
        self._log(f"Local output started on {device.description()}", "MIX")
        self.started.emit(device.description())

    @pyqtSlot()
    def _do_stop(self) -> None:
        if self._sink is not None:
            try:
                self._sink.stop()
            except Exception:
                pass
        if self._device is not None:
            try:
                self._device.source = None
                self._device.close()
            except Exception:
                pass
        self._sink = None
        self._device = None

    def _log(self, message: str, category: str = "MIX") -> None:
        if self.debug:
            self.debug.log(message, category)
