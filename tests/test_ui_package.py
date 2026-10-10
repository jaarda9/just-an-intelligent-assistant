"""Guards for the ui/ package split."""
import pytest

from conftest import ROOT


def test_public_entry_point():
    from ui import JarvisUI
    assert callable(JarvisUI)


def test_paths_resolve_to_project_root():
    from ui.base import BASE_DIR, CONFIG_DIR
    assert BASE_DIR == ROOT
    assert CONFIG_DIR == ROOT / "config"
    assert (CONFIG_DIR / "jarvis.ico").exists()


@pytest.mark.parametrize("mod", ["base", "metrics", "hud", "widgets",
                                 "overlays_setup", "overlays_data", "window"])
def test_every_module_imports(mod):
    import importlib
    importlib.import_module(f"ui.{mod}")


def test_main_window_builds(qapp, monkeypatch):
    """Construct the real window offscreen — exercises every panel's wiring."""
    import ui.hud
    monkeypatch.setattr(ui.hud, "_sfx", None)
    from ui.window import MainWindow
    win = MainWindow("face.png")
    assert win.hud is not None
    win.hud._tmr.stop()
    win.close()
    win.deleteLater()
