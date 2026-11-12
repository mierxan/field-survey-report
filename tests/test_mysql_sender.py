"""The background sender of MySQL rounds (fsr_mysql_sender): it runs in
its own thread, folds requests together, and hands every result - also an
error - to the window's thread."""
import threading

import fsr_mysql_sender


def test_sender_runs_in_the_background_and_reports_on_the_window():
    started, release = threading.Event(), threading.Event()
    told = []

    def work(**request):
        started.set()
        release.wait(5)
        return {"asked": request}

    sender = fsr_mysql_sender.Sender(work, told.append)
    sender.request(path="A")
    assert started.wait(5)
    assert not sender.idle()            # the window is free meanwhile
    sender.request(path="B", catch_up=True)     # folded into one more
    sender.request(path="C")
    release.set()
    assert sender.wait(5)
    sender.poll()
    assert [t["result"]["asked"] for t in told] == [
        {"path": "A"}, {"path": "C", "catch_up": True}]
    assert sender.idle()


def test_sender_reports_errors_instead_of_losing_them():
    told = []

    def work(**request):
        raise OSError("no server")

    sender = fsr_mysql_sender.Sender(work, told.append)
    sender.request()
    assert sender.wait(5)
    sender.poll()
    (item,) = told
    assert item["result"] is None and isinstance(item["error"], OSError)


def test_inline_sender_reports_at_once():
    told = []
    sender = fsr_mysql_sender.Sender(lambda **r: "done", told.append,
                                     inline=True)
    sender.request(x=1)
    assert [t["result"] for t in told] == ["done"] and sender.idle()
