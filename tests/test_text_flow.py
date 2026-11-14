"""Live continuation, using invented text and isolated report profiles."""
import hashlib
from pathlib import Path

import pytest

import fsr_draft_form
import fsr_forms
import fsr_storage
from fsr_text_flow import line_spec, split_spans, validate


@pytest.mark.parametrize('text', [
    'a b c de fgh ij klmnop qr', 'abcdefghijklmno', ' leading  spaces  stay ',
    'one\ntwo\n\nthree\n', 'W' * 80, '', 'first\nsecond paragraph is longer',
])
def test_split_preserves_text_and_uses_fitting_word_boundaries(text):
    spans = split_spans(text, lambda value: len(value) / 7, 100)
    assert ''.join(text[a:b] for a, b in spans) == text.replace('\n', '')
    assert all(len(text[a:b]) <= 7 for a, b in spans)
    assert all(a <= b for a, b in spans)


def test_huge_paste_is_bounded_and_excess_is_retained():
    text = 'word ' * 100_000
    spans = split_spans(text, lambda value: len(value) / 40, 12)
    assert len(spans) == 13
    assert ''.join(text[a:b] for a, b in spans) == text


def test_template_geometry_is_read_only_and_uses_actual_fonts():
    paths = [fsr_forms.FORM_TEMPLATE, fsr_forms.CARGO_TEMPLATE,
             fsr_forms.UNIT_FORM_TEMPLATE, fsr_forms.INCIDENT_TEMPLATE]
    before = {path: hashlib.sha256(Path(path).read_bytes()).digest() for path in paths}
    _, goods, widths = line_spec(str(paths[0]), 1, 'A22')
    assert goods[:2] == ('Calibri', 12)
    assert len(widths) == 3
    _, remarks, widths = line_spec(str(paths[0]), 1, 'G21')
    assert remarks[:2] == ('Calibri', 12)
    assert len(widths) == 5
    _, incident, widths = line_spec(str(paths[3]), 1, 'A19')
    assert incident[:2] == ('Times New Roman', 11)
    assert len(widths) == 9
    assert before == {path: hashlib.sha256(Path(path).read_bytes()).digest() for path in paths}


@pytest.fixture(scope='module', params=['owner', 'user'])
def app(tmp_path_factory, request):
    import gui_harness as h
    g, answers = h.start_app(tmp_path_factory.mktemp('text_flow'),
                             extra_env={'FSR_EDITION': request.param})
    yield g, answers
    h.stop_app(g, answers)


@pytest.fixture
def form(app):
    g, answers = app
    g['new_report'](confirm=False)
    g['app_shell'].show('inspection')
    g['choose_condition']('Bad Order')
    g['set_entry'](g['SO_number_entry'], 'TEXT-FLOW-TEST')
    g['window'].update()
    answers.calls.clear()
    return g


def focus(g, section):
    tab, entry = {
        'goods': (g['documents_tab'], g['declared_goods_rows'][0][0]),
        'remarks': (g['documents_tab'], g['other_remarks_entries'][0]),
        'details': (g['findings_tab'], g['findings_entries'][0]),
        'incident': (g['incident_tab'], g['incident_cards'][0].rows[0]),
    }[section]
    g['notebook'].select(tab)
    g['window'].update()
    entry.focus_force()
    g['window'].update()
    assert entry.focus_get() is entry
    return entry, entry.text_flow


def paste(entry, text):
    entry.clipboard_clear()
    entry.clipboard_append(text)
    entry.event_generate('<<Paste>>')
    entry.update()


def text_rows(flow):
    return [row[0].get() for row in flow.rows()]


@pytest.mark.gui
@pytest.mark.parametrize('section', ['goods', 'remarks', 'details', 'incident'])
def test_paste_flows_every_section_and_draft_roundtrips(form, section):
    g = form
    entry, flow = focus(g, section)
    # Enough for several lines at each section's real printed width.
    text = 'Invented cargo inspection observations. ' * (4 if section == 'goods' else 12)
    paste(entry, text)
    values = text_rows(flow)
    assert sum(bool(value) for value in values) >= 2
    assert ''.join(values) == text
    assert not flow.error()
    assert g['window'].focus_get() is not entry
    assert g['report_state']['dirty']
    snapshot = fsr_draft_form.capture(g)
    assert fsr_draft_form.validate_snapshot(snapshot)
    fsr_draft_form.restore(g, snapshot)
    assert fsr_draft_form.capture(g) == snapshot


@pytest.mark.gui
def test_real_typing_moves_focus_and_keeps_every_character(form):
    g = form
    entry, flow = focus(g, 'goods')
    text = 'This is invented cargo description for checking automatic continuation ' * 2
    for char in text:
        target = g['window'].focus_get()
        name = 'space' if char == ' ' else char
        target.event_generate('<KeyPress>', keysym=name)
        target.event_generate('<KeyRelease>', keysym=name)
        g['window'].update()
    assert ''.join(text_rows(flow)) == text
    assert sum(bool(value) for value in text_rows(flow)) > 1
    assert not flow.error()


@pytest.mark.gui
def test_print_font_width_handles_wide_letters_and_keeps_loaded_text_raw(form):
    g = form
    entry, flow = focus(g, 'goods')
    wide = split_spans('W' * 100, lambda t: flow.metrics.measure('goods', t), 60)
    narrow = split_spans('i' * 100, lambda t: flow.metrics.measure('goods', t), 60)
    assert wide[0][1] < narrow[0][1]
    raw = 'Saved long text ' * 50
    fsr_draft_form.put(entry, raw)
    g['window'].update()
    assert entry.get() == raw  # Reports/drafts are not rewritten on load.
    assert flow.refresh()
    assert entry.get() == raw


@pytest.mark.gui
def test_width_failure_keeps_input_and_shows_inline_warning(form, monkeypatch):
    g = form
    entry, flow = focus(g, 'remarks')
    def unavailable(*_):
        raise ValueError('Test form geometry unavailable')
    monkeypatch.setattr(flow.metrics, 'measure', unavailable)
    paste(entry, 'All of this input must remain recoverable')
    assert entry.get() == 'All of this input must remain recoverable'
    assert 'could not be checked' in flow.warning.get()
    assert g['report_state']['dirty']


@pytest.mark.gui
def test_goods_continuation_preserves_quantity_packaging_and_following_item(form):
    g = form
    entry, flow = focus(g, 'goods')
    for widget, value in zip(g['declared_goods_rows'][0][1:], ['25', 'Crates']):
        fsr_draft_form.put(widget, value)
    for widget, value in zip(g['declared_goods_rows'][1], ['Other goods', '7', 'Boxes']):
        fsr_draft_form.put(widget, value)
    text = 'Lengthy invented description ' * 4
    paste(entry, text)
    rows = [[w.get() for w in row] for row in g['declared_goods_rows']]
    assert rows[0][1:] == ['25', 'Crates']
    later = next(i for i, row in enumerate(rows) if row[0] == 'Other goods')
    assert later >= 2
    assert rows[later] == ['Other goods', '7', 'Boxes']
    assert ''.join(row[0] for row in rows[:later]) == text
    assert all(row[1:] == ['', ''] for row in rows[1:later])


@pytest.mark.gui
def test_paste_paragraphs_enter_and_edit_in_the_middle(form):
    g = form
    entry, flow = focus(g, 'remarks')
    paste(entry, 'First line\nSecond line\nThird line')
    assert text_rows(flow)[:3] == ['First line', 'Second line', 'Third line']
    entry.focus_force()
    entry.icursor(5)
    paste(entry, ' inserted words ' * 6)
    assert 'Second line' in text_rows(flow)
    assert 'Third line' in text_rows(flow)
    assert 'First' in text_rows(flow)[0]
    active = g['window'].focus_get()
    active.event_generate('<KeyPress-Return>')
    g['window'].update()
    assert not flow.error()


@pytest.mark.gui
@pytest.mark.parametrize('section', ['goods', 'remarks', 'details', 'incident'])
def test_full_section_retains_overflow_and_save_refuses_without_losing_draft(form, section):
    g = form
    entry, flow = focus(g, section)
    flow.ensure(flow.limit)
    flow.watch()
    for i, row in enumerate(flow.rows()):
        fsr_draft_form.put(row[0], f'Existing line {i}')
    last = flow.rows()[-1][0]
    last.focus_force()
    last.icursor('end')
    original = last.get()
    added = ' excess text' * 100
    paste(last, added)
    assert last.get() == original + added
    assert flow.warning.get()
    before = fsr_draft_form.capture(g)
    assert g['save_report']() is False
    assert fsr_draft_form.capture(g) == before
    c = g['draft_controller']
    c.checkpoint()
    assert c.flush()
    assert c.draft_id


@pytest.mark.gui
def test_manually_added_rows_flow_and_new_report_cancels_pending_edit(form):
    g = form
    entry, flow = focus(g, 'remarks')
    g['other_remarks_frame'].set_row_count(6)
    last = g['other_remarks_entries'][-1]
    assert last.text_flow is flow
    last.focus_force()
    paste(last, 'Following invented words ' * 8)
    assert len(g['other_remarks_entries']) > 6
    assert not flow.error()
    flow.schedule(entry)
    g['new_report'](confirm=False)
    assert flow.pending is None
    g['window'].update()
    assert not any(text_rows(flow))


@pytest.mark.gui
def test_normal_save_printed_copies_and_reopen_keep_flowed_lines(form):
    g = form
    for section in ['goods', 'remarks', 'details', 'incident']:
        entry, _ = focus(g, section)
        paste(entry, 'Invented observations for printed row checking ' *
              (3 if section == 'goods' else 8))
    assert validate(g)
    data = g['collect_report_data']()
    control = data['control_no']
    assert g['save_report']() is True
    path = Path(g['excel_state']['path'])
    saved = fsr_storage.read_report(path, control)
    assert saved['declared_goods'] == data['declared_goods']
    assert saved['other_important_remarks'] == data['other_important_remarks']
    assert saved['findings_and_remarks'] == data['findings_and_remarks']
    assert saved['incident_reports'][0]['lines'] == data['incident_reports'][0]['lines']
    from openpyxl import load_workbook
    book = load_workbook(path.parent / 'Report Forms' / f'{control}_Report.xlsx')
    first = book['First Page']
    assert first['A22'].value == data['declared_goods'][0]['description']
    assert first['A22'].font.sz == 12
    assert first['G21'].font.sz == 12
    incident = next(book[name] for name in book.sheetnames if 'Incident' in name)
    assert incident['A18'].font.sz == incident['A19'].font.sz == 11
    book.close()
    g['new_report'](confirm=False)
    g['load_report_into_form'](control, 'excel')
    reopened = g['collect_report_data']()
    assert reopened['declared_goods'] == data['declared_goods']
    assert reopened['findings_and_remarks'] == data['findings_and_remarks']
