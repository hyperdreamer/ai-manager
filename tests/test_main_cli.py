"""Unit tests for CLI argument parsing in ``ai_manager.main``.

These tests never construct a ``QApplication``; they only exercise the pure
argument-parsing helper so unknown Qt flags can be verified to pass through
without raising.
"""

from ai_manager.main import parse_arguments


def test_parse_arguments_defaults_to_false():
    assert parse_arguments([]) is False


def test_parse_arguments_minimized_flag():
    assert parse_arguments(["--minimized"]) is True


def test_parse_arguments_tray_alias():
    assert parse_arguments(["--tray"]) is True


def test_parse_arguments_ignores_unknown_qt_args():
    # Qt platform selection must pass through parse_known_args without error.
    assert parse_arguments(["-platform", "offscreen"]) is False


def test_parse_arguments_minimized_alongside_qt_args():
    assert parse_arguments(["-platform", "offscreen", "--minimized"]) is True
