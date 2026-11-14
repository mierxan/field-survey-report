"""Draft behavior in the real form, using invented data in a temporary home."""

import pytest

import fsr_draft_form as form
import fsr_drafts as drafts
import fsr_drafts_ui as ui

pytestmark = pytest.mark.gui


@pytest.fixture
def app(tmp_path):
    import gui_harness as h
    g, answers = h.start_app(tmp_path)
    yield g, answers
    h.stop_app(g, answers)


def fill(g):
    g['new_report'](confirm=False)
    g['choose_condition']('Bad Order')
    g['set_entry'](g['SO_number_entry'], 'DRAFT-ONLY')
    g['set_entry'](g['location_combobox'], 'Invented yard')
    g['mark_dirty']()


def test_all_sections_roundtrip_without_validation(app):
    g, _ = app
    fill(g)
    c = g['draft_controller']
    c.muted = True
    try:
        for widgets in [g['schedule_entries'], g['transport_entries'], g['document_entries']]:
            for index, widget in enumerate(widgets.values()):
                form.put(widget, ' incomplete ' + str(index))
        form.put(g['inspection_date_entry'], 'half a date')
        for row in g['declared_goods_rows']:
            for widget in row:
                form.put(widget, ' raw 1, ')
        g['other_remarks_frame'].set_row_count(7)
        form.put(g['other_remarks_entries'][5], '  remark after blanks  ')
        form.put(g['findings_entries'][3], ' later finding ')
        g['goods_type_vars'][next(iter(g['goods_type_vars']))].set(True)
        g['others_var'].set(False)
        form.put(g['others_entry'], 'hidden but unfinished')
        g['set_item_form']('Containerized')
        form.put(g['item_frames'][0].rows[2][0], '  container  ')
        g['set_item_form']('Loading')
        form.put(g['item_frames'][0].rows[3][0], '  truck  ')
        g['set_item_form']('Default')
        section = g['item_frames'][0]
        form.put(section.cell(section.rows[1], 'Quantity'), '1,')
        section.rows[1].hidden = {'Receiving Ref': 'TEST-REF'}
        section.rows[1].po_link = {'PO Line No.': '2'}
        g['add_incident_card'](copy_voyage=False, autofill=False)
        for card in g['incident_cards']:
            for key, widget in card.fields.items():
                form.put(widget, ' unfinished ' + key)
            form.put(card.rows[2], ' line after blanks ')
            card.touched = {'vessel', 'date'}
        before = form.capture(g)
        assert form.validate_snapshot(before)
        form.restore(g, before)
        assert form.capture(g) == before, drafts.differences(before, form.capture(g))
        g['set_item_form']('Containerized')
        assert g['item_frames'][0].rows[2][0].get() == '  container  '
    finally:
        c.muted = False


def test_unchanged_navigation_never_asks_and_dirty_cancel_preserves_form(app, monkeypatch):
    g, _ = app
    c = g['draft_controller']
    def forbidden(*_):
        pytest.fail('An unchanged form asked about unsaved changes')
    monkeypatch.setattr(ui, 'ask_choice', forbidden)
    g['new_report']()
    fill(g)
    monkeypatch.setattr(ui, 'ask_choice', lambda *_: 'cancel')
    assert not g['confirm_discard']('Test', 'Leave?')
    assert g['SO_number_entry'].get() == 'DRAFT-ONLY'
    assert c.draft_id is None


def test_keep_later_restore_and_discard(app, monkeypatch):
    g, _ = app
    fill(g)
    c = g['draft_controller']
    monkeypatch.setattr(ui, 'ask_choice', lambda *_: 'keep')
    assert g['confirm_discard']('New report', 'Leave?')
    saved = c.store.read(c.store.path(c.draft_id))
    g['new_report'](confirm=False)
    assert c.restore(saved)
    assert g['SO_number_entry'].get() == 'DRAFT-ONLY'
    assert g['report_state']['dirty']
    assert c.flush()
    monkeypatch.setattr(ui, 'ask_choice', lambda *_: 'discard')
    assert g['confirm_discard']('Close', 'Leave?')
    assert not c.store.path(saved['id']).exists()


def test_successful_checkpoints_only_update_small_status(app):
    g, answers = app
    fill(g)
    c = g['draft_controller']
    before = len(answers.calls)
    assert c.flush()
    c.poll()
    assert c.status.get().startswith('Draft saved ')
    assert len(answers.calls) == before


def test_save_removes_draft_but_failed_validation_keeps_it(app):
    g, _ = app
    fill(g)
    c = g['draft_controller']
    assert c.flush()
    draft_id = c.draft_id
    # Bad Order without incident lines uses the normal confirmation.
    g['set_entry'](g['SO_number_entry'], '')
    assert not g['save_report']()
    assert c.store.path(draft_id).exists()
    g['set_entry'](g['SO_number_entry'], 'DRAFT-SAVED')
    g['schedule_entries']['activity'].set('Receiving')
    assert g['save_report']()
    assert not c.store.path(draft_id).exists()


def test_removed_account_cannot_restore_into_admin_account(app):
    g, _ = app
    fill(g)
    c = g['draft_controller']
    value = c.value()
    value['owner'] = 'f' * 32
    value['orphan'] = True
    with pytest.raises(drafts.DraftError, match='only be discarded'):
        c.restore(value)


def test_shutdown_simulation_keeps_draft_without_save_or_question(app, monkeypatch):
    g, answers = app
    fill(g)
    c = g['draft_controller']
    monkeypatch.setitem(g, 'save_report', lambda: pytest.fail('Shutdown saved a report'))
    before = len(answers.calls)
    assert c.shutdown(3)
    assert len(answers.calls) == before
    assert c.store.path(c.draft_id).exists()


def test_actual_four_button_dialog_cancel(app):
    g, _ = app
    actual = ui.ask_choice
    # The harness's auto-answer patch is restored temporarily to exercise the dialog.
    actual = app[1]._draft_choice
    def cancel():
        for child in g['window'].winfo_children():
            if child.winfo_class() == 'Toplevel' and child.title() == 'Real four choices':
                labels = [w.cget('text') for frame in child.winfo_children() for w in frame.winfo_children() if w.winfo_class() == 'TButton']
                assert labels == ['Save', 'Keep as draft', 'Discard', 'Cancel']
                child.event_generate('<Escape>')
                # Destroy acts as the dialog's default Cancel too.
                child.destroy()
    g['window'].after(100, cancel)
    assert actual(g['window'], 'Real four choices') == 'cancel'


def test_saved_report_conflict_is_reviewed_before_restore_and_before_save(app, monkeypatch):
    from datetime import date
    from factories import report
    g, _ = app
    store = g['data_store']()
    original = report('FSR-TEST-202611-0001', 'Receiving', date(2026, 11, 14))
    store.write_report(original, False)
    g['load_report_into_form'](original['control_no'])
    g['set_entry'](g['SO_number_entry'], 'UNSAVED-DRAFT')
    c = g['draft_controller']
    assert c.flush()
    saved = c.store.read(c.store.path(c.draft_id))
    g['new_report'](confirm=False)
    newer = store.read_report(original['control_no'])
    newer['general_information']['so_number'] = 'IMPORTED-VERSION'
    store.write_report(newer, True)
    seen = []
    def no(window, changes, **kwargs):
        seen.extend(changes)
        return False
    monkeypatch.setattr(ui, 'show_differences', no)
    assert not c.restore(saved)
    assert any('so_number' in name for name, _, _ in seen)
    assert store.read_report(original['control_no'])['general_information']['so_number'] == 'IMPORTED-VERSION'
    monkeypatch.setattr(ui, 'show_differences', lambda *a, **k: True)
    assert c.restore(saved)
    assert g['SO_number_entry'].get() == 'UNSAVED-DRAFT'
    newer['general_information']['so_number'] = 'CHANGED-AGAIN'
    store.write_report(newer, True)
    seen.clear()
    monkeypatch.setattr(ui, 'show_differences', no)
    assert not g['save_report']()
    assert seen and c.store.path(saved['id']).exists()
    assert store.read_report(original['control_no'])['general_information']['so_number'] == 'CHANGED-AGAIN'


def test_checkpoint_does_not_use_control_number_or_enter_exports(app, monkeypatch):
    g, _ = app
    fill(g)
    c = g['draft_controller']
    store = g['data_store']()
    before = store.control_numbers()
    assert c.flush()
    assert store.control_numbers() == before
    assert not store.list_reports()
    assert not store.read_all_reports()
    assert not store.search_index()
    assert c.store.read(c.store.path(c.draft_id))['control'] == ''


def test_actual_idle_checkpoint_and_context_menu_edit_trace(app):
    import time
    g, answers = app
    c = g['draft_controller']
    c.schedule.idle = .05
    # StringVar tracing must catch changes even without a KeyRelease event.
    g['set_entry'](g['SO_number_entry'], 'PASTED-WITHOUT-KEY')
    assert g['report_state']['dirty']
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        g['window'].update()
        if c.draft_id and c.store.path(c.draft_id).exists():
            break
        time.sleep(.02)
    assert c.store.read(c.store.path(c.draft_id))['form']['simple']['SO_number_entry'] == 'PASTED-WITHOUT-KEY'
    assert not [call for call in answers.calls if call[1] == 'Draft not saved']


def test_failure_notice_is_once_and_normal_save_still_works(app, monkeypatch):
    g, answers = app
    fill(g)
    c = g['draft_controller']
    def fail(*a, **k):
        raise OSError('invented local draft disk failure')
    monkeypatch.setattr(c.store, 'write', fail)
    assert not c.flush()
    assert not c.flush()
    assert len([call for call in answers.calls if call[1] == 'Draft not saved']) == 1
    g['schedule_entries']['activity'].set('Receiving')
    assert g['save_report']()
    assert g['data_store']().list_reports()


def test_admin_orphan_window_disables_restore_and_allows_discard(app):
    g, _ = app
    c = g['draft_controller']
    item = c.value()
    item['owner'] = 'e' * 32
    item['session'], item['pid'] = '', 0
    other = drafts.Store(c.store.root, c.scope, item['owner'])
    other.write(item)
    c.show()
    dialog = c.dialog
    assert dialog is not None and dialog.title() == 'Unfinished work found'
    tree = next(w for w in dialog.winfo_children() if w.winfo_class() == 'Treeview')
    row = tree.get_children()[0]
    assert 'Removed account' in tree.item(row, 'values')[3]
    tree.selection_set(row)
    g['window'].update()
    buttons = {w.cget('text'): w for frame in dialog.winfo_children() for w in frame.winfo_children() if w.winfo_class() == 'TButton'}
    assert str(buttons['Restore'].cget('state')) == 'disabled'
    assert str(buttons['Discard'].cget('state')) == 'normal'
    buttons['Discard'].invoke()
    assert not other.path(item['id']).exists()
    assert not g['report_state']['editing']
    dialog.destroy()


def test_windows_session_messages_checkpoint_without_closing_or_prompting(app):
    import sys
    if sys.platform != 'win32':
        pytest.skip('Windows session message integration')
    g, answers = app
    fill(g)
    c = g['draft_controller']
    before = len(answers.calls)
    assert c.hook is not None and c.hook.callback is not None
    assert c.hook.callback(c.hook.hwnd, 0x11, 0, 0) == 1
    assert c.hook.callback(c.hook.hwnd, 0x16, 1, 0x80000000) == 0
    assert c.store.path(c.draft_id).exists()
    assert g['window'].winfo_exists()
    assert len(answers.calls) == before


def test_po_link_and_uncommitted_quantity_roundtrip(app):
    import test_withdrawal_gui as wdtest
    from fsr_withdrawal_ui import is_linked
    g, _ = app
    wdtest.write_receiving(g)
    wdtest.begin(g)
    panel = wdtest.pick(g)
    section, row = panel.linked_lines()[0]
    panel.edit_quantity(section, row)
    form.put(section.cell(row, 'Quantity'), '1,')
    c = g['draft_controller']
    before = form.capture(g)
    assert c.flush()
    saved = c.store.read(c.store.path(c.draft_id))
    g['new_report'](confirm=False)
    assert c.restore(saved)
    assert form.capture(g) == before
    section, row = panel.linked_lines()[0]
    assert is_linked(row)
    assert section.cell(row, 'Quantity').get() == '1,'
    assert panel.editing is not None


def test_mysql_change_is_reviewed_on_restore_but_autosave_does_not_contact_it(app, monkeypatch):
    from datetime import date
    from factories import report
    from types import SimpleNamespace
    g, _ = app
    original = report('FSR-TEST-202611-0001', 'Receiving', date(2026, 11, 14))
    store = g['data_store']()
    store.write_report(original, False)
    g['load_report_into_form'](original['control_no'])
    g['set_entry'](g['SO_number_entry'], 'draft edit')
    c = g['draft_controller']
    called = []
    remote = store.read_report(original['control_no'])
    remote['general_information']['so_number'] = 'MYSQL-NEWER'
    def load(control):
        called.append(control)
        return remote
    monkeypatch.setitem(g, 'mysql_in_use', lambda: True)
    monkeypatch.setitem(g, 'db_mysql', SimpleNamespace(load_report=load))
    assert c.flush()
    assert not called
    saved = c.store.read(c.store.path(c.draft_id))
    g['new_report'](confirm=False)
    changes = []
    def refuse(window, diff, **kwargs):
        changes.extend(diff)
        return False
    monkeypatch.setattr(ui, 'show_differences', refuse)
    assert not c.restore(saved)
    assert called and any(name.startswith('MySQL') for name, _, _ in changes)
    assert store.read_report(original['control_no'])['general_information']['so_number'] == 'SO-1'


def test_form_remains_editable_while_checkpoint_disk_write_waits(app, monkeypatch):
    import threading
    g, _ = app
    fill(g)
    c = g['draft_controller']
    entered, release = threading.Event(), threading.Event()
    original = c.store.write
    def slow(value, commit=None):
        entered.set()
        assert release.wait(5)
        return original(value, commit)
    monkeypatch.setattr(c.store, 'write', slow)
    job = c.checkpoint()
    try:
        assert entered.wait(3)
        events = []
        g['window'].after(0, lambda: events.append('responsive'))
        g['set_entry'](g['SO_number_entry'], 'TYPING-CONTINUES')
        g['window'].update()
        assert events == ['responsive']
        assert g['SO_number_entry'].get() == 'TYPING-CONTINUES'
        assert not job[2].is_set()
    finally:
        release.set()
        assert job[2].wait(5)


def test_unchanged_saved_report_opens_another_without_question(app, monkeypatch):
    from datetime import date
    from factories import report
    g, _ = app
    store = g['data_store']()
    for number in ('0001', '0002'):
        store.write_report(report('FSR-TEST-202611-' + number, 'Receiving', date(2026, 11, 14)), False)
    g['load_report_into_form']('FSR-TEST-202611-0001')
    original = g['SO_number_entry'].get()
    # An unchanged value can still trigger a Tk variable write on focus-out.
    g['set_entry'](g['SO_number_entry'], original)
    def forbidden(*_):
        pytest.fail('An unchanged saved report asked about unsaved changes')
    monkeypatch.setattr(ui, 'ask_choice', forbidden)
    g['load_report_into_form']('FSR-TEST-202611-0002')
    assert g['control_entry'].get() == 'FSR-TEST-202611-0002'
    assert not g['report_state']['dirty']


def test_draft_follows_current_control_number_after_automatic_renumber(app):
    from datetime import date
    from factories import report
    g, _ = app
    store = g['data_store']()
    old, new = 'FSR-TEST-202611-0001', 'FSR-TEST-202611-0002'
    store.write_report(report(old, 'Receiving', date(2026, 11, 14)), False)
    g['load_report_into_form'](old)
    g['set_entry'](g['SO_number_entry'], 'UNSAVED-AFTER-RENUMBER')
    store.renumber(old, new)
    g['set_control_number'](new)
    c = g['draft_controller']
    c.retarget(old, new, store.read_report(new), store.saved_stamp(new, False))
    assert c.flush()
    saved = c.store.read(c.store.path(c.draft_id))
    assert saved['control'] == new
    assert saved['form']['simple']['SO_number_entry'] == 'UNSAVED-AFTER-RENUMBER'
    assert store.read_report(new)['general_information']['so_number'] == 'SO-1'


def test_discard_is_not_recreated_during_close_wait_but_new_edits_are_protected(app, monkeypatch):
    g, _ = app
    fill(g)
    c = g['draft_controller']
    assert c.flush()
    old = c.draft_id
    monkeypatch.setattr(ui, 'ask_choice', lambda *_: 'discard')
    assert c.leave('Close')
    assert c.suspended and c.draft_id is None
    c.poll()  # The existing export/MySQL closing window still runs the Tk loop.
    assert c.shutdown()
    assert not c.store.path(old).exists()
    assert not list(c.store.root.glob('*.draft.json'))
    # If a navigation failure left the old form visible, new typing starts new work.
    g['set_entry'](g['SO_number_entry'], 'NEW-EDIT-AFTER-DISCARD')
    assert not c.suspended
    assert c.flush()
    assert c.draft_id != old and c.store.path(c.draft_id).exists()
