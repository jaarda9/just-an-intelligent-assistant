"""Talking over JARVIS: the echo guard, the pre-roll, and the interrupt fix."""
import types as _t

import numpy as np
import pytest

from core.echo import EchoGuard

OUT_SR, MIC_SR = 24000, 16000
BLOCK = 1024                      # mic block, as in main.CHUNK_SIZE


def _voice(sr, n, f0, formants, t0=0.0, amp=6000.0):
    """A crude vowel: harmonics of f0 weighted by formant bumps."""
    t = t0 + np.arange(n) / sr
    x = np.zeros(n)
    for k in range(1, int(7000 / f0)):
        f = k * f0
        w = sum(np.exp(-((f - fc) / bw) ** 2) for fc, bw in formants)
        x += w * np.sin(2 * np.pi * f * t + k)
    x /= max(1e-9, np.abs(x).max())
    return (x * amp).astype(np.int16)


JARVIS = dict(f0=110, formants=[(600, 180), (1000, 220)])      # low, back vowel
USER = dict(f0=210, formants=[(350, 120), (2400, 400), (3200, 400)])   # high, front


def _level(pcm):
    from main import _pcm_level
    return _pcm_level(pcm)


def _run(guard, blocks, user_from=None, echo_gain=0.5, seed=0):
    """Play JARVIS for `blocks` mic blocks; from block `user_from` on, the user
    talks too. Returns the guard's verdict per block."""
    rng = np.random.default_rng(seed)
    verdicts = []
    for i in range(blocks):
        t = i * BLOCK / MIC_SR
        out = _voice(OUT_SR, int(BLOCK * OUT_SR / MIC_SR), t0=t, **JARVIS)
        guard.note_output(out, OUT_SR, _level(out), when=t)
        mic = _voice(MIC_SR, BLOCK, t0=t, **JARVIS).astype(np.float64) * echo_gain
        mic += rng.normal(0, 40, BLOCK)
        if user_from is not None and i >= user_from:
            mic += _voice(MIC_SR, BLOCK, t0=t, **USER).astype(np.float64) * 0.9
        mic = np.clip(mic, -32768, 32767).astype(np.int16)
        verdicts.append(guard.is_user_speech(mic, MIC_SR, _level(mic), when=t + 0.02))
    return verdicts


def test_own_echo_is_never_the_user():
    g = EchoGuard()
    assert not any(_run(g, 80))


def test_user_over_the_echo_triggers_a_barge_in():
    g = EchoGuard()
    v = _run(g, 60, user_from=30)
    assert not any(v[:30])                      # warm-up and echo only: silent
    run = best = 0
    for hit in v[30:]:
        run = run + 1 if hit else 0
        best = max(best, run)
    assert best >= g.required_blocks            # enough agreement to interrupt


# ── main.py helpers ──────────────────────────────────────────────────────────

def _live(**state):
    import main
    from collections import deque
    ns = _t.SimpleNamespace(
        _preroll=deque(maxlen=main._PREROLL_BLOCKS), _barge_run=0, _barge_enabled=True,
        _phone_active=False, _ptt_enabled=False, _ptt_held=False,
        ui=_t.SimpleNamespace(muted=False), out_queue=_t.SimpleNamespace(items=[]),
        **state)
    ns.out_queue.put_nowait = ns.out_queue.items.append
    for name in ("_barge_ready", "_flush_preroll"):
        setattr(ns, name, getattr(main.JarvisLive, name).__get__(ns))
    return main, ns


class _Loop:
    def call_soon_threadsafe(self, fn, *a):
        fn(*a)


def test_preroll_sends_newest_blocks_in_order():
    main, ns = _live()
    for i in range(10):
        ns._preroll.append(np.full(4, i, dtype=np.int16))
    ns._flush_preroll(_Loop(), 3)
    sent = [np.frombuffer(m["data"], dtype=np.int16)[0] for m in ns.out_queue.items]
    assert sent == [7, 8, 9] and len(ns._preroll) == 0


def test_barge_in_respects_mute_ptt_and_the_switch():
    main, ns = _live()
    assert ns._barge_ready()
    ns.ui.muted = True
    assert not ns._barge_ready()
    ns.ui.muted = False
    ns._ptt_enabled = True                      # push-to-talk, key not held
    assert not ns._barge_ready()
    ns._ptt_held = True
    assert ns._barge_ready()
    ns._barge_enabled = False
    assert not ns._barge_ready()


@pytest.mark.parametrize("generating,expect", [(True, True), (False, False)])
def test_interrupt_only_discards_a_reply_still_being_generated(generating, expect):
    """If the reply had already finished arriving, no turn_complete will come
    to clear the flag — setting it would swallow the answer to the next
    command."""
    import asyncio
    import main
    logs = []
    ns = _t.SimpleNamespace(
        _generating=generating, _interrupted=False, audio_in_queue=asyncio.Queue(),
        _visemes=_t.SimpleNamespace(reset=lambda: None), _play_cursor=1.0,
        _turn_done_event=None, ui=_t.SimpleNamespace(write_log=logs.append),
        set_speaking=lambda v: None)
    ns.audio_in_queue.put_nowait(b"x")
    main.JarvisLive.interrupt(ns)
    assert ns._interrupted is expect
    assert ns.audio_in_queue.empty()


def test_barge_switch_persists(fake_config):
    import memory.config_manager as cm
    assert cm.get_barge_in_enabled() is True
    fake_config["barge_in"] = False
    assert cm.get_barge_in_enabled() is False
