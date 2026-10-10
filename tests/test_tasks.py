import time


def _board():
    from core.tasks import TaskBoard
    return TaskBoard()


def test_lifecycle_and_visibility_delay():
    b = _board()
    events = []
    b.subscribe(lambda: events.append(1))
    tid = b.start("web_search", "news")
    assert b.snapshot() == []                      # too young to show (no flicker)
    assert b.snapshot(min_age=0)[0].name == "Searching the web"
    b.update(tid, progress=0.5, detail="half")
    b.finish(tid, ok=True)
    t = b.snapshot(min_age=0)[0]
    assert t.ok and t.progress == 1.0 and t.finished
    assert len(events) == 3


def test_finished_tasks_expire(monkeypatch):
    b = _board()
    tid = b.start("open_app")
    b.finish(tid)
    b._tasks[tid].finished -= b.LINGER_S + 1
    assert b.snapshot(min_age=0) == []
    assert tid not in b._tasks


def test_update_by_name_from_another_thread():
    import threading
    b = _board()
    tid = b.start("run_protocol", "work")
    th = threading.Thread(target=lambda: b.update(progress=0.25, detail="step 1/4", name="Protocol"))
    th.start(); th.join()
    assert b._tasks[tid].progress == 0.25 and b._tasks[tid].detail == "step 1/4"


def test_protocol_reports_step_progress(protocols_file):
    from core.tasks import get_board
    from plugins import protocols
    from conftest import FakePlayer
    board = get_board()
    tid = board.start("run_protocol", "night")
    seen = []
    p = FakePlayer(tools={"computer_settings": lambda a: (seen.append(board._tasks[tid].detail), "ok")[1]})
    protocols.time.sleep = lambda s: None
    protocols.run({"name": "night"}, player=p)
    assert seen[0].startswith("night · step 1/4")
    board.finish(tid)


def test_panel_shows_running_work(qapp):
    from ui.taskpanel import TaskPanel
    b = _board()
    panel = TaskPanel(b)
    panel.resize(320, 200)
    b.start("web_search", "x")
    b._tasks[1].started -= 2                       # running for 2 s
    panel.refresh()
    assert not panel.isHidden() and "1 RUNNING" in panel._title
    panel.grab()                                   # paints without error
    b.finish(1)
    b._tasks[1].finished -= b.LINGER_S + 1
    panel.refresh()
    assert panel.isHidden()
