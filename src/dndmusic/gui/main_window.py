# src/dndmusic/gui/main_window.py
"""The main window.

This is the *composition layer*: it owns no domain logic of its own.  Widgets
emit intents, this class translates them into calls on the library, the
playlist and the engine, then pushes the resulting state back into the widgets.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QByteArray, QFileSystemWatcher, Qt, QTimer
from PyQt6.QtMultimedia import QMediaDevices
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QWidget,
)

from ..bot.auth import resolve_token
from ..bot.client import BotContext, BotRunner
from ..config import APP_NAME, APP_VERSION, paths
from ..audio.ffmpeg import ffmpeg_status
from ..audio.opus import ensure_opus
from ..audio.opus import looks_like_opus as opus_looks_right
from ..audio.ffmpeg import looks_like_ffmpeg as ffmpeg_looks_right
from ..audio.ffmpeg import set_executable as set_ffmpeg_executable
from ..core.importer import import_folder, import_legacy_library
from ..core.library import LibraryError
from ..core.models import MediaKind, MusicTrack, OutputMode, PlaybackMode
from ..core.playlist import load_playlist, save_playlist
from ..discord_api import DISCORD_AVAILABLE, INSTALL_HINT
from ..services import Services, missing_requirements
from .bridge import EngineBridge
from .dialogs.prompts import ask_text, choose_category, confirm, inform, pick_audio_files, warn
from .dialogs.token_setup import show_token_setup_dialog
from .local_output import SYSTEM_DEFAULT_LABEL, LocalAudioSink
from .ui_state import UiState
from .theme.editor import ThemeEditorDialog
from .theme.manager import ThemeManager
from .widgets.control_panel import ControlPanel
from .widgets.layer_mixer import LayerMixerPanel
from .widgets.library_panel import LibraryPanel
from .widgets.playlist_panel import PlaylistPanel
from .widgets.top_bar import TopBar
from .widgets.visualizer import VisualizerWidget

BOT_START_DELAY_MS = 800

#: Bump when the set of docks changes, so an old saved layout is discarded
#: rather than restored into a window that no longer matches it.
LAYOUT_VERSION = 2


class MainWindow(QMainWindow):
    def __init__(self, services: Services) -> None:
        super().__init__()
        self.services = services
        self.debug = services.debug
        self.library = services.library
        self.playlist = services.playlist
        self.engine = services.engine
        self.categories = services.categories

        self.themes = ThemeManager()
        self.themes.load()
        self.ui_state = UiState.load()
        remembered = self.themes.resolve(self.ui_state.theme) if self.ui_state.theme else None
        if remembered is not None:
            self.themes.current = remembered

        self.bridge = EngineBridge()
        self.bridge.attach(self.engine)
        # Qt lives here, not in the engine: the sink is duck-typed.
        self.engine.local_sink = LocalAudioSink(self.debug, self)
        self.engine.local_sink.failed.connect(self._on_output_failed)
        self.engine.local_sink.started.connect(
            lambda name: self.controls.set_status(f"Playing locally — {name}")
        )
        self.bot_runner: Optional[BotRunner] = None

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setGeometry(80, 80, 1440, 880)

        self._build_ui()
        self._connect_signals()
        self._sync_controls_to_settings()
        self._apply_theme(self.themes.current)
        self.refresh_all()

        self._restore_layout()
        self._install_audio_device_watcher()
        self._install_disk_watcher()
        self._install_mixer_poll()
        self._install_settings_saver()

        self._report_missing_requirements()

        if services.discord_enabled:
            QTimer.singleShot(BOT_START_DELAY_MS, self.start_bot)
        else:
            self.controls.set_status("UI-only mode (--ui-only)")
            self.debug.log("Discord disabled via --ui-only", "SYS")

    # ═════════════════════════════════════════════════════════════════════
    #  Construction
    # ═════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        """Toolbar on top, everything else a dock.

        The central widget is deliberately zero-height: a QMainWindow gives all
        leftover space to its centre, so putting the header there squeezed the
        docks to the edges.  With nothing in the centre, the docks fill the
        window and behave like resizable columns.
        """
        current = self.themes.current

        self.top_bar = TopBar(self.themes.entries(), self.themes.label_for(current))
        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("toolbar_main")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.addWidget(self.top_bar)

        # Zero width so it takes no room, but vertically expanding: QMainWindow
        # has to give leftover vertical space to *something*, and if the centre
        # can't take it the top dock area does — which left a dead band under the
        # visualiser and squashed the panels below.
        placeholder = QWidget()
        placeholder.setMaximumWidth(0)
        placeholder.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setCentralWidget(placeholder)

        self.visualizer = VisualizerWidget()
        self.visualizer.set_colors(current.primary, current.accent)
        self.library_panel = LibraryPanel()
        self.playlist_panel = PlaylistPanel()
        self.layer_mixer = LayerMixerPanel()
        self.controls = ControlPanel()

        self.docks = {}
        visual_dock = self._add_dock("visualizer", "Visualiser", self.visualizer,
                                     Qt.DockWidgetArea.TopDockWidgetArea)
        visual_dock.setMaximumHeight(180)
        library_dock = self._add_dock("library", "Library", self.library_panel,
                                      Qt.DockWidgetArea.LeftDockWidgetArea)
        playlist_dock = self._add_dock("playlist", "Playlist", self.playlist_panel,
                                       Qt.DockWidgetArea.LeftDockWidgetArea)
        layers_dock = self._add_dock("layers", "Playing now", self.layer_mixer,
                                     Qt.DockWidgetArea.LeftDockWidgetArea)
        controls_dock = self._add_dock("controls", "Controls", self.controls,
                                       Qt.DockWidgetArea.RightDockWidgetArea)

        # Library | (Playlist over Playing now) | Controls — close to the old
        # three-column arrangement, but each part detachable.
        self.splitDockWidget(library_dock, playlist_dock, Qt.Orientation.Horizontal)
        self.splitDockWidget(playlist_dock, layers_dock, Qt.Orientation.Vertical)

        self.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
        )
        self.resizeDocks(
            [library_dock, playlist_dock, controls_dock], [520, 420, 380],
            Qt.Orientation.Horizontal,
        )
        self.resizeDocks([visual_dock], [130], Qt.Orientation.Vertical)

        self._default_dock_state = None
        self._build_menus()

    def _add_dock(self, key: str, title: str, widget: QWidget, area) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(f"dock_{key}")     # required for saveState()
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        # Deliberately NOT closable: a closed dock has no visible affordance to
        # bring it back, so panels could be lost for good.  Hiding is still
        # possible from the View menu, which can also restore them.
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(area, dock)
        self.docks[key] = dock
        return dock

    def _build_menus(self) -> None:
        view = self.menuBar().addMenu("&View")
        for dock in self.docks.values():
            view.addAction(dock.toggleViewAction())
        view.addSeparator()
        view.addAction("Show all panels", self._show_all_docks)
        view.addAction("Pop all panels out", self._float_all_docks)
        view.addAction("Tab panels together", self._tabify_docks)
        view.addAction("Reset layout", self._reset_layout)

        library = self.menuBar().addMenu("&Library")
        library.addAction("Import folder…", self._on_import_folder)
        library.addAction("Import an old music_data.json…", self._on_import_legacy)
        library.addSeparator()
        library.addAction("Rescan folders", lambda: self.rescan_library(quiet=False))
        library.addAction("Analyse loudness", self._on_analyse_library)

    def _show_all_docks(self) -> None:
        for dock in self.docks.values():
            dock.show()
            dock.setFloating(False)

    def _float_all_docks(self) -> None:
        for index, dock in enumerate(self.docks.values()):
            dock.show()
            dock.setFloating(True)
            dock.move(self.x() + 60 + index * 40, self.y() + 60 + index * 40)

    def _tabify_docks(self) -> None:
        docks = [d for key, d in self.docks.items() if key != "visualizer"]
        for dock in docks:
            dock.show()
            dock.setFloating(False)
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        for previous, dock in zip(docks, docks[1:]):
            self.tabifyDockWidget(previous, dock)
        docks[0].raise_()

    def _reset_layout(self) -> None:
        """Back to the shipped arrangement, with every panel visible.

        Also writes the reset state out, so a crash before the next clean exit
        can't resurrect the layout you just escaped from.
        """
        self._show_all_docks()
        if self._default_dock_state is not None:
            self.restoreState(self._default_dock_state)
        for dock in self.docks.values():
            dock.show()
        self.resize(1600, 900)
        self._save_ui_state()
        self.controls.set_status("Layout reset")
        self.debug.log("Layout reset to the default", "SYS")

    def _sync_controls_to_settings(self) -> None:
        """Push engine defaults into the widgets so nothing lies at startup."""
        settings = self.engine.settings
        self.controls.set_volumes(
            int(settings.music_volume * 100), int(settings.master_volume * 100)
        )
        self.controls.set_fade(settings.fade_enabled, settings.fade_seconds)
        self.controls.set_loop(settings.loop_music)
        self.controls.set_output_mode(settings.output)
        self.controls.set_output_devices(
            LocalAudioSink.device_names(), settings.output_device, SYSTEM_DEFAULT_LABEL
        )
        self.library_panel.ambient.set_loop(settings.loop_ambient)
        self.playlist_panel.set_mode(self.playlist.mode)
        self.library_panel.ambient.set_volume(int(settings.ambient_volume * 100))
        self.library_panel.sfx.set_volume(int(settings.sfx_volume * 100))
        self.controls.set_loudness(
            settings.normalise,
            settings.target_lufs,
            settings.ceiling_dbtp,
            settings.allow_boost,
            settings.trim_db,
        )

    def _connect_signals(self) -> None:
        bar = self.top_bar
        bar.theme_selected.connect(self._on_theme_selected)
        bar.customise_requested.connect(self._on_customise_theme)
        bar.reset_layout_requested.connect(self._reset_layout)
        bar.visualizer_style_selected.connect(self.visualizer.set_style)

        music = self.library_panel.music
        music.play_requested.connect(self._on_play_single)
        music.enqueue_requested.connect(self._on_enqueue)
        music.add_files_requested.connect(self._on_add_music)
        music.rename_requested.connect(self._on_rename)
        music.recategorise_requested.connect(self._on_recategorise)
        music.delete_requested.connect(lambda t: self._on_delete(MediaKind.MUSIC, t))
        music.new_category_requested.connect(self._on_new_category)
        music.rescan_requested.connect(lambda: self.rescan_library(quiet=False))
        music.layer_requested.connect(self._on_add_layer)
        music.analyse_requested.connect(self._on_analyse_library)

        sfx = self.library_panel.sfx
        sfx.add_files_requested.connect(self._on_add_sfx)
        sfx.play_requested.connect(self.engine.play_sfx)
        sfx.delete_requested.connect(lambda t: self._on_delete(MediaKind.SFX, t))
        sfx.volume_changed.connect(lambda v: self.engine.set_sfx_volume(v / 100.0))

        ambient = self.library_panel.ambient
        ambient.add_files_requested.connect(self._on_add_ambient)
        ambient.ambient_selected.connect(self._on_select_ambient)
        ambient.ambient_cleared.connect(self._on_clear_ambient)
        ambient.delete_requested.connect(lambda t: self._on_delete(MediaKind.AMBIENT, t))
        ambient.volume_changed.connect(lambda v: self.engine.set_ambient_volume(v / 100.0))
        ambient.loop_toggled.connect(self.engine.set_loop_ambient)

        queue = self.playlist_panel
        queue.mode_selected.connect(self._on_playback_mode)
        queue.play_index_requested.connect(self.engine.play_index)
        queue.move_requested.connect(self._on_move_in_playlist)
        queue.remove_requested.connect(self._on_remove_from_playlist)
        queue.clear_requested.connect(self._on_clear_playlist)
        queue.save_requested.connect(self._on_save_playlist)
        queue.load_requested.connect(self._on_load_playlist)

        controls = self.controls
        controls.play_clicked.connect(self._on_play_button)
        controls.stop_clicked.connect(self.engine.stop)
        controls.next_clicked.connect(self.engine.next)
        controls.previous_clicked.connect(self.engine.previous)
        controls.music_volume_changed.connect(lambda v: self.engine.set_music_volume(v / 100.0))
        controls.master_volume_changed.connect(lambda v: self.engine.set_master_volume(v / 100.0))
        controls.fade_toggled.connect(self._on_fade_toggled)
        controls.fade_seconds_changed.connect(self._on_fade_seconds)
        controls.loop_toggled.connect(self.engine.set_loop_music)
        controls.output_mode_selected.connect(self._on_output_mode)
        controls.output_device_selected.connect(self.engine.set_output_device)
        controls.normalise_toggled.connect(self.engine.set_normalisation)
        controls.target_lufs_changed.connect(self.engine.set_target_lufs)
        controls.ceiling_changed.connect(self.engine.set_ceiling_dbtp)
        controls.allow_boost_toggled.connect(self.engine.set_allow_boost)
        controls.trim_changed.connect(self.engine.set_trim_db)
        controls.locate_ffmpeg_requested.connect(self._on_locate_ffmpeg)
        controls.locate_opus_requested.connect(self._on_locate_opus)
        for signal in (
            controls.music_volume_changed,
            controls.master_volume_changed,
            controls.normalise_toggled,
            controls.target_lufs_changed,
            controls.ceiling_changed,
            controls.allow_boost_toggled,
            controls.trim_changed,
            controls.fade_toggled,
            controls.fade_seconds_changed,
        ):
            signal.connect(lambda *_: self._queue_settings_save())

        self.layer_mixer.trim_changed.connect(
            lambda voice_id, percent: self.engine.set_layer_trim(voice_id, percent / 100.0)
        )
        self.layer_mixer.stop_requested.connect(self._on_stop_layer)
        self.layer_mixer.loop_toggled.connect(self.engine.set_layer_loop)
        self.layer_mixer.pause_toggled.connect(self.engine.set_layer_paused)

        bridge = self.bridge
        bridge.track_changed.connect(self._on_track_changed)
        bridge.playing_changed.connect(self._on_playing_changed)
        bridge.status_changed.connect(controls.set_status)
        bridge.error_raised.connect(lambda message: warn(self, "Playback", message))
        bridge.layers_changed.connect(self._sync_layer_mixer)

    # ═════════════════════════════════════════════════════════════════════
    #  Live disk watching
    # ═════════════════════════════════════════════════════════════════════

    def _on_locate_ffmpeg(self) -> None:
        """Let someone point at an FFmpeg they already have.

        Validated before saving — a wrong file here would fail later with a
        confusing decode error rather than an obvious one.
        """
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Select ffmpeg.exe",
            "",
            "FFmpeg (ffmpeg.exe ffmpeg);;All files (*)",
        )
        if not chosen:
            return

        if not ffmpeg_looks_right(chosen):
            warn(
                self,
                "Not FFmpeg",
                f"{Path(chosen).name} does not respond like FFmpeg.\n\n"
                "Pick ffmpeg.exe itself — usually in a bin folder.",
            )
            return

        set_ffmpeg_executable(chosen)
        self.engine.settings.ffmpeg_path = chosen
        self.engine.save_settings()
        status = ffmpeg_status(refresh=True)
        self.services.ffmpeg = status
        self.debug.log(f"FFmpeg set to {chosen}", "SYS")
        self._report_missing_requirements()
        inform(
            self,
            "FFmpeg",
            f"Using {Path(chosen).name}.\n\n{status.version or 'Ready.'}",
        )

    def _on_locate_opus(self) -> None:
        """Point Opus at a specific DLL.

        Opus is loaded into the process rather than executed, so this can be
        applied immediately — disnake only needs it loaded before a voice
        connection, not before startup.
        """
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Select libopus-0.dll", "", "Opus library (*.dll *.so *.dylib);;All files (*)"
        )
        if not chosen:
            return

        if not opus_looks_right(chosen):
            warn(
                self,
                "Not libopus",
                f"{Path(chosen).name} could not be loaded as libopus.\n\n"
                "It should be a libopus DLL — disnake ships one in its bin folder.",
            )
            return

        self.engine.settings.opus_path = chosen
        self.engine.save_settings()
        loaded = ensure_opus(lambda message: self.debug.log(message, "OPUS"), preferred=chosen)
        self.debug.log(f"Opus set to {chosen} (loaded={loaded})", "SYS")
        self._report_missing_requirements()
        inform(self, "Opus", f"Using {Path(chosen).name}." if loaded else "Could not load it.")

    def _report_missing_requirements(self) -> None:
        """Put missing dependencies in the window, not just in a console.

        The packaged app runs windowed, so stdout goes nowhere — without this a
        missing PyNaCl looks like "the bot just doesn't work".
        """
        missing = missing_requirements(self.services.ffmpeg, self.services.discord_enabled)
        self.controls.set_warning(missing)
        if not missing:
            return
        for item in missing:
            self.debug.log(f"MISSING: {item}", "ERR")
        log_file = self.debug.log_file
        if log_file:
            self.debug.log(f"This session is being logged to {log_file}", "SYS")

    def _restore_layout(self) -> None:
        """Put the window and panels back where they were left.

        A layout saved by an older version describes a different set of docks, so
        restoring it produces a mangled window.  The version stamp makes those
        fall back to the current default instead.
        """
        self._default_dock_state = self.saveState()

        geometry = UiState.decode(self.ui_state.geometry)
        if geometry:
            self.restoreGeometry(QByteArray(geometry))

        saved_version = self.ui_state.extras.get("layout_version")
        if saved_version != LAYOUT_VERSION:
            if saved_version is not None:
                self.debug.log("Layout is from an older version; using the default", "SYS")
            return

        docks = UiState.decode(self.ui_state.dock_state)
        if docks and not self.restoreState(QByteArray(docks)):
            self.debug.log("Saved layout could not be restored; using the default", "SYS")

        # Never start with everything hidden — that looks like a broken app.
        if all(dock.isHidden() for dock in self.docks.values()):
            self.debug.log("Every panel was hidden; restoring them", "SYS")
            self._show_all_docks()

    def _save_ui_state(self) -> None:
        self.ui_state.theme = self.themes.label_for(self.themes.current)
        self.ui_state.geometry = UiState.encode(self.saveGeometry())
        self.ui_state.dock_state = UiState.encode(self.saveState())
        self.ui_state.extras["layout_version"] = LAYOUT_VERSION
        self.ui_state.save()

    def _install_audio_device_watcher(self) -> None:
        """Keep the device list in step with the OS.

        Headsets get plugged in mid-session, so the list is refreshed rather than
        captured once at startup.
        """
        self._media_devices = QMediaDevices(self)
        self._media_devices.audioOutputsChanged.connect(self._refresh_audio_devices)
        self._refresh_audio_devices()

    def _refresh_audio_devices(self) -> None:
        names = LocalAudioSink.device_names()
        self.controls.set_output_devices(
            names, self.engine.settings.output_device, SYSTEM_DEFAULT_LABEL
        )
        wanted = self.engine.settings.output_device
        if wanted and wanted not in names:
            self.debug.log(f"Audio device '{wanted}' is not available", "MIX")

    def _install_disk_watcher(self) -> None:
        """Notice files dropped into the folders by hand, without a restart."""
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_directory_changed)

        # Debounce: a copy of several files fires many events.
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.setInterval(600)
        self._rescan_timer.timeout.connect(lambda: self.rescan_library(quiet=True))

        self._refresh_watched_paths()

    def _refresh_watched_paths(self) -> None:
        wanted = {str(paths.music), str(paths.sfx), str(paths.ambient)}
        if paths.music.is_dir():
            wanted |= {str(d) for d in paths.music.iterdir() if d.is_dir()}
        current = set(self._watcher.directories())
        for gone in current - wanted:
            self._watcher.removePath(gone)
        for added in wanted - current:
            if Path(added).is_dir():
                self._watcher.addPath(added)

    def _on_directory_changed(self, _path: str) -> None:
        self._rescan_timer.start()

    def rescan_library(self, quiet: bool = False) -> None:
        result = self.library.sync_with_disk()
        self._refresh_watched_paths()
        if result.changed:
            self.library.save()
            self.refresh_library()
            names = ", ".join(t.display_name for t in result.added[:3])
            summary = f"Library updated: {result}"
            if names:
                summary += f" ({names}{'...' if len(result.added) > 3 else ''})"
            self.debug.log(summary, "SYNC")
            self.controls.set_status(summary)
        elif not quiet:
            inform(self, "Rescan", "No changes found — the library matches the folders.")

    # ═════════════════════════════════════════════════════════════════════
    #  Mixer telemetry
    # ═════════════════════════════════════════════════════════════════════

    def _install_settings_saver(self) -> None:
        """Write levels to disk 2 s after the last change, not on every step."""
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(2000)
        self._save_timer.timeout.connect(self.engine.save_settings)

    def _queue_settings_save(self) -> None:
        self._save_timer.start()

    def _install_mixer_poll(self) -> None:
        self.visualizer.level_provider = self.engine.spectrum
        self._mixer_timer = QTimer(self)
        self._mixer_timer.setInterval(500)
        self._mixer_timer.timeout.connect(self._update_mixer_readout)
        self._mixer_timer.start()

    def _update_mixer_readout(self) -> None:
        # Doubles as the idle poll: stop transmitting when there's nothing to send.
        self.engine.suspend_if_idle()

        info = self.engine.diagnostics()
        if not info.get("attached"):
            if self.engine.can_output:
                where = "speakers" if self.engine.output_mode is OutputMode.LOCAL else "Discord"
                self.controls.set_mixer_readout(f"Ready ({where}), silent — no output")
            else:
                self.controls.set_mixer_readout("Idle — no output available")
            return
        if info.get("normalise"):
            norm = f"norm {info['target_lufs']:.1f} LUFS"
            norm += " +boost" if info.get("allow_boost") else " (cut only)"
        else:
            norm = "norm off"
        if info.get("paused"):
            norm += "  | PAUSED"
        clipped = info.get("clipped", 0)
        warning = f"\nCLIPPING on {clipped} frames — lower Master" if clipped else ""
        if self.engine.output_mode is OutputMode.LOCAL and self.engine.local_sink is not None:
            served = self.engine.local_sink.frames_served
            local = f"  local frames {served}" if served else "  local: no frames pulled!"
        else:
            local = ""
        effective = self.engine.effective_lufs()
        out = f"out {self.engine.effective_music_db():+.1f} dB"
        if effective is not None:
            out += f"  ~{effective:.0f} LUFS"
        self.controls.set_mixer_readout(
            f"music {info['music']}  ambient {info['ambient']}  sfx {info['sfx']}\n"
            f"level {info['level']:.2f}  {out}\n"
            f"{norm}{local}{warning}"
        )
        self._sync_layer_mixer()

    def _sync_layer_mixer(self) -> None:
        self.layer_mixer.sync(self.engine.layers())

    # ═════════════════════════════════════════════════════════════════════
    #  Rendering
    # ═════════════════════════════════════════════════════════════════════

    def refresh_all(self) -> None:
        self.refresh_library()
        self.refresh_playlist()

    def refresh_library(self) -> None:
        self.library_panel.music.set_tracks(
            self.library.sorted_tracks(MediaKind.MUSIC), list(self.categories)
        )
        self.library_panel.sfx.set_tracks(self.library.sorted_tracks(MediaKind.SFX))
        ambient_track = self.engine.ambient_track
        self.library_panel.ambient.set_tracks(
            self.library.sorted_tracks(MediaKind.AMBIENT),
            ambient_track.path if ambient_track else None,
        )

    def refresh_playlist(self) -> None:
        self.playlist_panel.set_tracks(self.playlist.tracks, self.playlist.index)

    # ═════════════════════════════════════════════════════════════════════
    #  Theme handlers
    # ═════════════════════════════════════════════════════════════════════

    def _apply_theme(self, cfg) -> None:
        self.themes.apply(self, cfg)
        self.visualizer.set_colors(cfg.primary, cfg.accent)

    def _on_theme_selected(self, label: str) -> None:
        cfg = self.themes.resolve(label)
        if cfg:
            self._apply_theme(cfg)
            self._save_ui_state()      # the chosen theme is remembered

    def _on_customise_theme(self) -> None:
        dialog = ThemeEditorDialog(self, self.themes.current)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        cfg = dialog.config()
        if confirm(self, "Save?", f"Save theme '{cfg.name}'?"):
            self.themes.remember(cfg)
            self.top_bar.add_theme_label(self.themes.label_for(cfg))
        self._apply_theme(cfg)

    # ═════════════════════════════════════════════════════════════════════
    #  Library handlers
    # ═════════════════════════════════════════════════════════════════════

    def _import(self, kind: MediaKind, title: str, category: Optional[str]) -> None:
        files = pick_audio_files(self, title)
        if not files:
            return
        if category is None:
            category = choose_category(self, self.categories)
            if category is None:
                return
        try:
            for file in files:
                self.library.import_file(file, kind, category)
        except LibraryError as exc:
            warn(self, "Import Error", str(exc))
        self.library.save()
        self.refresh_library()

    def _on_add_music(self) -> None:
        self._import(MediaKind.MUSIC, "Select Music", None)

    def _on_add_sfx(self) -> None:
        self._import(MediaKind.SFX, "Select SFX", "SFX")

    def _on_add_ambient(self) -> None:
        self._import(MediaKind.AMBIENT, "Select Ambient", "AMBIENT")

    def _on_rename(self, track: MusicTrack) -> None:
        name = ask_text(self, "Rename", "New name:", track.display_name)
        if not name:
            return
        try:
            self.library.rename(track, name)
        except LibraryError as exc:
            warn(self, "Rename", str(exc))
            return
        self.library.save()
        self.refresh_library()
        self.refresh_playlist()

    def _on_recategorise(self, track: MusicTrack) -> None:
        category = choose_category(self, self.categories, exclude=track.category, title="Move to")
        if not category:
            return
        try:
            self.library.move_to_category(track, category)
        except LibraryError as exc:
            warn(self, "Error", str(exc))
            return
        self.library.save()
        self.refresh_library()
        self.refresh_playlist()

    def _on_delete(self, kind: MediaKind, track: MusicTrack) -> None:
        if not confirm(self, "Delete?", f"Delete '{track.display_name}'?"):
            return
        active_ambient = self.engine.ambient_track
        if kind is MediaKind.AMBIENT and active_ambient and active_ambient.path == track.path:
            self._on_clear_ambient()
        try:
            self.library.delete(kind, track)
        except LibraryError as exc:
            warn(self, "Error", str(exc))
            return
        self.library.save()
        self.refresh_library()

    def _on_new_category(self) -> None:
        name = ask_text(self, "New Folder", "Name:")
        if not name:
            return
        emoji = ask_text(self, "Emoji", "Emoji (optional):", "📁") or "📁"
        if self.categories.add(emoji, name) is None:
            warn(self, "New Folder", f"'{name}' already exists.")
            return
        self.categories.save_custom()
        self.refresh_library()

    # ═════════════════════════════════════════════════════════════════════
    #  Ambient handlers
    # ═════════════════════════════════════════════════════════════════════

    def _on_select_ambient(self, track: MusicTrack) -> None:
        self.engine.set_ambient(track)
        self.library_panel.ambient.set_active(track)
        self.refresh_library()

    def _on_clear_ambient(self) -> None:
        self.engine.clear_ambient()
        self.library_panel.ambient.set_active(None)
        self.refresh_library()

    # ═════════════════════════════════════════════════════════════════════
    #  Playlist handlers
    # ═════════════════════════════════════════════════════════════════════

    def _on_play_single(self, track: MusicTrack) -> None:
        """Double-click in the library.

        In multi-track mode this layers the track on top of what's playing; in
        every other mode it replaces the queue with just this track.
        """
        if self.playlist.mode is PlaybackMode.MULTITRACK:
            self._on_add_layer(track)
            return
        self.playlist.set_tracks([track])
        self.playlist.mode = PlaybackMode.SINGLE
        self.playlist_panel.set_mode(PlaybackMode.SINGLE)
        self.refresh_playlist()
        self.engine.play(track)

    def _on_add_layer(self, track: MusicTrack) -> None:
        """Play a track alongside whatever is already going."""
        if self.engine.add_layer(track):
            self._sync_layer_mixer()

    def _on_stop_layer(self, voice_id: int) -> None:
        self.engine.stop_layer(voice_id)
        self._sync_layer_mixer()

    def _on_import_folder(self) -> None:
        """Point at a folder — subfolders become categories."""
        folder = QFileDialog.getExistingDirectory(self, "Import a folder of music")
        if not folder:
            return
        self._run_import(
            lambda report: import_folder(
                self.library, self.categories, Path(folder), progress=report
            ),
            f"Importing {Path(folder).name}",
        )

    def _on_import_legacy(self) -> None:
        """Import an older install's library file, measurements and all."""
        file, _ = QFileDialog.getOpenFileName(
            self, "Select an old music_data.json", "", "Library data (*.json)"
        )
        if not file:
            return
        self._run_import(
            lambda report: import_legacy_library(
                self.library, self.categories, Path(file), progress=report
            ),
            "Importing the old library",
        )

    def _run_import(self, work, title: str) -> None:
        def report(index: int, total: int, name: str) -> None:
            self.controls.set_status(f"{title}: {index}/{total} — {name}")
            QApplication.processEvents()

        result = work(report)
        if result.categories_created:
            self.categories.save_custom()
        self.library.save()
        self.refresh_library()
        self._refresh_watched_paths()
        self.controls.set_status(str(result))
        self.debug.log(f"{title}: {result}", "IMPORT")

        message = str(result)
        if result.failed:
            message += "\n\nProblems:\n" + "\n".join(result.failed[:10])
            if len(result.failed) > 10:
                message += f"\n… and {len(result.failed) - 10} more"
        QMessageBox.information(self, "Import complete", message)

    def _on_analyse_library(self) -> None:
        """Measure loudness for every unmeasured track, so gains are ready."""
        pending = self.library.unmeasured()
        if not pending:
            inform(self, "Loudness", "Every track is already measured.")
            return
        if not confirm(
            self,
            "Analyse loudness",
            f"Measure {len(pending)} track(s)? This runs FFmpeg once per file "
            f"and is cached afterwards.",
        ):
            return

        for index, track in enumerate(pending, start=1):
            self.controls.set_status(f"Analysing {index}/{len(pending)}: {track.display_name}")
            QApplication.processEvents()
            self.library.measure_track(track)
        self.library.save()
        self.refresh_library()
        self.controls.set_status(f"Analysed {len(pending)} track(s)")
        inform(self, "Loudness", f"Measured {len(pending)} track(s).")

    def _on_enqueue(self, track: MusicTrack) -> None:
        self.playlist.add(track)
        self.refresh_playlist()

    def _on_playback_mode(self, mode: PlaybackMode) -> None:
        self.playlist.mode = mode
        # A queue can't advance while the current track repeats, so turning on a
        # queue mode turns repeat off.  Still overridable afterwards.
        if mode in (PlaybackMode.PLAYLIST, PlaybackMode.SHUFFLE) and self.engine.settings.loop_music:
            self.engine.set_loop_music(False)
            self.controls.set_loop(False)
        self.debug.log(f"Playback mode: {mode.value}", "PLAY")

    def _on_output_failed(self, message: str) -> None:
        """The local sink starts asynchronously, so failures arrive here."""
        self.engine.handle_output_failure(message)
        self.controls.set_status(f"Local output failed: {message}")

    def _on_output_mode(self, mode: OutputMode) -> None:
        if mode is None:
            return
        self.engine.set_output_mode(mode)
        if mode is OutputMode.LOCAL:
            device = LocalAudioSink.default_device_name() or "default device"
            self.controls.set_status(f"Playing locally — {device}")
        elif self.engine.is_connected:
            self.controls.set_status("Streaming to Discord")
        else:
            self.controls.set_status("Discord output — bot not in a channel yet")

    def _on_move_in_playlist(self, position: int, offset: int) -> None:
        new_position = self.playlist.move(position, offset)
        if new_position is None:
            return
        self.refresh_playlist()
        self.playlist_panel.set_current_index(new_position)

    def _on_remove_from_playlist(self, position: int) -> None:
        self.playlist.remove(position)
        self.refresh_playlist()

    def _on_clear_playlist(self) -> None:
        self.playlist.clear()
        self.refresh_playlist()

    def _on_save_playlist(self) -> None:
        if not self.playlist.tracks:
            return
        name = ask_text(self, "Save Playlist", "Name:")
        if not name:
            return
        target = save_playlist(name, self.playlist.tracks)
        self.debug.log(f"Playlist saved: {target.name}", "PL")

    def _on_load_playlist(self) -> None:
        file, _ = QFileDialog.getOpenFileName(self, "Load", str(paths.playlists), "*.json")
        if not file:
            return
        try:
            tracks = load_playlist(Path(file), self.library.music)
        except Exception as exc:
            warn(self, "Error", str(exc))
            return
        self.playlist.set_tracks(tracks)
        self.refresh_playlist()

    # ═════════════════════════════════════════════════════════════════════
    #  Transport handlers
    # ═════════════════════════════════════════════════════════════════════

    def _on_play_button(self) -> None:
        """Play / pause / resume — pausing holds position instead of restarting."""
        if self.engine.is_paused:
            self.engine.resume()
            return
        if self.engine.is_playing:
            self.engine.pause()
            return
        if self.playlist.tracks:
            index = max(0, self.playlist_panel.current_index)
            self.engine.play_index(index)
            return
        track = self.library_panel.music.selected_track()
        if track:
            self._on_play_single(track)

    def _on_fade_toggled(self, enabled: bool) -> None:
        self.engine.settings.fade_enabled = enabled

    def _on_fade_seconds(self, seconds: int) -> None:
        self.engine.settings.fade_seconds = seconds

    def _on_track_changed(self, track: Optional[MusicTrack]) -> None:
        self.controls.set_now_playing(track)
        if track is not None:
            self.playlist_panel.set_current_index(self.playlist.index)

    def _on_playing_changed(self, playing: bool) -> None:
        self.controls.set_playing(playing)
        self.visualizer.set_playing(playing)

    # ═════════════════════════════════════════════════════════════════════
    #  Bot lifecycle
    # ═════════════════════════════════════════════════════════════════════

    def start_bot(self) -> None:
        if not DISCORD_AVAILABLE:
            self.controls.set_status(f"disnake missing — {INSTALL_HINT}")
            return

        token = resolve_token(allow_remote=not self.services.dev_mode)
        if not token:
            self.debug.log("No token found, showing setup dialog", "SYS")
            token = show_token_setup_dialog(self)
        if not token:
            self.controls.set_status("No token — restart to set one up")
            self.debug.log("User cancelled token setup", "SYS")
            return

        context = BotContext(
            engine=self.engine,
            library=self.library,
            debug=self.debug,
            on_status=self.bridge.status_changed.emit,
        )
        self.bot_runner = BotRunner(token, context)
        self.engine.bind_loop(lambda: self.bot_runner.loop if self.bot_runner else None)
        self.controls.set_status("Connecting to Discord...")
        self.bot_runner.start()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._save_ui_state()
        self.engine.save_settings()
        self.engine.shutdown()
        if self.bot_runner:
            self.bot_runner.stop()
        event.accept()
