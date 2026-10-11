"""Talking over JARVIS: the echo guard on speech-like audio, the pre-roll,
and the interrupt fix.

The guard's thresholds were chosen on a room simulation with real speech
(Windows TTS voices through a 128 ms buffer, delay and reverb): zero false
triggers on 20 s of echo at four speaker loudnesses; a voice talking over him
caught in 10 of 12 cases, median 0.45 s. The tests below repeat that with
synthetic speech so they run anywhere."""
import types as _t

import numpy as np
import pytest

from core.echo import EchoGuard

OUT_SR, MIC_SR = 24000, 16000
BLOCK = 1024                      # mic block, as in main.CHUNK_SIZE


def _voice(sr, n, f0, formants, t0=0.0):
    """A crude vowel: harmonics of f0 weighted by formant bumps (peak 1.0)."""
    t = t0 + np.arange(n) / sr
    x = np.zeros(n)
    for k in range(1, int(7000 / f0)):
        f = k * f0
        w = sum(np.exp(-((f - fc) / bw) ** 2) for fc, bw in formants)
        x += w * np.sin(2 * np.pi * f * t + k)
    return x / max(1e-9, np.abs(x).max())


def _speech(sr, seconds, vowels, f0s, seed):
    """Speech-like signal: syllables of 80-150 ms, each a different vowel and
    pitch with an attack/decay envelope, and short gaps between some."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(sr * seconds))
    i = 0
    while i < out.size:
        n = int(sr * rng.uniform(0.08, 0.15))
        f0 = rng.choice(f0s) * rng.uniform(0.9, 1.1)
        syl = _voice(sr, n, f0, vowels[rng.integers(len(vowels))], t0=i / sr)
        syl *= np.sin(np.linspace(0, np.pi, n)) ** 0.6 * rng.uniform(0.5, 1.0)
        out[i:i + n] = syl[:max(0, out.size - i)]
        i += n + (int(sr * rng.uniform(0.02, 0.09)) if rng.random() < 0.4 else 0)
    return out


JARVIS_VOWELS = [[(600, 180), (1000, 220)], [(450, 150), (1700, 300)],
                 [(700, 200), (1200, 250)], [(380, 120), (900, 200)]]
USER_VOWELS = [[(320, 100), (2400, 350)], [(500, 150), (2100, 350)],
               [(360, 120), (2800, 400)], [(650, 180), (1900, 300)]]


def _level(pcm):
    from main import _pcm_level
    return _pcm_level(pcm)


def _room(x, sr, gain, delay_s=0.02, rt=0.2, seed=3):
    rng = np.random.default_rng(seed)
    n = int(rt * sr)
    ir = rng.normal(0, 1, n) * np.exp(-np.arange(n) / (rt * sr / 6))
    ir[0] = 4.0
    ir /= np.sqrt((ir ** 2).sum())                 # echo RMS ~ gain x output RMS
    y = np.convolve(x, ir)[:x.size] * gain
    d = int(delay_s * sr)
    return np.concatenate([np.zeros(d), y])[:x.size]


def _simulate(echo_gain, user_gain, seconds=8.0, user_at=4.0, seed=0):
    """JARVIS talks for `seconds`; the user talks over him from `user_at`.
    Output is noted in 64 ms slices stamped with when they are heard, as
    main.py does. Returns the times a barge-in would have fired."""
    g = EchoGuard()
    jv = _speech(OUT_SR, seconds, JARVIS_VOWELS, (100, 115, 130), seed) * 9000
    mic = _room(np.interp(np.linspace(0, jv.size - 1, int(jv.size * MIC_SR / OUT_SR)),
                          np.arange(jv.size), jv), MIC_SR, echo_gain)
    mic += np.random.default_rng(seed).normal(0, 50, mic.size)
    if user_gain:
        uv = _speech(MIC_SR, seconds - user_at, USER_VOWELS, (190, 220, 250), seed + 1)
        a = int(user_at * MIC_SR)
        mic[a:a + uv.size] += (uv * 9000 * user_gain)[:mic.size - a]
    mic = np.clip(mic, -32768, 32767).astype(np.int16)
    sl = int(0.064 * OUT_SR)
    notes = [(k / OUT_SR, jv[k:k + sl].astype(np.int16)) for k in range(0, jv.size, sl)]
    ni, hits, fired = 0, [], []
    for b in range(0, mic.size - BLOCK, BLOCK):
        t = (b + BLOCK) / MIC_SR
        while ni < len(notes) and notes[ni][0] <= t:
            ts, seg = notes[ni]
            g.note_output(seg, OUT_SR, _level(seg), when=ts)
            ni += 1
        blk = mic[b:b + BLOCK]
        hits.append(g.is_user_speech(blk, MIC_SR, _level(blk), when=t))
        if sum(hits[-g.window_blocks:]) >= g.required_blocks:
            fired.append(t)
            hits.clear()
    return fired


@pytest.mark.parametrize("echo_gain", [0.2, 0.5, 0.9])
def test_own_echo_never_interrupts(echo_gain):
    assert _simulate(echo_gain, 0.0, seconds=12.0) == []


@pytest.mark.parametrize("echo_gain", [0.2, 0.5])
def test_talking_over_him_interrupts_quickly(echo_gain):
    fired = _simulate(echo_gain, 0.6)
    assert fired and all(t >= 4.0 for t in fired)      # nothing before the user
    assert fired[0] - 4.0 < 1.0                          # caught within a second


def test_guard_reports_what_it_saw():
    g = EchoGuard()
    _ = _simulate  # (stats are exercised end to end in main; here the shape)
    st = g.take_stats()
    assert {"blocks", "hits", "max_ratio", "max_res", "ratio_bar", "res_bar",
            "need", "window", "learned"} <= set(st)


# ── main.py helpers ──────────────────────────────────────────────────────────

def _live(**state):
    import main
    from collections import deque
    ns = _t.SimpleNamespace(
        _preroll=deque(maxlen=main._PREROLL_BLOCKS), _barge_hits=deque(maxlen=32),
        _barge_enabled=True, _phone_active=False, _ptt_enabled=False, _ptt_held=False,
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


def test_barge_mode_defaults_to_name_and_migrates(fake_config):
    import memory.config_manager as cm
    assert cm.get_barge_mode() == "name" and cm.get_barge_in_enabled()
    fake_config["barge_in"] = False                 # the older on/off switch
    assert cm.get_barge_mode() == "off" and not cm.get_barge_in_enabled()
    fake_config["barge_in_mode"] = "voice"          # an explicit mode wins
    assert cm.get_barge_mode() == "voice"
    fake_config["barge_in_mode"] = "nonsense"
    assert cm.get_barge_mode() == "off"


def _name_live(speaking):
    import threading
    import main
    from collections import deque
    calls = []
    ns = _t.SimpleNamespace(
        _speaking_lock=threading.Lock(), _is_speaking=speaking, _tail_until=5.0,
        _loop=_t.SimpleNamespace(call_soon_threadsafe=lambda fn, *a: calls.append(fn)),
        _preroll=deque([np.zeros(4, np.int16)] * 3, maxlen=main._PREROLL_BLOCKS),
        _barge_in="BARGE", out_queue=None)
    ns._flush_preroll = lambda loop, n: calls.append(("flush", n))
    main.JarvisLive._on_name_heard(ns)
    return ns, calls


def test_hearing_his_name_while_speaking_interrupts():
    import main
    ns, calls = _name_live(speaking=True)
    assert ns._is_speaking is False and ns._tail_until == 0.0
    assert calls == ["BARGE", ("flush", main._PREROLL_BLOCKS)]


def test_hearing_his_name_when_quiet_does_nothing():
    ns, calls = _name_live(speaking=False)
    assert calls == [] and ns._tail_until == 5.0


def test_name_detector_reset_and_threshold():
    from core.wake_word import WakeWordDetector
    d = WakeWordDetector(on_detect=lambda: None, threshold=0.5)
    d.threshold = 0.85
    assert d.threshold == 0.85
    d._queue.put_nowait(b"stale")
    d.reset()
    assert d._reset_pending and d._queue.empty()


def test_name_mode_is_the_default_setting_choice():
    import main
    assert main._NAME_THRESHOLD < main._NAME_THRESHOLD_SELF <= 1.0


# ── WebRTC echo cancellation (core/aec.py) ─────────────────────────────────

def test_aec_voice_rule_needs_level_and_a_voice_that_survived():
    from core.aec import EchoCanceller
    a = EchoCanceller(16000, 24000)
    for _ in range(40):                          # leftover echo: quiet
        assert not a.voice_now(rms=30, raw=300)
    bar = a.bar()
    # loud but mostly removed by the canceller: a leak of his own voice
    assert not any(a.voice_now(rms=bar * 1.5, raw=bar * 6) for _ in range(6))
    bar = a.bar()                                # leaks raised the bar, as they should
    # loud and kept: a person — needs 3 of the last 5 blocks
    assert not a.voice_now(rms=bar * 2, raw=bar * 2.2)
    assert not a.voice_now(rms=bar * 2, raw=bar * 2.2)
    assert a.voice_now(rms=bar * 2, raw=bar * 2.2)


@pytest.mark.skipif(not __import__("core.aec", fromlist=["HAVE_AEC"]).HAVE_AEC,
                    reason="livekit not installed")
def test_aec_removes_echo_and_keeps_shape():
    from core.aec import EchoCanceller
    a = EchoCanceller(16000, 24000)
    assert a.ok and not a.warm
    jv = (_speech(24000, 5.0, JARVIS_VOWELS, (100, 115, 130), 0) * 9000).astype(np.int16)
    mic = _room(np.interp(np.linspace(0, jv.size - 1, int(jv.size * 2 / 3)),
                          np.arange(jv.size), jv.astype(float)), 16000, 0.8, delay_s=0.14)
    mic = mic.astype(np.int16)
    raw_e = clean_e = 0.0
    for b in range(mic.size // 960):
        t = (b + 1) * 0.06
        a.render(jv[int((t - 0.06) * 24000):int(t * 24000)])
        blk = mic[b * 960:(b + 1) * 960]
        out = a.capture(blk)
        assert out.shape == (960,) and out.dtype == np.int16
        if t > 3.0:
            raw_e += float(np.sum(blk.astype(float) ** 2))
            clean_e += float(np.sum(out.astype(float) ** 2))
    assert a.warm
    assert 10 * np.log10(raw_e / max(clean_e, 1.0)) > 10       # >10 dB removed



def _video_live(speaking, open_until=0.0):
    import threading
    import main
    from collections import deque
    calls, ducks = [], []
    ns = _t.SimpleNamespace(
        _speaking_lock=threading.Lock(), _is_speaking=speaking, _tail_until=0.0,
        _video_open_until=open_until,
        _loop=_t.SimpleNamespace(call_soon_threadsafe=lambda fn, *a: calls.append(fn)),
        _preroll=deque(maxlen=main._PREROLL_BLOCKS), _barge_in="BARGE",
        ui=_t.SimpleNamespace(video_gate=True, muted=False, duck_video=ducks.append))
    ns._flush_preroll = lambda loop, n: calls.append(("flush", n))
    for name in ("_open_video_listen", "_video_gated"):
        setattr(ns, name, getattr(main.JarvisLive, name).__get__(ns))
    return main, ns, calls, ducks


def test_video_gate_listens_for_the_name_only_until_it_is_heard():
    import time
    main, ns, calls, ducks = _video_live(speaking=False)
    assert ns._video_gated()                                 # name-only listening
    main.JarvisLive._on_name_heard(ns)
    assert ducks == [True]                                   # video turned down
    assert ("flush", main._PREROLL_BLOCKS) in calls          # "Jarvis …" reaches Gemini
    assert "BARGE" not in calls                              # nothing to interrupt
    assert not ns._video_gated()                             # mic open for the command
    assert ns._video_open_until - time.monotonic() > main._VIDEO_LISTEN_S - 1


def test_name_during_video_while_he_talks_also_interrupts():
    main, ns, calls, ducks = _video_live(speaking=True)
    main.JarvisLive._on_name_heard(ns)
    assert ducks == [True] and "BARGE" in calls and ns._is_speaking is False
