from PyQt6.QtCore import Qt, QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget


PROFIT_COLOR = "#008000"
LOSS_COLOR = "#C00000"

STYLESHEET = f"""
QLineEdit[output="true"] {{
    background: #f2f2f2;
    border: 1px solid #b4b4b4;
    border-radius: 2px;
    padding: 2px 5px;
}}
QLineEdit[tone="profit"] {{ color: {PROFIT_COLOR}; }}
QLineEdit[tone="loss"] {{ color: {LOSS_COLOR}; }}
QLabel[role="section"] {{ font-weight: bold; }}
QLabel[role="header"] {{ color: #555555; }}
"""


def tone_name(value) -> str:
    """Map a signed number to a color tone: >0 profit, <0 loss, else neutral."""
    if value is None:
        return "neutral"
    if value > 0:
        return "profit"
    if value < 0:
        return "loss"
    return "neutral"


class OutputField(QLineEdit):
    """Read-only, right-aligned, selectable result box (replaces the sunken tk Label)."""

    def __init__(self, default_tone: str = "neutral", min_chars: int = 8, parent=None):
        super().__init__(parent)
        self.default_tone = default_tone
        self._tone = None
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setProperty("output", True)
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * min_chars + 14)
        self.set_tone(default_tone)

    def set_tone(self, tone: str):
        if tone == self._tone:
            return
        self._tone = tone
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)


class TimeInput(QWidget):
    """HH : MM, digits only; jumps to minutes once the hour is unambiguous."""

    def __init__(self, parent=None):
        super().__init__(parent)
        digits = QRegularExpressionValidator(QRegularExpression(r"\d{0,2}"), self)

        self.hour = QLineEdit(self)
        self.minute = QLineEdit(self)
        for edit in (self.hour, self.minute):
            edit.setValidator(digits)
            edit.setMaxLength(2)
            edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            edit.setFixedWidth(edit.fontMetrics().averageCharWidth() * 4 + 14)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.hour)
        layout.addWidget(QLabel(":"))
        layout.addWidget(self.minute)

        self.hour.textEdited.connect(self._on_hour_edited)

    def _on_hour_edited(self, text: str):
        if len(text) >= 2 or (len(text) == 1 and int(text) >= 3):
            self.minute.setFocus()
            self.minute.selectAll()
