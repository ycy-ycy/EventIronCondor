from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QVBoxLayout,
)

from ..paths import SETTINGS_FILE
from ..providers import CAPABILITIES, CAPABILITY_LABELS, sources_for


class DataSourceDialog(QDialog):
    """Pick a data source per capability (price / option chain / rate)."""

    def __init__(self, current: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Data sources")
        self.setMinimumWidth(560)

        self.combos = {}
        self.descriptions = {}

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        row = 0
        for capability in CAPABILITIES:
            combo = QComboBox(self)
            for cls in sources_for(capability):
                combo.addItem(cls.label, cls)
            index = next(
                (i for i in range(combo.count()) if combo.itemData(i).key == current.get(capability)),
                0,
            )
            combo.setCurrentIndex(index)

            description = QLabel(self)
            description.setWordWrap(True)
            description.setProperty("role", "header")

            grid.addWidget(QLabel(CAPABILITY_LABELS[capability]), row, 0)
            grid.addWidget(combo, row, 1)
            grid.addWidget(description, row + 1, 1)
            row += 2

            self.combos[capability] = combo
            self.descriptions[capability] = description
            combo.currentIndexChanged.connect(lambda _i, c=capability: self._update_description(c))
            self._update_description(capability)

        note = QLabel(
            "To add a source, implement PriceSource / OptionSource / RateSource in ironcondor/providers/ "
            "and register() it in registry.py. Put API keys and other constructor arguments in "
            f"{SETTINGS_FILE.name} under provider_options."
        )
        note.setWordWrap(True)
        note.setProperty("role", "header")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addSpacing(8)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _update_description(self, capability: str):
        cls = self.combos[capability].currentData()
        self.descriptions[capability].setText(cls.description if cls else "")

    def selected_sources(self) -> dict:
        return {capability: combo.currentData().key for capability, combo in self.combos.items()}
