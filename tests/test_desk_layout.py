import pytest

from aque.desk import DeskApp


def test_effective_layout_auto_uses_width_breakpoint(tmp_aque_dir):
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    app._layout_mode = "auto"
    assert app._effective_layout(79) == "stacked"
    assert app._effective_layout(80) == "wide"
    assert app._effective_layout(120) == "wide"


def test_effective_layout_forced_ignores_width(tmp_aque_dir):
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    app._layout_mode = "wide"
    assert app._effective_layout(40) == "wide"
    app._layout_mode = "stacked"
    assert app._effective_layout(200) == "stacked"


def test_layout_mode_defaults_to_auto(tmp_aque_dir):
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    assert app._layout_mode == "auto"
