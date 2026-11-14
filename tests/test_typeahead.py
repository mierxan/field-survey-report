"""Shared picker behavior, using invented lists and real Tk key bindings."""
import ast
from pathlib import Path
import time

import pytest

from fsr_typeahead import Combobox, PrefixIndex


def test_prefix_index_casefold_order_and_no_fallback():
    index = PrefixIndex(['ABB PTE LTD', 'Kokusai Commerce Co. Ltd.', 'Super',
                         'sun', 'A Super', 'Suede'])
    assert index.matches('s') == ('Super', 'sun', 'Suede')
    assert index.matches('Su') == ('Super', 'sun', 'Suede')
    assert index.matches('Super') == ('Super',)
    assert index.matches('KOKUSAI') == ('Kokusai Commerce Co. Ltd.',)
    assert index.matches('absent') == ()
    assert index.matches('') == index.values


def test_large_list_index_reuses_normalized_keys():
    index = PrefixIndex([f'Company {i:06}' for i in range(100_000)])
    keys = index.keys
    started = time.monotonic()
    for _ in range(100):
        assert index.matches('Company 099999') == ('Company 099999',)
    assert index.keys is keys
    assert time.monotonic() - started < 2


def test_every_non_date_constructor_uses_shared_picker():
    root = Path(__file__).resolve().parents[1]
    files = ['field_survey_report.py', 'fsr_item_lists_ui.py', 'fsr_open_dialog.py',
             *[str(p.relative_to(root)) for p in (root / 'warehouse_ui').glob('*.py')]]
    ordinary = []
    for filename in files:
        tree = ast.parse((root / filename).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == 'Combobox':
                    ordinary.append(filename)
                    assert any(k.arg == 'postcommand' for k in node.keywords) is False
    assert ordinary == ['field_survey_report.py']  # recent-date constructor only


@pytest.fixture(scope='module', params=['owner', 'user'])
def app(tmp_path_factory, request):
    import gui_harness as harness
    g, answers = harness.start_app(tmp_path_factory.mktemp('typeahead_home'),
                                    extra_env={'FSR_EDITION': request.param})
    yield g
    harness.stop_app(g, answers)


@pytest.fixture
def combo(app):
    widget = Combobox(app['window'], values=['ABB PTE LTD',
        'Kokusai Commerce Co. Ltd.', 'Sun', 'Super A', 'Super B'])
    widget.place(x=20, y=50, width=260)
    app['window'].update()
    widget.focus_force()
    app['window'].update()
    yield widget
    widget.destroy()
    app['window'].update()


def key(widget, keysym):
    widget.event_generate('<KeyPress>', keysym=keysym)
    widget.event_generate('<KeyRelease>', keysym=keysym)
    widget.update()


def type_text(widget, text):
    for char in text:
        key(widget, char)


@pytest.mark.gui
def test_exact_kokusai_enter_regression_and_focus(combo):
    selected = []
    combo.bind('<<ComboboxSelected>>', lambda e: selected.append(combo.get()))
    type_text(combo, 'Kokusai')
    assert combo.get() == 'Kokusai'
    assert combo.focus_get() is combo
    assert combo.typeahead.items == ('Kokusai Commerce Co. Ltd.',)
    assert combo.typeahead.listbox.curselection() == (0,)
    key(combo, 'Return')
    assert combo.get() == 'Kokusai Commerce Co. Ltd.'
    assert selected == ['Kokusai Commerce Co. Ltd.']
    assert not combo.typeahead.opened


@pytest.mark.gui
def test_backspace_navigation_and_enter(combo):
    type_text(combo, 'Supe')
    assert combo.typeahead.items == ('Super A', 'Super B')
    key(combo, 'BackSpace')
    key(combo, 'BackSpace')
    assert combo.get() == 'Su'
    assert combo.typeahead.items == ('Sun', 'Super A', 'Super B')
    key(combo, 'Down')
    key(combo, 'Down')
    key(combo, 'Up')
    key(combo, 'Return')
    assert combo.get() == 'Super A'


@pytest.mark.gui
def test_escape_no_match_and_arrow_full_list(combo):
    type_text(combo, 'Kok')
    key(combo, 'Escape')
    assert combo.get() == 'Kok'
    assert not combo.typeahead.opened
    type_text(combo, 'z')
    assert combo.get() == 'Kokz'
    assert not combo.typeahead.opened
    key(combo, 'Return')
    assert combo.get() == 'Kokz'
    combo.event_generate('<Button-1>', x=combo.winfo_width() - 5, y=10)
    combo.update()
    assert combo.typeahead.items == tuple(combo.cget('values'))
    assert combo.get() == 'Kokz'


@pytest.mark.gui
def test_mouse_selects_filtered_item_without_focus_loss(combo):
    type_text(combo, 'Kok')
    box = combo.typeahead.listbox
    box.event_generate('<Button-1>', x=5, y=5)
    combo.update()
    assert combo.get() == 'Kokusai Commerce Co. Ltd.'
    assert combo.focus_get() is combo
    assert not combo.typeahead.opened


@pytest.mark.gui
def test_backing_list_refresh_and_native_popup_never_mismatch(combo):
    type_text(combo, 'Kok')
    combo.configure(values=['AAA', 'Kokusai Commerce Co. Ltd.', 'Kokusai Other'])
    assert combo.typeahead.items == ('Kokusai Commerce Co. Ltd.', 'Kokusai Other')
    key(combo, 'Down')
    key(combo, 'Return')
    assert combo.get() == 'Kokusai Other'


@pytest.mark.gui
def test_paste_delete_and_pending_enter(combo):
    combo.clipboard_clear()
    combo.clipboard_append('Kokusai')
    combo.event_generate('<<Paste>>')
    # Enter may arrive before the idle filter has run.
    combo.event_generate('<KeyPress-Return>')
    combo.update()
    assert combo.get() == 'Kokusai Commerce Co. Ltd.'
    combo.selection_range(0, 'end')
    key(combo, 'Delete')
    assert combo.get() == ''
    assert combo.typeahead.items == tuple(combo.cget('values'))


@pytest.mark.gui
def test_bounded_popup_reaches_end_and_preserves_source(combo):
    values = tuple(f'Supplier {i:06}' for i in range(20_000))
    combo.configure(values=values)
    type_text(combo, 'Supplier')
    picker = combo.typeahead
    assert len(picker.items) == 20_000
    assert picker.listbox.size() <= picker.PAGE
    picker.scroll_to('moveto', '1')
    key(combo, 'Return')
    assert combo.get() == values[-1]
    assert tuple(combo.cget('values')) == values


@pytest.mark.gui
def test_locked_and_disabled_boxes_never_change(combo):
    combo.set('Sun')
    for state in ('readonly', 'disabled'):
        combo.configure(state=state)
        type_text(combo, 'Kok')
        key(combo, 'Down')
        key(combo, 'Down')
        key(combo, 'F4')
        key(combo, 'Return')
        assert combo.get() == 'Sun'
        assert not combo.typeahead.opened
        native = str(combo) + '.popdown'
        assert not int(combo.tk.call('winfo', 'exists', native)) or not int(
            combo.tk.call('winfo', 'ismapped', native))


@pytest.mark.gui
def test_fixed_list_backspace_escape_and_focus_loss(app):
    combo = Combobox(app['window'], state='readonly', values=['Sun', 'Super'])
    combo.place(x=20, y=50)
    combo.set('Sun')
    combo.update()
    combo.focus_force()
    combo.update()
    try:
        type_text(combo, 'Supe')
        key(combo, 'BackSpace')
        key(combo, 'BackSpace')
        assert combo.typeahead.items == ('Sun', 'Super')
        assert combo.typeahead.query == 'Su'
        key(combo, 'Escape')
        assert combo.get() == 'Sun'
        assert not combo.typeahead.opened
        key(combo, 'F4')
        assert combo.typeahead.items == ('Sun', 'Super')
        app['window'].focus_force()
        combo.update()
        assert not combo.typeahead.opened
    finally:
        combo.destroy()


@pytest.mark.gui
def test_current_master_source_and_destroy_cleanup(app):
    values = ['First']
    root = app['window']
    combo = Combobox(root, values=values, values_provider=lambda: values)
    combo.place(x=20, y=50)
    combo.update()
    values.append('New supplier')  # Settings/import updates the shared source
    combo.focus_force()
    combo.update()
    type_text(combo, 'New')
    assert combo.typeahead.items == ('New supplier',)
    tag = combo.typeahead.tag
    commands = tuple(combo.typeahead.bindings)
    combo.destroy()
    root.update()
    assert not root.bind_class(tag)
    assert commands
    for command in commands:
        assert command not in root._tclCommands
        assert not root.tk.call('info', 'commands', command)


@pytest.mark.gui
def test_fixed_list_search_does_not_edit_or_dirty_until_selected(app):
    app['app_shell'].show('inspection')
    app['choose_condition']('Good Order')
    app['notebook'].select(app['general_tab'])
    app['window'].update()
    combo = app['transport_entries']['shipment_type']
    combo.focus_force()
    combo.update()
    combo.set('Local')
    assert combo.focus_get() is combo, (combo.focus_get(), combo.winfo_ismapped(), combo.cget('state'))
    app['set_dirty'](False)
    controller = app['draft_controller']
    revision = controller.revision
    type_text(combo, 'Imp')
    assert combo.get() == 'Local'
    assert combo.typeahead.items == ('Import',)
    assert controller.revision == revision
    key(combo, 'Return')
    assert combo.get() == 'Import'
    assert controller.revision > revision
    type_text(combo, 'unknown')
    assert not combo.typeahead.opened
    key(combo, 'Escape')
    assert combo.get() == 'Import'


@pytest.mark.gui
def test_real_supplier_master_commit_dates_and_draft_capture(app):
    import fsr_draft_form
    app['app_shell'].show('inspection')
    app['choose_condition']('Good Order')
    app['notebook'].select(app['general_tab'])
    app['window'].update()
    combo = app['supplier_combobox']
    source = app['master_data']['supplier_list']
    original = list(source)
    try:
        source[:] = ['ABB PTE LTD', 'Kokusai Commerce Co. Ltd.']
        combo.configure(values=source)
        combo.set('')
        combo.focus_force()
        combo.update()
        assert combo.focus_get() is combo, (combo.focus_get(), combo.winfo_ismapped(), combo.cget('state'))
        app['draft_controller'].watch()
        revision = app['draft_controller'].revision
        type_text(combo, 'Kokusai')
        key(combo, 'Return')
        assert combo.get() == source[1]
        assert app['draft_controller'].revision > revision
        snapshot = fsr_draft_form.capture(app)
        combo.set('')
        fsr_draft_form.restore(app, snapshot)
        assert combo.get() == source[1]
        for name in ('commenced_date', 'completion_date'):
            date_combo = app['schedule_entries'][name]
            assert not hasattr(date_combo, 'typeahead')
            assert str(date_combo.cget('state')) == 'normal'
            assert len(date_combo.cget('values')) == 9
    finally:
        source[:] = original
        combo.configure(values=source)
