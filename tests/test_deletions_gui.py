"""Exercise the delete/history/restore buttons in the real window."""
from datetime import date

import pytest

from factories import report


@pytest.mark.gui
def test_delete_and_restore_in_saved_reports_window(tmp_path):
    import gui_harness as h
    import fsr_deletions
    from tkinter import ttk
    try:
        g, answers = h.start_app(tmp_path)
    except Exception as error:
        pytest.skip(f'GUI cannot start here: {error}')
    try:
        store = g['data_store']()
        store.write_report(report('FSR-DELETE-1', 'Receiving', date(2026, 11, 22)), False)
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
        assert not [call for call in answers.calls if call[0] == 'showerror']
        dialog.destroy()
    finally:
        h.stop_app(g, answers)


