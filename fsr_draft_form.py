"""Lossless UI checkpoints: no validation, commits, number allocation or I/O."""
import copy


def entry(widget):
    return widget.entry if hasattr(widget, 'entry') else widget


def put(widget, value):
    widget = entry(widget)
    state = str(widget.cget('state'))
    widget.configure(state='normal')
    widget.delete(0, 'end')
    widget.insert(0, value)
    widget.configure(state=state)


def item_sections(host):
    return [{'rows': [{'cells': {header: widget.get() for header, widget in zip(section.headers, row)},
                       'hidden': copy.deepcopy(row.hidden), 'po_link': copy.deepcopy(row.po_link),
                       'manual': [bool(getattr(w, 'manual_total', False)) for w in row]}
                      for row in section.rows]} for section in host['item_frames']]


def restore_items(host, sections):
    host['set_item_list_count'](max(1, len(sections)))
    import fsr_withdrawal_ui
    for section, saved in zip(host['item_frames'], sections):
        section.set_row_count(len(saved['rows']))
        for row, value in zip(section.rows, saved['rows']):
            fsr_withdrawal_ui.unlock_line(section, row)
            row.hidden = copy.deepcopy(value['hidden'])
            for header, widget in zip(section.headers, row):
                put(widget, value['cells'].get(header, ''))
            for widget, manual in zip(row, value.get('manual', [])):
                widget.manual_total = manual
            fsr_withdrawal_ui.restore_link(section, row, value['po_link'])
            row.po_link = copy.deepcopy(value['po_link'])
        section.update_subtotal()
        section.update_buttons()


def capture(host):
    simple = ['SO_number_entry', 'consignee_combobox', 'supplier_combobox',
              'brokerage_combobox', 'hauler_combobox', 'location_combobox',
              'destination_combobox', 'country_combobox']
    data = {'simple': {k: host[k].get() for k in simple},
            'date': entry(host['inspection_date_entry']).get() if 'inspection_date_entry' in host else host['get_inspection_date'](),
            'condition': host['condition_var'].get(),
            'goods': {k: v.get() for k, v in host['goods_type_vars'].items()},
            'others': host['others_var'].get(), 'others_text': host['others_entry'].get(),
            'item_form': host['item_form_var'].get(),
            'item_cache': copy.deepcopy(host.get('draft_item_cache', {})),
            'other_item_forms': copy.deepcopy(host['item_form_store']),
            'items': item_sections(host),
            'declared': [[w.get() for w in row] for row in host['declared_goods_rows']],
            'remarks': [w.get() for w in host['other_remarks_entries']],
            'findings': [w.get() for w in host['findings_entries']],
            'incidents': [{'fields': {k: entry(w).get() for k, w in c.fields.items()},
                           'touched': sorted(c.touched), 'rows': [w.get() for w in c.rows]}
                          for c in host['incident_cards']]}
    for name in ['schedule_entries', 'transport_entries', 'document_entries']:
        data[name] = {k: entry(w).get() for k, w in host[name].items()}
    panel = host['withdrawal_panel']
    editing = None
    if panel.editing:
        section, row, old = panel.editing
        if section in host['item_frames'] and row in section.rows:
            editing = [host['item_frames'].index(section), section.rows.index(row), old]
    data['withdrawal'] = {'po': panel.po_entry.get(), 'owned': panel.owned,
                          'activity': panel.activity_text, 'editing': editing}
    return data


def restore(host, data):
    if not validate_snapshot(data):
        raise ValueError('The draft form is damaged or has an unsupported format.')
    host['clear_form']()
    host['set_item_form'](data['item_form'])
    for name, value in data['simple'].items():
        put(host[name], value)
    # Set condition before incident details: Good Order normally clears them.
    host['set_condition'](data['condition'])
    host['set_inspection_date'](data['date'])
    for name in ['schedule_entries', 'transport_entries', 'document_entries']:
        for key, value in data[name].items():
            put(host[name][key], value)
    for key, value in data['goods'].items():
        host['goods_type_vars'][key].set(value)
    host['others_var'].set(data['others'])
    put(host['others_entry'], data['others_text'])
    host['others_entry'].configure(state='normal' if data['others'] else 'disabled')
    for row, values in zip(host['declared_goods_rows'], data['declared']):
        for widget, value in zip(row, values):
            put(widget, value)
    for frame, entries, values in [('other_remarks_frame', 'other_remarks_entries', data['remarks']),
                                   ('findings_frame', 'findings_entries', data['findings'])]:
        host[frame].set_row_count(len(values))
        for widget, value in zip(host[entries], values):
            put(widget, value)
    restore_items(host, data['items'])
    host['item_form_store'].clear()
    host['item_form_store'].update(copy.deepcopy(data['other_item_forms']))
    host['draft_item_cache'] = copy.deepcopy(data['item_cache'])
    host['set_incident_reports']([{} for _ in data['incidents']])
    for card, saved in zip(host['incident_cards'], data['incidents']):
        while len(card.rows) < len(saved['rows']):
            card.add_line(notify_change=False)
        while len(card.rows) > len(saved['rows']):
            card.rows.pop().destroy()
        for key, value in saved['fields'].items():
            put(card.fields[key], value)
        for widget, value in zip(card.rows, saved['rows']):
            put(widget, value)
        card.touched = set(saved['touched'])
        card.refresh()
    host['show_incident_tab'](data['condition'] == host['CONDITION_BAD'])
    panel = host['withdrawal_panel']
    saved = data['withdrawal']
    put(panel.po_entry, saved['po'])
    panel.owned, panel.activity_text = saved['owned'], saved['activity']
    panel.sync()
    if saved['editing']:
        si, ri, old = saved['editing']
        section = host['item_frames'][si]
        row = section.rows[ri]
        panel.editing = (section, row, old)
        section.cell(row, 'Quantity').configure(state='normal')
    host['other_remarks_frame'].refresh_counter()
    host['findings_frame'].refresh_counter()


def validate_snapshot(value):
    """Reject malformed UI data before creating or changing any widgets."""
    def strings(mapping):
        return isinstance(mapping, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items())
    def text_rows(rows):
        return isinstance(rows, list) and all(isinstance(v, str) for v in rows)
    def sections(values):
        return isinstance(values, list) and bool(values) and all(
            isinstance(section, dict) and isinstance(section.get('rows'), list) and bool(section['rows']) and all(
                isinstance(row, dict) and strings(row.get('cells')) and isinstance(row.get('hidden'), dict)
                and isinstance(row.get('po_link'), dict) and isinstance(row.get('manual'), list)
                for row in section['rows']) for section in values)
    if not isinstance(value, dict):
        return False
    if not all(strings(value.get(k)) for k in ('simple', 'schedule_entries', 'transport_entries', 'document_entries')):
        return False
    if not all(isinstance(value.get(k), str) for k in ('date', 'condition', 'item_form', 'others_text')):
        return False
    if not isinstance(value.get('others'), bool) or not isinstance(value.get('goods'), dict):
        return False
    if not sections(value.get('items')) or not isinstance(value.get('item_cache'), dict) or not all(sections(v) for v in value['item_cache'].values()):
        return False
    if not isinstance(value.get('other_item_forms'), dict):
        return False
    if not isinstance(value.get('declared'), list) or not all(text_rows(r) and len(r) == 3 for r in value['declared']):
        return False
    if not all(text_rows(value.get(k)) for k in ('remarks', 'findings')):
        return False
    if not isinstance(value.get('incidents'), list) or not all(isinstance(c, dict) and strings(c.get('fields')) and text_rows(c.get('rows')) and text_rows(c.get('touched')) for c in value['incidents']):
        return False
    wd = value.get('withdrawal')
    if not isinstance(wd, dict) or not isinstance(wd.get('owned'), bool) or not isinstance(wd.get('po'), str) or not isinstance(wd.get('activity'), str):
        return False
    edit = wd.get('editing')
    if edit is not None:
        if not isinstance(edit, list) or len(edit) != 3 or not isinstance(edit[0], int) or not isinstance(edit[1], int) or not isinstance(edit[2], str):
            return False
        if not 0 <= edit[0] < len(value['items']) or not 0 <= edit[1] < len(value['items'][edit[0]]['rows']):
            return False
    return True
