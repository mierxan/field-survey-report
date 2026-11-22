"""Exercise the delete/history/restore buttons in the real window."""
from datetime import date
import time

import pytest

from factories import report


@pytest.mark.gui
@pytest.mark.parametrize('activity', ['Receiving', 'Withdrawal'])
def test_delete_and_restore_in_saved_reports_window(tmp_path, activity):
    import gui_harness as h
    import fsr_deletions
    from tkinter import ttk
    try:
        g, answers = h.start_app(tmp_path)
    except Exception as error:
        pytest.skip(f'GUI cannot start here: {error}')
    try:
        store = g['data_store']()
        store.write_report(report('FSR-DELETE-1', activity, date(2026, 11, 22), condition='Bad Order'), False)
        shell = g['app_shell']
        shell.service.invalidate()
        def wait_for_snapshot(count):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                g['window'].update()
                snap = shell.service.snapshot
                if snap is not None and len(snap.transactions) == count:
                    return snap
                time.sleep(0.02)
            pytest.fail(f'Live views did not refresh to {count} transactions')
        wait_for_snapshot(1)
        for page in ('receiving', 'withdrawal', 'bad_order', 'dashboard'):
            shell.show(page)
            g['window'].update()
            assert len(shell.pages[page].snapshot.transactions) == 1
        incident = shell.pages['bad_order']
        assert len(incident.reports(incident.filters)[0]) == 1
        g['open_saved_report_dialog']()
        window = g['window']
        window.update()
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        dialog = next(w for w in window.winfo_children()
                      if callable(getattr(w, 'title', None)) and w.title() == 'Open Saved Report')
        widgets = list(descendants(dialog))
        tree = next(w for w in widgets if isinstance(w, ttk.Treeview))
        tree.selection_set('FSR-DELETE-1')
        next(w for w in widgets if w.winfo_class() == 'TButton' and w.cget('text') == 'Delete Selected').invoke()
        assert not store.list_reports()
        wait_for_snapshot(0)
        assert shell.pages['dashboard'].snapshot.transactions == []
        for page in ('receiving', 'withdrawal', 'bad_order'):
            shell.show(page)
            g['window'].update()
            assert shell.pages[page].snapshot.transactions == []
        errors = []
        def recover():
            try:
                history = next(w for w in descendants(window)
                               if callable(getattr(w, 'title', None)) and w.title().startswith('Deleted History'))
                children = list(descendants(history))
                listing = next(w for w in children if isinstance(w, ttk.Treeview))
                listing.selection_set(listing.get_children()[0])
                next(w for w in children if w.winfo_class() == 'TButton' and w.cget('text') == 'Restore Selected').invoke()
                history.destroy()
            except Exception as error:
                errors.append(error)
                for w in descendants(window):
                    if callable(getattr(w, 'title', None)) and w.title().startswith('Deleted History'):
                        w.destroy()
        window.after(100, recover)
        next(w for w in widgets if w.winfo_class() == 'TButton' and w.cget('text') == 'Deleted History').invoke()
        assert not errors
        assert store.list_reports()
        assert fsr_deletions.history(store.excel_path)[0]['state'] == 'restored'
        wait_for_snapshot(1)
        for page in ('receiving', 'withdrawal', 'bad_order', 'dashboard'):
            shell.show(page)
            g['window'].update()
            assert len(shell.pages[page].snapshot.transactions) == 1
        assert len(incident.reports(incident.filters)[0]) == 1
        assert not [call for call in answers.calls if call[0] == 'showerror']
        dialog.destroy()
    finally:
        h.stop_app(g, answers)


