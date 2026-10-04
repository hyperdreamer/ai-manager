from typing import List, Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QCompleter, QWidget


class ModelComboBox(QComboBox):
    """Editable filterable combobox for model selection."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_models(self, models: List[str], current: Optional[str] = None) -> None:
        selected = current or self.currentText()
        self.clear()
        self.addItems(models)
        if selected:
            idx = self.findText(selected, Qt.MatchFlag.MatchExactly)
            if idx >= 0:
                self.setCurrentIndex(idx)
            else:
                self.setEditText(selected)
