def test_every_tool_is_listed_once_and_escaped():
    from ui.capabilities import build_html
    cat = [{"name": "open_app", "description": "Opens any application. More text."},
           {"name": "media_control", "description": "Controls <music> & video"},
           {"name": "brand_new_tool", "description": "Something a plugin added"}]
    out = build_html(cat)
    for n in ("open_app", "media_control", "brand_new_tool"):
        assert out.count(f">{n}<") == 1
    assert "&lt;music&gt; &amp; video" in out            # escaped, not parsed
    assert "More text" not in out                         # first sentence only
    assert "MORE" in out and "KEYS" in out and "Ctrl+Alt+J" in out


def test_long_descriptions_cut_at_a_word():
    from ui.capabilities import build_html
    out = build_html([{"name": "x", "description": "word " * 60}])
    assert "word…" in out and "wor…" not in out


def test_overlay_builds(qapp):
    from ui.capabilities import CapabilitiesOverlay
    ov = CapabilitiesOverlay([{"name": "open_app", "description": "Opens apps"}])
    assert "open_app" in ov._view.toPlainText()
    assert not ov.grab().isNull()
