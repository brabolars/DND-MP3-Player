# src/dndmusic/gui/widgets/control_panel.py
"""Right-hand column: bot status, now playing, transport, volume, fades."""

from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QScrollArea,
    QSizePolicy,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.models import MusicTrack, OutputMode

PLAY_GLYPH = "▶"
PAUSE_GLYPH = "⏸"


class ControlPanel(QWidget):
    play_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    next_clicked = pyqtSignal()
    previous_clicked = pyqtSignal()
    music_volume_changed = pyqtSignal(int)
    master_volume_changed = pyqtSignal(int)
    fade_toggled = pyqtSignal(bool)
    fade_seconds_changed = pyqtSignal(int)
    loop_toggled = pyqtSignal(bool)
    output_mode_selected = pyqtSignal(object)
    output_device_selected = pyqtSignal(str)
    normalise_toggled = pyqtSignal(bool)
    target_lufs_changed = pyqtSignal(float)
    ceiling_changed = pyqtSignal(float)
    allow_boost_toggled = pyqtSignal(bool)
    trim_changed = pyqtSignal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Everything sits in a scroll area: the panel has a lot of groups, and a
        # short window should scroll rather than stretch each group into a gap.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(6)

        for build in (
            self._build_output,
            self._build_status,
            self._build_now_playing,
            self._build_transport,
            self._build_transitions,
            self._build_loudness,
            self._build_mixer_readout,
        ):
            group = build()
            # Keep each group at its natural height instead of expanding.
            group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            layout.addWidget(group)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        outer.addWidget(scroll)

    # ── construction ─────────────────────────────────────────────────────

    def _build_output(self) -> QGroupBox:
        group = QGroupBox("Output")
        layout = QVBoxLayout(group)
        self.output_combo = QComboBox()
        for mode in OutputMode:
            self.output_combo.addItem(mode.value, mode)
        self.output_combo.setToolTip(
            "Where the mixer sends audio.\n"
            "Discord bot: streamed into the voice channel.\n"
            "This PC: straight out of your speakers, so the app works as a\n"
            "plain music player with no bot involved.\n\n"
            "Switching stops playback — a frame can only be played once, so the\n"
            "two outputs can't share the mixer."
        )
        self.output_combo.currentIndexChanged.connect(self._on_output_changed)
        layout.addWidget(self.output_combo)

        device_row = QHBoxLayout()
        device_row.addWidget(QLabel("Device:"))
        self.device_combo = QComboBox()
        self.device_combo.setToolTip(
            "Which sound device local playback uses.\n"
            "'System default' follows whatever Windows is set to.\n"
            "Only applies to This PC output; switching applies immediately."
        )
        self.device_combo.currentIndexChanged.connect(
            lambda index: self.output_device_selected.emit(
                self.device_combo.itemData(index) or ""
            )
        )
        device_row.addWidget(self.device_combo, 1)
        layout.addLayout(device_row)
        return group

    def _build_status(self) -> QGroupBox:
        group = QGroupBox("Bot Status")
        layout = QVBoxLayout(group)
        self.status_label = QLabel("Starting...")
        self.status_label.setStyleSheet("padding: 8px; font-weight: bold;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        return group

    def _build_now_playing(self) -> QGroupBox:
        group = QGroupBox("Now Playing")
        layout = QVBoxLayout(group)
        self.now_playing_label = QLabel("Nothing playing")
        self.now_playing_label.setStyleSheet(
            "font-size: 14px; padding: 12px; font-weight: bold;"
        )
        self.now_playing_label.setWordWrap(True)
        layout.addWidget(self.now_playing_label)
        return group

    def _build_transport(self) -> QGroupBox:
        group = QGroupBox("Playback")
        layout = QVBoxLayout(group)

        transport = QHBoxLayout()
        transport.setSpacing(8)
        self.previous_button = QPushButton("⏮")
        self.play_button = QPushButton(PLAY_GLYPH)
        self.stop_button = QPushButton("⏹")
        self.next_button = QPushButton("⏭")
        self.play_button.setToolTip("Play, or pause/resume without losing your place")
        for button, signal in (
            (self.previous_button, self.previous_clicked),
            (self.play_button, self.play_clicked),
            (self.stop_button, self.stop_clicked),
            (self.next_button, self.next_clicked),
        ):
            button.setMinimumSize(50, 42)
            button.setStyleSheet(button.styleSheet() + "font-size: 20px;")
            button.clicked.connect(signal.emit)
            transport.addWidget(button)

        self.loop_button = QPushButton("↻")
        self.loop_button.setCheckable(True)
        self.loop_button.setChecked(True)
        self.loop_button.setMinimumSize(50, 42)
        self.loop_button.setStyleSheet(self.loop_button.styleSheet() + "font-size: 20px;")
        self.loop_button.setToolTip(
            "Repeat the current track.\n"
            "With this on, a playlist will not advance — the track repeats instead."
        )
        self.loop_button.toggled.connect(self.loop_toggled.emit)
        transport.addWidget(self.loop_button)
        layout.addLayout(transport)

        self.music_slider, self.music_label = self._volume_row(
            layout, "Music:", 50, self._on_music_volume
        )
        self.master_slider, self.master_label = self._volume_row(
            layout, "Master:", 100, self._on_master_volume
        )
        self.music_slider.setToolTip("Level of the music bus.")
        self.master_slider.setToolTip(
            "Applies on top of every bus — master and music multiply.\n"
            "Leave this at 100% and use Music, unless you want to duck everything."
        )

        self.effective_label = QLabel()
        self.effective_label.setStyleSheet("font-size: 11px; color: #9a9a9a;")
        layout.addWidget(self.effective_label)
        self._update_effective()
        return group

    def _update_effective(self) -> None:
        """Spell out the multiplication, because two sliders at 50% is -12 dB."""
        music = self.music_slider.value() / 100.0
        master = self.master_slider.value() / 100.0
        combined = music * master
        if combined <= 0:
            text = "music x master = silent"
        else:
            db = 20 * math.log10(combined)
            text = (
                f"music {self.music_slider.value()}% x master "
                f"{self.master_slider.value()}% = {db:+.1f} dB"
            )
        self.effective_label.setText(text)

    def _volume_row(self, layout, label, initial, handler):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(initial)
        value_label = QLabel(f"{initial}%")
        value_label.setMinimumWidth(40)
        slider.valueChanged.connect(handler)
        row.addWidget(slider)
        row.addWidget(value_label)
        layout.addLayout(row)
        return slider, value_label

    def _build_transitions(self) -> QGroupBox:
        group = QGroupBox("Transitions")
        layout = QVBoxLayout(group)

        self.fade_checkbox = QCheckBox("Smooth transitions")
        self.fade_checkbox.setChecked(True)
        self.fade_checkbox.toggled.connect(self.fade_toggled.emit)
        layout.addWidget(self.fade_checkbox)

        row = QHBoxLayout()
        row.addWidget(QLabel("Fade:"))
        self.fade_spin = QSpinBox()
        self.fade_spin.setRange(1, 5)
        self.fade_spin.setValue(2)
        self.fade_spin.setSuffix("s")
        self.fade_spin.valueChanged.connect(self.fade_seconds_changed.emit)
        row.addWidget(self.fade_spin)
        row.addStretch()
        layout.addLayout(row)
        return group

    #: (label, LUFS) — the recognised reference targets.
    #: Reference targets, quietest first.  The right one depends on whether the
    #: music is *under* speech or is itself the thing being listened to.
    LOUDNESS_PRESETS = (
        ("Very quiet bed", -40.0),
        ("Quiet bed under talk", -30.0),
        ("Bed under talk", -26.0),
        ("Under conversation (default)", -24.0),
        ("Broadcast (EBU R128)", -23.0),
        ("Featured, nobody talking", -18.0),
        ("Podcast (Apple)", -16.0),
        ("Streaming (Spotify/YT)", -14.0),
        ("Custom", None),
    )

    def _build_loudness(self) -> QGroupBox:
        group = QGroupBox("Loudness")
        layout = QVBoxLayout(group)

        self.normalise_checkbox = QCheckBox("Normalise all audio")
        self.normalise_checkbox.setChecked(True)
        self.normalise_checkbox.setToolTip(
            "Measure each file's loudness (EBU R128) and match it to the target,\n"
            "so no track is jarringly louder than another."
        )
        self.normalise_checkbox.toggled.connect(self.normalise_toggled.emit)
        layout.addWidget(self.normalise_checkbox)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems([label for label, _ in self.LOUDNESS_PRESETS])
        self.preset_combo.currentIndexChanged.connect(self._on_preset)
        preset_row.addWidget(self.preset_combo, 1)
        layout.addLayout(preset_row)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target:"))
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(-60.0, -3.0)
        self.target_spin.setDecimals(1)
        self.target_spin.setSingleStep(0.5)
        self.target_spin.setValue(-24.0)
        self.target_spin.setSuffix(" LUFS")
        self.target_spin.setKeyboardTracking(False)   # emit on Enter/focus-out, not per keystroke
        self.target_spin.setToolTip(
            "Integrated loudness every track is matched to.\n"
            "LOWER (more negative) = quieter.  Raising this makes everything louder,\n"
            "because less attenuation is applied.\n\n"
            "-30 quiet bed  ·  -24 under conversation (ATSC/GANG)\n"
            "-23 broadcast (EBU R128)  ·  -18 speech level  ·  -14 streaming"
        )
        self.target_spin.valueChanged.connect(self._on_target)
        target_row.addWidget(self.target_spin, 1)
        layout.addLayout(target_row)

        ceiling_row = QHBoxLayout()
        ceiling_row.addWidget(QLabel("Peak ceiling:"))
        self.ceiling_spin = QDoubleSpinBox()
        self.ceiling_spin.setRange(-6.0, 0.0)
        self.ceiling_spin.setDecimals(1)
        self.ceiling_spin.setSingleStep(0.5)
        self.ceiling_spin.setValue(-1.0)
        self.ceiling_spin.setSuffix(" dBTP")
        self.ceiling_spin.setKeyboardTracking(False)
        self.ceiling_spin.setToolTip(
            "A boost is held back rather than pushing a track's true peak\n"
            "above this, so normalisation can never cause clipping."
        )
        self.ceiling_spin.valueChanged.connect(self.ceiling_changed.emit)
        ceiling_row.addWidget(self.ceiling_spin, 1)
        layout.addLayout(ceiling_row)

        trim_row = QHBoxLayout()
        trim_row.addWidget(QLabel("Trim:"))
        self.trim_spin = QDoubleSpinBox()
        self.trim_spin.setRange(-24.0, 12.0)
        self.trim_spin.setDecimals(1)
        self.trim_spin.setSingleStep(0.5)
        self.trim_spin.setValue(0.0)
        self.trim_spin.setSuffix(" dB")
        self.trim_spin.setKeyboardTracking(False)
        self.trim_spin.setToolTip(
            "A manual nudge on top of everything else.\n"
            "The target sets the level; this is the escape hatch when a room or\n"
            "rig needs a little more or less without re-tuning the target."
        )
        self.trim_spin.valueChanged.connect(self.trim_changed.emit)
        trim_row.addWidget(self.trim_spin)
        trim_row.addStretch()
        layout.addLayout(trim_row)

        self.boost_checkbox = QCheckBox("Also boost quiet tracks")
        self.boost_checkbox.setChecked(False)
        self.boost_checkbox.setToolTip(
            "Off (default): normalisation only turns loud tracks down, so it can\n"
            "never make anything louder than the file itself.\n"
            "On: quiet tracks are raised towards the target too, by up to 6 dB."
        )
        self.boost_checkbox.toggled.connect(self.allow_boost_toggled.emit)
        layout.addWidget(self.boost_checkbox)

        return group

    def _on_output_changed(self, index: int) -> None:
        mode = self.output_combo.itemData(index)
        # Keep the device picker's enabled state in step with a user-made change,
        # not just a programmatic one.
        self.device_combo.setEnabled(mode is OutputMode.LOCAL)
        self.output_mode_selected.emit(mode)

    def _on_preset(self, index: int) -> None:
        _label, value = self.LOUDNESS_PRESETS[index]
        if value is None:
            return  # "Custom" — leave the spin box to the user
        self.target_spin.blockSignals(True)
        self.target_spin.setValue(value)
        self.target_spin.blockSignals(False)
        self.target_lufs_changed.emit(value)

    def _on_target(self, value: float) -> None:
        """Typing a value that isn't a preset switches the picker to Custom."""
        matched = next(
            (i for i, (_, preset) in enumerate(self.LOUDNESS_PRESETS)
             if preset is not None and abs(preset - value) < 0.05),
            len(self.LOUDNESS_PRESETS) - 1,
        )
        if self.preset_combo.currentIndex() != matched:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(matched)
            self.preset_combo.blockSignals(False)
        self.target_lufs_changed.emit(value)

    def _build_mixer_readout(self) -> QGroupBox:
        group = QGroupBox("Mixer")
        layout = QVBoxLayout(group)
        self.mixer_label = QLabel("Idle")
        self.mixer_label.setStyleSheet("padding: 6px; font-family: Consolas, monospace;")
        self.mixer_label.setWordWrap(True)
        layout.addWidget(self.mixer_label)
        return group

    # ── updates ──────────────────────────────────────────────────────────

    def _on_music_volume(self, value: int) -> None:
        self.music_label.setText(f"{value}%")
        self._update_effective()
        self.music_volume_changed.emit(value)

    def _on_master_volume(self, value: int) -> None:
        self.master_label.setText(f"{value}%")
        self._update_effective()
        self.master_volume_changed.emit(value)

    def set_mixer_readout(self, text: str) -> None:
        self.mixer_label.setText(text)

    def set_volumes(self, music: int, master: int) -> None:
        """Set both faders without emitting, then refresh the dB readout."""
        for slider, label, value in (
            (self.music_slider, self.music_label, music),
            (self.master_slider, self.master_label, master),
        ):
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
            label.setText(f"{value}%")
        self._update_effective()

    def set_loop(self, enabled: bool) -> None:
        self.loop_button.blockSignals(True)
        self.loop_button.setChecked(enabled)
        self.loop_button.blockSignals(False)

    def set_output_mode(self, mode: OutputMode) -> None:
        index = self.output_combo.findData(mode)
        if index >= 0:
            self.output_combo.blockSignals(True)
            self.output_combo.setCurrentIndex(index)
            self.output_combo.blockSignals(False)
        # The device picker only means anything for local playback.
        self.device_combo.setEnabled(mode is OutputMode.LOCAL)

    def set_output_devices(self, names, current: str = "", default_label: str = "System default") -> None:
        """Repopulate the device list, keeping the current choice if it survives."""
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem(default_label, "")
        for name in names:
            self.device_combo.addItem(name, name)

        index = self.device_combo.findData(current) if current else 0
        if index < 0:
            # The saved device is gone (unplugged); fall back to the default.
            index = 0
        self.device_combo.setCurrentIndex(index)
        self.device_combo.blockSignals(False)

    def set_fade(self, enabled: bool, seconds: int) -> None:
        for widget, value in ((self.fade_checkbox, enabled), (self.fade_spin, seconds)):
            widget.blockSignals(True)
            widget.setChecked(value) if widget is self.fade_checkbox else widget.setValue(value)
            widget.blockSignals(False)

    def set_loudness(
        self,
        normalise: bool,
        target: float,
        ceiling: float = -1.0,
        allow_boost: bool = False,
        trim_db: float = 0.0,
    ) -> None:
        for widget, value in ((self.boost_checkbox, allow_boost), (self.trim_spin, trim_db)):
            widget.blockSignals(True)
            if widget is self.boost_checkbox:
                widget.setChecked(value)
            else:
                widget.setValue(float(value))
            widget.blockSignals(False)
        self.normalise_checkbox.blockSignals(True)
        self.normalise_checkbox.setChecked(normalise)
        self.normalise_checkbox.blockSignals(False)

        for spin, value in ((self.target_spin, target), (self.ceiling_spin, ceiling)):
            spin.blockSignals(True)
            spin.setValue(float(value))
            spin.blockSignals(False)


        index = next(
            (i for i, (_, preset) in enumerate(self.LOUDNESS_PRESETS)
             if preset is not None and abs(preset - target) < 0.05),
            len(self.LOUDNESS_PRESETS) - 1,
        )
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(index)
        self.preset_combo.blockSignals(False)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_now_playing(self, track: Optional[MusicTrack]) -> None:
        if track is None:
            self.now_playing_label.setText("Nothing playing")
        else:
            self.now_playing_label.setText(f"{track.display_name}\n[{track.category}]")

    def set_playing(self, playing: bool) -> None:
        self.play_button.setText(PAUSE_GLYPH if playing else PLAY_GLYPH)
