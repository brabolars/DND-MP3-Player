# src/dndmusic/audio/stream.py
"""Decoded audio streams.

An FFmpeg process per source, decoded to raw PCM on a reader thread and handed
to the mixer one frame at a time.  The thread plus bounded queue matter: the
mixer's ``read()`` is called every 20 ms by disnake's audio thread and must
never block on a pipe, or playback stutters.
"""

from __future__ import annotations

import queue
import subprocess
import threading
from typing import Callable, Optional, Protocol, Sequence

from .ffmpeg import executable as ffmpeg_executable
from .process import hidden_process_kwargs
from .pcm import FFMPEG_OUTPUT_ARGS, FRAME_BYTES, SILENCE, pad_frame

DEFAULT_PREBUFFER_FRAMES = 25   # 0.5 s
DEFAULT_QUEUE_FRAMES = 150      # 3 s

#: Input options for streams that come over the network rather than off disk.
NETWORK_INPUT_OPTIONS = (
    "-reconnect", "1",
    "-reconnect_streamed", "1",
    "-reconnect_delay_max", "5",
)


class FrameStream(Protocol):
    """Anything the mixer can pull frames from."""

    def read_frame(self) -> Optional[bytes]:
        """Return one frame, or None when the stream is exhausted."""

    def stop(self) -> None:
        """Release resources."""


class FFmpegPcmStream:
    """Decodes anything FFmpeg understands into 20 ms PCM frames.

    ``path`` may be a local file or a URL — pass
    ``input_options=NETWORK_INPUT_OPTIONS`` for the latter so a dropped
    connection reconnects instead of ending the stream.
    """

    def __init__(
        self,
        path: str,
        *,
        loop: bool = False,
        start_at: float = 0.0,
        executable: Optional[str] = None,
        queue_frames: int = DEFAULT_QUEUE_FRAMES,
        input_options: Sequence[str] = (),
    ) -> None:
        self.path = path
        self.loop = loop
        self._queue: queue.Queue = queue.Queue(maxsize=queue_frames)
        self._stopping = threading.Event()
        self._eof = threading.Event()
        self._ready = threading.Event()
        self.underruns = 0
        self.frames_read = 0

        command = [executable or ffmpeg_executable(), "-hide_banner", "-loglevel", "error"]
        command += list(input_options)
        if loop:
            command += ["-stream_loop", "-1"]
        if start_at > 0:
            command += ["-ss", f"{start_at:.3f}"]
        command += ["-i", path, *FFMPEG_OUTPUT_ARGS, "pipe:1"]
        self.command = command

        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            bufsize=FRAME_BYTES * 8,
            **hidden_process_kwargs(),
        )
        self._thread = threading.Thread(
            target=self._pump, name=f"pcm-{id(self):x}", daemon=True
        )
        self._thread.start()

    # ── reader thread ────────────────────────────────────────────────────

    def _pump(self) -> None:
        stdout = self._process.stdout
        try:
            while not self._stopping.is_set():
                chunk = stdout.read(FRAME_BYTES)
                if not chunk:
                    break
                if len(chunk) < FRAME_BYTES:
                    chunk = pad_frame(chunk)
                while not self._stopping.is_set():
                    try:
                        self._queue.put(chunk, timeout=0.2)
                        break
                    except queue.Full:
                        continue
                if not self._ready.is_set() and self._queue.qsize() >= 2:
                    self._ready.set()
        except (OSError, ValueError):
            pass
        finally:
            self._eof.set()
            self._ready.set()

    # ── mixer interface ──────────────────────────────────────────────────

    def read_frame(self) -> Optional[bytes]:
        try:
            frame = self._queue.get_nowait()
            self.frames_read += 1
            return frame
        except queue.Empty:
            if self._eof.is_set():
                return None
            # Decoder hasn't kept up; emit silence rather than stalling the mix.
            self.underruns += 1
            return SILENCE

    def wait_until_ready(self, timeout: float = 1.0, frames: int = DEFAULT_PREBUFFER_FRAMES) -> bool:
        """Block briefly so playback starts with a full buffer.

        Safe to call from a worker thread; never called from the audio thread.
        """
        self._ready.wait(timeout)
        deadline = threading.Event()
        waited = 0.0
        while self._queue.qsize() < frames and not self._eof.is_set() and waited < timeout:
            deadline.wait(0.02)
            waited += 0.02
        return self._queue.qsize() > 0 or self._eof.is_set()

    @property
    def finished(self) -> bool:
        return self._eof.is_set() and self._queue.empty()

    @property
    def decoder_finished(self) -> bool:
        """FFmpeg has read the whole file, though frames may still be queued.

        This fires seconds before playback catches up, which is what lets
        :class:`LoopingStream` prepare the next pass without a gap.
        """
        return self._eof.is_set()

    @property
    def buffered_frames(self) -> int:
        return self._queue.qsize()

    def stop(self) -> None:
        self._stopping.set()
        if self._process.poll() is None:
            try:
                self._process.kill()
                # Reap it: without a wait() the child lingers as a zombie, and
                # this app spawns one FFmpeg per track and per SFX.
                self._process.wait(timeout=2)
            except Exception:
                pass
        try:
            if self._process.stdout:
                self._process.stdout.close()
        except Exception:
            pass
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._eof.set()


class LoopingStream:
    """Repeats a stream, with the loop flag mutable *while playing*.

    FFmpeg's own ``-stream_loop`` is decided when the process spawns, so a track
    started as a loop could never stop looping without a restart.  Here the
    repeat happens one level up: when the inner stream ends, a fresh one takes
    over.  The handover is gapless because the next pass is spawned as soon as
    the decoder reports EOF — typically seconds before playback needs it, since
    frames are still draining out of the queue.
    """

    def __init__(self, factory: Callable[[], "FrameStream"], loop: bool = True) -> None:
        self._factory = factory
        self.loop = loop
        self.passes = 1
        self._current = factory()
        self._next: Optional["FrameStream"] = None
        self._stopped = False
        self._frames_this_pass = 0

    # ── delegation so the mixer and engine can still introspect ──────────

    @property
    def current(self):
        return self._current

    @property
    def buffered_frames(self) -> int:
        return getattr(self._current, "buffered_frames", 0)

    @property
    def frames_read(self) -> int:
        return getattr(self._current, "frames_read", 0)

    def wait_until_ready(self, timeout: float = 1.0, frames: int = DEFAULT_PREBUFFER_FRAMES) -> bool:
        waiter = getattr(self._current, "wait_until_ready", None)
        return waiter(timeout, frames) if waiter else True

    # ── frame source ─────────────────────────────────────────────────────

    def read_frame(self) -> Optional[bytes]:
        if self._stopped:
            return None

        frame = self._current.read_frame()
        if frame is not None:
            self._frames_this_pass += 1
            # Decoder done but frames still queued: build the next pass now.
            if self.loop and self._next is None and getattr(self._current, "decoder_finished", False):
                try:
                    self._next = self._factory()
                except Exception:
                    self._next = None
            return frame

        if not self.loop:
            return None

        if self._frames_this_pass == 0:
            # The last pass produced nothing — the file is gone or unreadable.
            # Looping again would spin forever, so end the voice instead.
            return None

        self._current.stop()
        upcoming, self._next = self._next, None
        try:
            self._current = upcoming or self._factory()
        except Exception:
            return None
        self.passes += 1
        self._frames_this_pass = 0
        return self._current.read_frame() or SILENCE

    def stop(self) -> None:
        self._stopped = True
        for stream in (self._current, self._next):
            if stream is not None:
                stream.stop()
        self._next = None


class SilenceStream:
    """Endless silence — used as a keep-alive so the voice source never ends."""

    def read_frame(self) -> Optional[bytes]:
        return SILENCE

    def stop(self) -> None:
        return None
