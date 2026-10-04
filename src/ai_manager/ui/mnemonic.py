"""Ampersand/mnemonic escaping for Qt widget text.

Several Qt widgets interpret ``&`` as a keyboard-mnemonic marker and *remove*
it from the laid-out glyphs (underlining the following character instead):

* ``QAbstractButton`` (``QPushButton``, ``QToolButton``, ``QCheckBox``,
  ``QRadioButton``), via ``setText``
* ``QGroupBox`` title, via ``setTitle``
* ``QTabWidget`` tab labels, via ``setTabText``
* ``QMenu``/``QAction`` text, via ``setText``/``addAction``
* ``QLabel`` *that has a buddy*, via ``setBuddy``

Widgets that render ``&`` literally and must **not** be escaped: ``QLabel``
without a buddy, ``QLineEdit``, ``QComboBox`` items, ``QListWidget`` items,
``QMessageBox`` body text and window titles (``setWindowTitle``/``QMessageBox``
title), which are drawn by the window manager.

Doubling the ampersand is the documented way to make Qt draw a literal ``&``.
Use :func:`escape_mnemonic` for any *dynamic* string (model names, provider
error text, paths, user input) that is fed to one of the widgets above.
Static literals may be written as ``"Save && Apply"`` directly.
"""


def escape_mnemonic(text: str) -> str:
    """Return ``text`` with every ``&`` doubled for Qt mnemonic widgets.

    Passing the result to, e.g., ``QToolButton.setText`` makes Qt render the
    text exactly as given instead of swallowing ``&`` as a mnemonic marker.
    """
    return text.replace("&", "&&")
