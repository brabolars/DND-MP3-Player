# src/dndmusic/gui/theme/stylesheet.py
"""Qt stylesheet generation from a :class:`ThemeConfig`.

Pure string building, so it can be tested without a QApplication.
"""

from __future__ import annotations

from typing import List

from .models import ThemeConfig, VisualStyle

FONT_STACKS = {
    VisualStyle.SCI_FI: "Segoe UI, Arial, sans-serif",
    VisualStyle.MEDIEVAL: "Georgia, serif",
    VisualStyle.CASUAL: "Verdana, sans-serif",
    VisualStyle.MINIMAL: "Segoe UI, sans-serif",
}


def hex_to_rgba(value: str, alpha: float = 0.4) -> str:
    value = value.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def make_gradient(colors: List[str], angle: int) -> str:
    if len(colors) == 1:
        return colors[0]
    stops = ", ".join(f"stop:{i / (len(colors) - 1):.3f} {c}" for i, c in enumerate(colors))
    x2 = "0" if angle in (90, 270) else ("1" if angle <= 180 else "0")
    y2 = "1" if angle == 180 else ("0" if angle == 0 else "0.5")
    return f"qlineargradient(x1:0,y1:0,x2:{x2},y2:{y2},{stops})"


def build_stylesheet(cfg: ThemeConfig, background_image: str = "") -> str:
    """Render the theme.

    ``background_image`` is a pre-composited PNG (image blended with its veil);
    when given it replaces the gradient behind the window.
    """
    primary, accent = cfg.primary, cfg.accent
    radius, border = cfg.border_radius, cfg.border_width
    inner_radius = max(2, radius - 2)
    background = make_gradient(cfg.gradient_colors, cfg.gradient_angle)
    font = FONT_STACKS[cfg.visual_style]

    if background_image:
        # Forward slashes: Qt stylesheet urls are not Windows paths.
        url = background_image.replace("\\", "/")
        window_background = (
            f"background-image: url({url});"
            "background-position: center center;"
            "background-repeat: no-repeat;"
            "background-attachment: fixed;"
        )
    else:
        window_background = f"background: {background};"

    return f"""
    * {{ font-family: {font}; }}
    QMainWindow {{ {window_background} }}
    QMainWindow > QWidget {{ background: transparent; }}
    QDockWidget {{ color: {primary}; titlebar-close-icon: none; }}
    QDockWidget::title {{
        background: rgba(0,0,0,0.55); padding: 6px 10px;
        border: {border}px solid {accent}; border-radius: {radius}px;
        font-weight: bold;
    }}
    QGroupBox {{
        color: {primary}; border: {border}px solid {accent}; border-radius: {radius}px;
        margin-top: 14px; padding: 16px 12px 12px 12px;
        font-weight: bold; font-size: 13px;
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 rgba(255,255,255,0.04), stop:1 rgba(0,0,0,0.25));
    }}
    QGroupBox::title {{
        subcontrol-origin: margin; left: 14px; padding: 0 8px; color: {primary};
    }}
    QLabel {{ color: #d8d8d8; font-size: 12px; }}

    QPushButton {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 {accent}, stop:1 rgba(0,0,0,0.8));
        color: {primary}; border: {border}px solid {accent}; padding: 7px 14px;
        border-radius: {radius}px; font-size: 12px; font-weight: bold;
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 {primary}, stop:1 {accent});
        border-color: {primary};
    }}
    QPushButton:pressed {{ background: {accent}; }}

    QListWidget, QTreeWidget {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 rgba(0,0,0,0.5), stop:1 rgba(0,0,0,0.85));
        color: #d8d8d8; border: {border}px solid {accent}; border-radius: {radius}px;
        padding: 4px; outline: none;
    }}
    QListWidget::item, QTreeWidget::item {{
        padding: 5px 6px; border-radius: {inner_radius}px;
    }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {accent}, stop:1 transparent);
        color: {primary}; border-left: 3px solid {primary};
    }}
    QListWidget::item:hover, QTreeWidget::item:hover {{
        background: rgba(255,255,255,0.07); color: {primary};
    }}

    QComboBox {{
        background: rgba(0,0,0,0.8); color: {primary}; border: {border}px solid {accent};
        padding: 5px 10px; border-radius: {radius}px; font-weight: bold;
    }}
    QComboBox:hover {{ border-color: {primary}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox::down-arrow {{
        image: none; border-left: 5px solid transparent;
        border-right: 5px solid transparent; border-top: 6px solid {primary};
        margin-right: 5px;
    }}
    QComboBox QAbstractItemView {{
        background: rgba(0,0,0,0.95); color: {primary}; border: {border}px solid {accent};
        selection-background-color: {accent}; selection-color: {primary};
    }}

    QSlider::groove:horizontal {{
        height: 6px; background: rgba(255,255,255,0.08);
        border: 1px solid {accent}; border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: qradialgradient(cx:0.5,cy:0.5,radius:0.5,
            fx:0.5,fy:0.5, stop:0 {primary}, stop:1 {accent});
        width: 18px; height: 18px; margin: -7px 0;
        border-radius: 9px; border: {border}px solid {primary};
    }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {primary}, stop:1 {accent});
        border-radius: 3px;
    }}

    QTabWidget::pane {{
        border: {border}px solid {accent}; border-radius: {radius}px;
        background: rgba(0,0,0,0.25); padding: 4px;
    }}
    QTabBar::tab {{
        background: rgba(0,0,0,0.85); color: #777; border: {border}px solid {accent};
        border-bottom: none; border-top-left-radius: {radius}px;
        border-top-right-radius: {radius}px; padding: 7px 14px;
        margin-right: 2px; font-weight: bold;
    }}
    QTabBar::tab:selected {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 {primary}, stop:1 {accent});
        color: #fff; border-color: {primary};
    }}
    QTabBar::tab:hover:!selected {{ color: {primary}; border-color: {primary}; }}

    QScrollBar:vertical {{
        background: rgba(0,0,0,0.4); width: 10px; border-radius: 5px;
    }}
    QScrollBar::handle:vertical {{
        background: {accent}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {primary}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{
        background: rgba(0,0,0,0.4); height: 10px; border-radius: 5px;
    }}
    QScrollBar::handle:horizontal {{
        background: {accent}; border-radius: 5px; min-width: 30px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    QCheckBox {{ color: #d8d8d8; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border: {border}px solid {accent};
        border-radius: {inner_radius}px; background: rgba(0,0,0,0.7);
    }}
    QCheckBox::indicator:checked {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 {primary}, stop:1 {accent});
        border-color: {primary};
    }}
    QSpinBox {{
        background: rgba(0,0,0,0.8); color: {primary}; border: {border}px solid {accent};
        padding: 4px 8px; border-radius: {radius}px; font-weight: bold;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background: {accent}; border: none; border-radius: 3px; width: 14px;
    }}

    QMenu {{
        background: rgba(0,0,0,0.95); color: {primary};
        border: {border}px solid {accent}; border-radius: {radius}px; padding: 4px;
    }}
    QMenu::item {{ padding: 7px 20px; border-radius: {inner_radius}px; }}
    QMenu::item:selected {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {accent}, stop:1 transparent);
    }}
    QDialog {{ background: {background}; }}
    QLineEdit {{
        background: rgba(0,0,0,0.7); color: {primary}; border: {border}px solid {accent};
        border-radius: {radius}px; padding: 5px 8px;
    }}
    """
