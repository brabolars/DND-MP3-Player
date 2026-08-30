# src/dndmusic/gui/bridge.py
"""Thread bridge between the engine (bot thread) and the UI (Qt thread).

The engine reports through plain callables.  Assigning Qt signal ``emit``
methods to those callables turns every cross-thread notification into a queued
signal, which is the only safe way to touch widgets from the bot's event loop.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class EngineBridge(QObject):
    track_changed = pyqtSignal(object)
    playing_changed = pyqtSignal(bool)
    status_changed = pyqtSignal(str)
    error_raised = pyqtSignal(str)
    layers_changed = pyqtSignal()

    def attach(self, engine) -> None:
        engine.on_track_change = self.track_changed.emit
        engine.on_playing_change = self.playing_changed.emit
        engine.on_error = self.error_raised.emit
        engine.on_layers_changed = self.layers_changed.emit
