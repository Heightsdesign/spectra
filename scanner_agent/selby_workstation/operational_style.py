"""Restrained shared action semantics for operational Qt surfaces."""

from PySide6.QtCore import Qt

ACTION_COLORS = {
    "primary": ("#3478D4", "#1C304A", "#F0F5FC", "#243E60"),
    "success": ("#23855B", "#153529", "#E5F4EC", "#1B4736"),
    "warning": ("#C18A35", "#352B1E", "#F6DEB3", "#493A24"),
    "destructive": ("#B84B51", "#3B252A", "#FFECEF", "#512F35"),
}

BASE_STYLE = """
QWidget { background: #131820; color: #E4EAF3; font-size: 12px; }
QLabel { background: transparent; }
QLabel[visualRole="eyebrow"] { color: #91A0B5; font-size: 11px; font-weight: 600; }
QLabel[visualRole="heading"] { color: #F0F5FC; font-size: 15px; font-weight: 600; padding: 4px 0; }
QLabel[visualRole="muted"] { color: #AAB6C7; }
QLabel[visualRole="warning"] { color: #F6DEB3; background: #29231B; border: 1px solid #6F552D; border-radius: 5px; padding: 8px; }
QLabel[visualRole="success"] { color: #B9E8D2; background: #153529; border: 1px solid #23855B; border-radius: 5px; padding: 6px; }
QLabel[visualRole="stage"] { color: #BBD6FC; background: #1C304A; border: 1px solid #3478D4; border-radius: 5px; padding: 6px; }
QPushButton { background: #202630; color: #D4DBE7; border: 2px solid #384353; border-radius: 5px; padding: 8px 10px; font-weight: 600; }
QPushButton:hover:enabled { background: #2B3441; }
QLineEdit, QComboBox, QAbstractSpinBox { background: #1B222D; color: #E4EAF3; border: 1px solid #465366; border-radius: 4px; padding: 6px; min-height: 20px; }
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus { border: 1px solid #8DB8F3; }
QComboBox QAbstractItemView { background: #202A38; color: #E4EAF3; selection-background-color: #285587; selection-color: #FFFFFF; }
QTableWidget { background: #171E28; alternate-background-color: #1D2531; color: #E4EAF3; border: 1px solid #344052; gridline-color: #2C3747; selection-background-color: #285587; selection-color: #FFFFFF; }
QHeaderView::section { background: #232D3B; color: #BECADD; border: none; padding: 8px; }
QTabWidget::pane { border: 1px solid #344052; }
QTabBar::tab { background: #1B222D; color: #AAB6C7; padding: 9px 12px; border-bottom: 2px solid #303B4B; }
QTabBar::tab:selected { color: #E4EAF3; border-bottom: 2px solid #3478D4; background: #222F40; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #171E28; width: 12px; }
QScrollBar::handle:vertical { background: #465366; min-height: 24px; border-radius: 4px; }
QToolTip { background: #283343; color: #F0F5FC; border: 1px solid #63748B; padding: 6px; }
"""


def operational_stylesheet():
    rules = [BASE_STYLE]
    for role, (accent, background, foreground, hover) in ACTION_COLORS.items():
        selector = f'QPushButton[actionRole="{role}"]'
        rules.append(
            f"{selector}:enabled {{ background: {background}; color: {foreground}; border-color: {accent}; }}"
        )
        rules.append(f"{selector}:hover:enabled {{ background: {hover}; }}")
    # Disabled semantic actions always become neutral. They never retain a red,
    # green, blue or amber actionable appearance.
    rules.append(
        "QPushButton:disabled { background: #1A1F27; color: #7F8C9E; border: 2px solid #303945; }"
    )
    rules.append("QPushButton:focus:enabled { border: 2px solid #D7E8FF; }")
    return "\n".join(rules)


def apply_operational_style(widget):
    widget.setStyleSheet(operational_stylesheet())
    widget.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)


def visual_role(widget, role):
    if widget.property("visualRole") != role:
        widget.setProperty("visualRole", role)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


def action_state(button, enabled, explanation):
    button.setEnabled(bool(enabled))
    button.setToolTip(explanation)
    button.setAccessibleDescription(explanation)
