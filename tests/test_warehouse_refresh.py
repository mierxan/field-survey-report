"""An outdated background read cannot repopulate the live view cache."""
from types import SimpleNamespace
from unittest.mock import Mock

from warehouse_ui.components import DataService


def test_invalidation_discards_inflight_snapshot(monkeypatch):
    import warehouse_ui.components as components
    from warehouse import store
    threads, polls, delivered = [], [], []

    class ControlledThread:
        def __init__(self, target, daemon):
            self.target = target
            self.alive = True
            threads.append(self)
        def start(self):
            pass
        def is_alive(self):
            return self.alive
        def finish(self):
            self.target()
            self.alive = False

    monkeypatch.setattr(components.threading, 'Thread', ControlledThread)
    loads = iter(['before delete', 'after delete'])
    monkeypatch.setattr(store, 'load_snapshot', lambda *args: next(loads))
    ctx = SimpleNamespace(window=SimpleNamespace(after=lambda ms, cb: polls.append(cb)),
                          excel_path=lambda: 'reports.xlsx', data_source=lambda: 'excel',
                          log=Mock())
    service = DataService(ctx)
    service.request(lambda snap, error: delivered.append(snap))
    threads[0].finish()  # Completed but its GUI callback has not run yet.
    service.invalidate()
    service.request(lambda snap, error: delivered.append(snap))
    polls.pop(0)()
    assert delivered == []
    assert service.snapshot is None
    threads[1].finish()
    polls.pop(0)()
    assert delivered == ['after delete', 'after delete']
    assert service.snapshot == 'after delete'
