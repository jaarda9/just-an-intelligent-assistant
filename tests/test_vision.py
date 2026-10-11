"""Vision: captures travel inside the tool result; the open camera streams.

Measured against the Live API (gemini-3.1-flash-live-preview): an image in
the function response is read in the same answer (3/3, no restart); a frame
sent as realtime video during a tool call is only seen a turn later; frames
streamed before a question are seen, the latest winning."""
import asyncio
import base64
import json
import types as _t

import pytest
from google.genai import types


class _WS:
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(json.loads(text))


def _jl(**kw):
    import main
    state = dict(session=_t.SimpleNamespace(_ws=_WS()), _vision_cam_active=False,
                 _vision_busy=True, _vision_close_pending=False, _pending_vision=None)
    state.update(kw)
    ns = _t.SimpleNamespace(**state)
    for name in ("_send_tool_responses", "_send_tool_responses_with_image",
                 "_vision_sent", "_flush_pending_vision"):
        setattr(ns, name, getattr(main.JarvisLive, name).__get__(ns))
    return ns


def _fr(name, i):
    return types.FunctionResponse(id=f"id{i}", name=name, response={"result": "ok"})


def test_capture_rides_inside_the_screen_process_result():
    ns = _jl()
    ns._pending_vision = (b"\xff\xd8jpeg", "image/jpeg", "what is this", "screen")
    asyncio.run(ns._send_tool_responses([_fr("open_app", 1), _fr("screen_process", 2)]))
    (msg,) = ns.session._ws.sent
    frs = msg["tool_response"]["functionResponses"]
    assert [f["name"] for f in frs] == ["open_app", "screen_process"]
    assert "parts" not in frs[0]
    part = frs[1]["parts"][0]["inlineData"]
    assert part["mimeType"] == "image/jpeg"
    assert base64.b64decode(part["data"]) == b"\xff\xd8jpeg"
    assert ns._pending_vision is None and ns._vision_busy is False   # nothing injected later


def test_camera_capture_keeps_busy_until_the_answer():
    ns = _jl(_vision_cam_active=True)
    ns._pending_vision = (b"jpg", "image/jpeg", "q", "camera")
    asyncio.run(ns._send_tool_responses([_fr("screen_process", 1)]))
    assert ns._vision_close_pending and not ns._vision_cam_active


def test_falls_back_to_a_separate_message_if_attaching_fails():
    sent = []

    async def send_tool_response(function_responses):
        sent.append(("tool", function_responses))

    async def send_client_content(**kw):
        sent.append(("content", kw))
    ns = _jl()
    ns.session = _t.SimpleNamespace(send_tool_response=send_tool_response,
                                    send_client_content=send_client_content)   # no _ws
    ns._pending_vision = (b"jpg", "image/jpeg", "q", "screen")
    asyncio.run(ns._send_tool_responses([_fr("screen_process", 1)]))
    assert [k for k, _ in sent] == ["tool", "content"]


def test_plain_results_use_the_sdk():
    sent = []

    async def send_tool_response(function_responses):
        sent.append(function_responses)
    ns = _jl()
    ns.session = _t.SimpleNamespace(send_tool_response=send_tool_response)
    asyncio.run(ns._send_tool_responses([_fr("open_app", 1)]))
    assert len(sent) == 1


@pytest.mark.parametrize("muted,asleep,frame,expect", [
    (False, False, b"jpg", 1), (True, False, b"jpg", 0),
    (False, True, b"jpg", 0), (False, False, None, 0)])
def test_open_camera_streams_frames(monkeypatch, muted, asleep, frame, expect):
    import main
    monkeypatch.setattr(main, "_CAMERA_FPS", 1000.0)
    sent = []

    async def send_realtime_input(video):
        sent.append(video)
        raise asyncio.CancelledError                # one frame is enough

    ns = _t.SimpleNamespace(
        session=_t.SimpleNamespace(send_realtime_input=send_realtime_input),
        ui=_t.SimpleNamespace(muted=muted, camera_snapshot=lambda: frame),
        _wake_enabled=asleep, _awake=not asleep)

    async def run():
        task = asyncio.ensure_future(main.JarvisLive._stream_camera(ns))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    asyncio.run(run())
    assert len(sent) == expect
    if expect:
        assert sent[0].mime_type == "image/jpeg"
