def test_readout_panel_gauges_and_verdict(player):
    from plugins import diagnostics
    out = diagnostics.run({}, player=player)
    assert player.panels and player.panels[0][0] == "DIAGNOSTICS"
    panel = player.panels[0][1]
    for label in ("CPU", "RAM", "NET", "UPTIME"):
        assert label in panel
    assert ("All systems nominal." in panel) or ("Attention required" in panel)
    gauges = player.gauges[0]
    assert [g[0] for g in gauges[:3]] == ["CPU", "GPU", "RAM"]
    for label, pct, warn, invert in gauges:
        assert pct is None or 0 <= pct <= 100
    assert "two-sentence status report" in out


def test_warning_thresholds_flag_attention(monkeypatch, player):
    from plugins import diagnostics
    monkeypatch.setattr(diagnostics, "get_system_status", lambda: {
        "cpu_percent": 97.0, "ram_percent": 40.0, "ram_used_gb": 4, "ram_total_gb": 16,
        "cpu_temp_c": None, "gpu_percent": None, "uptime": "1h 0m", "process_count": 100})
    diagnostics.run({}, player=player)
    assert "Attention required: CPU 97%" in player.panels[0][1]
