"""Tk-only draft coordination and dialogs; the worker never touches widgets."""
import copy
import os
import queue
import time
import tkinter as tk
import uuid
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

import fsr_drafts as drafts
import fsr_draft_form as form
import fsr_windows_session


def ask_choice(window, title):
    dialog = tk.Toplevel(window)
    dialog.title(title)
    dialog.transient(window)
    answer = ['cancel']
    ttk.Label(dialog, text='This report has unsaved changes. What would you like to do?',
              padding=18).pack()
    bar = ttk.Frame(dialog, padding=12)
    bar.pack()
    def finish(value):
        answer[0] = value
        dialog.destroy()
    for label, value in [('Save', 'save'), ('Keep as draft', 'keep'), ('Discard', 'discard'), ('Cancel', 'cancel')]:
        ttk.Button(bar, text=label, command=lambda v=value: finish(v)).pack(side='left', padx=4)
    dialog.protocol('WM_DELETE_WINDOW', lambda: finish('cancel'))
    dialog.bind('<Escape>', lambda e: finish('cancel'))
    dialog.grab_set()
    window.wait_window(dialog)
    return answer[0]


def show_differences(window, changes, title='Saved report changed', detail=''):
    dialog = tk.Toplevel(window)
    dialog.title(title)
    dialog.transient(window)
    ttk.Label(dialog, text='The saved report changed since this draft began.\n'
              'Restoring fills the form only. Nothing saved is overwritten.\n' + detail,
              padding=12).pack(anchor='w')
    text = tk.Text(dialog, width=100, height=18, wrap='word')
    text.pack(padx=12)
    for name, before, after in changes:
        text.insert('end', f'{name}\n  Earlier: {before!s}\n  Now: {after!s}\n\n')
    text.configure(state='disabled')
    answer = [False]
    def finish(value):
        answer[0] = value
        dialog.destroy()
    bar = ttk.Frame(dialog, padding=12)
    bar.pack()
    ttk.Button(bar, text='Continue with my draft', command=lambda: finish(True)).pack(side='left', padx=5)
    ttk.Button(bar, text='Cancel', command=lambda: finish(False)).pack(side='left')
    dialog.protocol('WM_DELETE_WINDOW', lambda: finish(False))
    dialog.grab_set()
    window.wait_window(dialog)
    return answer[0]


class Controller:
    def __init__(self, host):
        self.h = host
        self.window = host['window']
        self.scope = drafts.scope_key(host['USERS_FILE'])
        self.owner = drafts.account_key(host['current_user'])
        root = drafts.folder() / 'Demo' if host['DEMO_MODE'] else drafts.folder()
        self.store = drafts.Store(root, self.scope, self.owner)
        self.writer = drafts.Writer(self.store)
        self.session = uuid.uuid4().hex
        self.process_started = fsr_windows_session.process_token(os.getpid())
        self.schedule = drafts.Schedule()
        self.muted = False
        self.stopped = False
        self.suspended = False
        self.revision = 0
        self.changed_text = drafts.now_text()
        self.draft_id = None
        self.baseline = {}
        self.base_control = ''
        self.restored = False
        self.source = 'excel'
        self.warning = False
        self.pending = None
        self.dialog = None
        self.variables = {}
        self.status = tk.StringVar(self.window)
        ttk.Label(host['status_label'].master, textvariable=self.status).pack(side='bottom', anchor='w')
        self.clean_form = form.capture(host)
        self.hook = None
        self.watch()
        self.timer = self.window.after(250, self.poll)
        self.window.bind('<Destroy>', self.destroyed, add='+')
        try:
            self.hook = fsr_windows_session.SessionHook(self.window, self.shutdown)
        except OSError:
            host['log'].exception('Windows shutdown checkpoint could not be attached')

    def destroyed(self, event):
        if event.widget is self.window:
            self.stop()

    def stop(self):
        if self.stopped:
            return
        self.stopped = True
        if self.hook:
            self.hook.close()
        try:
            self.window.after_cancel(self.timer)
        except tk.TclError:
            pass
        self.writer.close()
        for variable, trace in self.variables.values():
            try:
                variable.trace_remove('write', trace)
            except tk.TclError:
                pass
        self.variables.clear()

    def changed(self):
        if self.muted or self.stopped:
            return
        self.suspended = False
        self.revision += 1
        self.changed_text = drafts.now_text()
        self.schedule.changed(time.monotonic())

    def watch(self):
        # Trace changes, including context-menu paste/delete and checkbox clicks.
        widgets = []
        for root in [self.h['general_tab'], self.h['documents_tab'], self.h['items_tab'],
                     self.h['findings_tab'], self.h['incident_tab']]:
            stack = [root]
            while stack:
                widget = stack.pop()
                stack.extend(widget.winfo_children())
                if widget.winfo_class() in ('TEntry', 'TCombobox', 'Entry'):
                    widgets.append(widget)
        live = {str(w) for w in widgets}
        for key in list(self.variables):
            if not key.startswith('var:') and key not in live:
                variable, trace = self.variables.pop(key)
                try:
                    variable.trace_remove('write', trace)
                except tk.TclError:
                    pass
        for widget in widgets:
            key = str(widget)
            if key in self.variables or widget is self.h['control_entry']:
                continue
            old = widget.get()
            name = widget.cget('textvariable')
            variable = tk.StringVar(self.window, name=name) if name else tk.StringVar(self.window, value=old)
            if not name:
                widget.configure(textvariable=variable)
            def touched(*_, w=widget):
                if not self.muted and not self.stopped and w.winfo_exists():
                    self.h['mark_dirty']()
            trace = variable.trace_add('write', touched)
            self.variables[key] = variable, trace
        for key, variable in {**self.h['goods_type_vars'], 'others': self.h['others_var']}.items():
            key = 'var:' + key
            if key not in self.variables:
                trace = variable.trace_add('write', lambda *_: self.h['mark_dirty']() if not self.muted else None)
                self.variables[key] = variable, trace

    def poll(self):
        if self.stopped:
            return
        self.window.after_cancel(self.timer)
        self.watch()
        while True:
            try:
                draft_id, revision, error = self.writer.results.get_nowait()
            except queue.Empty:
                break
            if draft_id != self.draft_id:
                continue
            if error:
                self.failed(error)
            else:
                self.warning = False
                self.status.set('Draft saved ' + datetime.now().strftime('%H:%M:%S'))
                if revision == self.revision:
                    self.schedule.saved()
        if not self.suspended and self.h['report_state']['dirty'] and self.schedule.due(time.monotonic()):
            if self.pending is None or self.pending[2].is_set():
                self.checkpoint()
        self.timer = self.window.after(250, self.poll)

    def failed(self, error):
        self.status.set('Draft could not be saved')
        self.h['log'].error('Draft checkpoint failed: %s', error)
        if not self.warning:
            self.warning = True
            messagebox.showwarning('Draft not saved',
                'The draft could not be saved. Your last successful checkpoint is kept.\n'
                'Keep the program open and save normally if possible.\n' + str(error), parent=self.window)

    def value(self):
        if self.draft_id is None:
            self.draft_id = uuid.uuid4().hex
        return {'version': 1, 'id': self.draft_id, 'scope': self.scope, 'owner': self.owner,
                'owner_label': self.h['current_user'].get('initials', ''),
                'session': self.session, 'pid': os.getpid(), 'process_started': self.process_started, 'revision': self.revision,
                'changed': self.changed_text, 'workbook': str(self.h['excel_state']['path']),
                'editing': self.h['report_state']['editing'],
                'control': self.h['control_entry'].get().strip() if self.h['report_state']['editing'] else '',
                'source': self.source, 'baseline': copy.deepcopy(self.baseline),
                'form': form.capture(self.h)}

    def checkpoint(self):
        value = self.value()
        self.pending = self.writer.submit(value)
        return self.pending

    def flush(self, seconds=4., quiet=False):
        if self.suspended or not self.h['report_state']['dirty']:
            return True
        job = self.checkpoint()
        if not job[2].wait(seconds):
            if not quiet:
                self.failed(OSError('Draft writing has not finished yet.'))
            return False
        try:
            stored = self.store.read(self.store.path(self.draft_id))
            if stored['revision'] < job[1]['revision']:
                raise OSError('The latest draft revision was not written.')
            return True
        except (OSError, ValueError, KeyError) as error:
            if not quiet:
                self.failed(error)
            return False

    def shutdown(self, seconds=1.5):
        try:
            return self.flush(seconds, quiet=True)
        except Exception:
            self.h['log'].exception('Final draft checkpoint failed')
            return False

    def leave(self, title):
        if not self.h['report_state']['dirty']:
            return True
        if form.capture(self.h) == self.clean_form:
            self.writer.invalidate(self.draft_id, discard=True)
            self.draft_id = None
            self.schedule.saved()
            self.h['set_dirty'](False)
            self.status.set('')
            return True
        answer = ask_choice(self.window, title)
        if answer == 'save':
            return self.h['save_report']() and not self.h['report_state']['dirty']
        if answer == 'keep':
            self.suspended = False
            return self.flush()
        if answer == 'discard':
            try:
                self.writer.invalidate(self.draft_id, discard=True)
                self.draft_id = None
                self.schedule.saved()
                self.suspended = True
                self.status.set('')
            except OSError as error:
                self.failed(error)
                return False
            return True
        return False

    def reset(self, data=None, source='excel'):
        self.suspended = False
        self.writer.invalidate()
        self.draft_id = None
        self.revision = 0
        self.schedule.saved()
        self.status.set('')
        self.source = source
        self.restored = False
        self.base_control = data.get('control_no', '') if data else ''
        # No store read during ordinary Save; keep Phase 3's write/read counts.
        self.baseline = {'data': copy.deepcopy(data)} if data else {}
        if data:
            self.baseline['stamp'] = self.h['data_store']().saved_stamp(self.base_control, self.h['withdrawal_panel'].owned)
        self.clean_form = form.capture(self.h)
        self.muted = False

    def retarget(self, old, new, data, stamp):
        if self.base_control.casefold() != old.casefold():
            return
        self.base_control = new
        self.baseline = {'data': copy.deepcopy(data), 'stamp': stamp}
        if self.h['report_state']['dirty']:
            self.changed()
            self.checkpoint()

    def current(self, value):
        path = Path(value['workbook'])
        if str(path.resolve()) != str(Path(self.h['excel_state']['path']).resolve()):
            raise drafts.DraftError('This draft belongs to another workbook. Choose that workbook first, then open Unfinished work again.')
        store = self.h['data_store']()
        linked = value['form']['withdrawal']['owned'] or any(
            row['po_link'] for section in value['form']['items'] for row in section['rows'])
        state = drafts.saved_state(store, value['control'], bool(linked)) if value['editing'] else {}
        return state

    def compare(self, value):
        current = self.current(value)
        base = {k: v for k, v in value['baseline'].items() if k != 'remote'}
        changes = drafts.differences(drafts.comparable_state(base), drafts.comparable_state(current)) if value['editing'] else []
        detail = ''
        if value.get('editing') and self.h['mysql_in_use']() and not value['form']['withdrawal']['owned']:
            try:
                remote = self.h['db_mysql'].load_report(value['control'])
                import fsr_mysql_guard
                base = value['baseline'].get('remote', value['baseline'].get('data'))
                if base is not None and not fsr_mysql_guard.same_value(base, remote):
                    changes += drafts.differences(base, remote, 'MySQL')
                elif base is None:
                    detail = 'MySQL has no draft baseline; its version must be reviewed. The normal overwrite guard still applies.'
                    changes += [('MySQL review', 'Not checked when draft began', 'Review required')]
            except Exception:
                detail = 'MySQL could not be checked. No claim is made that its report is unchanged.'
                changes += [('MySQL check', 'Unknown', 'Unavailable')]
        if changes and not show_differences(self.window, changes, detail=detail):
            return None
        return current

    def restore(self, value):
        if value.get('orphan') or value['owner'] != self.owner or value.get('scope') != self.scope:
            raise drafts.DraftError('Removed-account drafts can only be discarded, not restored.')
        if value.get('handed_over'):
            raise drafts.DraftError('This draft was handed over to the next inspector, so it is continued there. It can only be discarded here.')
        if value.get('session') != self.session and fsr_windows_session.draft_is_running(value):
            raise drafts.DraftError('This draft is open in another running session. Close that session first.')
        current = self.compare(value)
        if current is None or not self.leave('Restore unfinished work'):
            return False
        self.writer.invalidate()
        self.muted = True
        try:
            form.restore(self.h, value['form'])
            self.h['report_state'].update(editing=value['editing'], dirty=True)
            # A new draft never owns its previously displayed candidate number.
            self.h['set_control_number'](value['control'] if value['editing'] else self.h['next_new_control_number']())
            self.draft_id, self.revision = value['id'], value['revision'] + 1
            self.changed_text = value['changed']
            self.base_control = value['control']
            self.baseline = current
            self.source = value.get('source', 'excel')
            self.restored = True
            self.schedule.changed(time.monotonic())
            self.h['update_status']()
            self.h['show_inspection_then'](lambda: None)()
        finally:
            self.muted = False
        return True

    def before_save(self):
        self.suspended = False
        expected = None
        if self.restored and self.h['report_state']['editing']:
            value = self.value()
            current = self.compare(value)
            if current is None:
                return False
            self.baseline = current
            expected = current.get('stamp')
        # An autosave failure must not prevent a normal validated report Save.
        self.flush()
        self.writer.invalidate()
        ref = {'root': str(self.store.root), 'scope': self.scope, 'owner': self.owner,
               'id': self.draft_id, 'revision': self.revision}
        if self.restored and self.h['report_state']['editing']:
            ref['expected_stamp'] = expected
            if '_revision' in self.baseline:
                ref['expected_revision'] = self.baseline['_revision']
            if '_file' in self.baseline:
                ref['expected_file'] = self.baseline['_file']
        return ref

    def saved(self, data, record, failed, journal):
        # Side-file failures without a journal have no durable repair copy.
        if journal is None and any(k in failed for k in ('incidents', 'item_forms')):
            self.h['report_state']['dirty'] = True
            return
        saved_revision = (record.get('draft') or {}).get('revision', self.revision)
        if self.revision > saved_revision:
            self.h['report_state']['dirty'] = True
            self.baseline = {'data': copy.deepcopy(data), 'stamp': record['stamp_planned']}
            self.base_control = data['control_no']
            self.checkpoint()
            return
        self.writer.invalidate(self.draft_id, discard=True)
        self.draft_id = None
        self.schedule.saved()
        self.status.set('')
        self.restored = False
        self.base_control = data['control_no']
        self.baseline = {'data': copy.deepcopy(data), 'stamp': record['stamp_planned']}
        self.clean_form = form.capture(self.h)

    def show(self, startup=False):
        if self.stopped:
            return
        if self.dialog is not None and self.dialog.winfo_exists():
            self.dialog.lift()
            return
        try:
            users = self.h['user_store'].list_users()
            active = [drafts.account_key(u) for u in users]
            values, damaged = self.store.list(active, admin=self.h['IS_OWNER'])
        except (OSError, ValueError) as error:
            self.failed(error)
            return
        if damaged:
            messagebox.showwarning('Damaged unfinished work',
                'Unreadable drafts were preserved aside; the program can continue.\n' + '\n'.join(damaged), parent=self.window)
        values = [v for v in values if not (v['owner'] == self.owner and v['id'] == self.draft_id and v.get('session') == self.session)]
        if not values:
            return
        if startup and all(v.get('handed_over') for v in values):
            return          # handed over: kept to look at, not to continue
        dialog = tk.Toplevel(self.window)
        self.dialog = dialog
        dialog.title('Unfinished work found')
        dialog.transient(self.window)
        tree = ttk.Treeview(dialog, columns=('report', 'so', 'changed', 'state'), show='headings', height=10)
        for name, label in [('report', 'Report'), ('so', 'SO number'), ('changed', 'Last change'), ('state', 'Status')]:
            tree.heading(name, text=label)
        tree.pack(fill='both', expand=True, padx=12, pady=12)
        for index, value in enumerate(values):
            state = 'Removed account — discard only' if value['orphan'] else 'Older than 30 days — review for discard' if value['old'] else ''
            if value.get('handed_over'):
                state = f"Handed over to {value['handed_over'].get('to') or 'the next inspector'} — discard only"
            elif value.get('received'):
                sender = value['received'].get('from') or {}
                state = f"Received from {sender.get('inspector') or sender.get('initials') or 'an inspector'}"
            if value.get('session') != self.session and fsr_windows_session.draft_is_running(value):
                state = 'Open in another session'
            tree.insert('', 'end', iid=str(index), values=(value['control'] or 'New report',
                value['form'].get('simple', {}).get('SO_number_entry', ''),
                datetime.fromisoformat(value['changed']).astimezone().strftime('%Y-%m-%d %H:%M:%S'), state))
        def selected():
            picked = tree.selection()
            return values[int(picked[0])] if picked else None
        def restore_selected():
            value = selected()
            if value is None:
                return
            try:
                if self.restore(value):
                    dialog.destroy()
            except (OSError, ValueError, KeyError, TypeError, tk.TclError) as error:
                messagebox.showwarning('Unfinished work', str(error), parent=dialog)
        def discard_selected():
            value = selected()
            if value and value.get('session') != self.session and fsr_windows_session.draft_is_running(value):
                return
            if value and messagebox.askyesno('Discard draft', 'Discard this unfinished work? Saved reports are not changed.', parent=dialog):
                try:
                    if value['owner'] == self.owner and value['id'] == self.draft_id:
                        self.writer.invalidate(self.draft_id)
                    self.store.discard(value['id'], value['owner'])
                    tree.delete(str(values.index(value)))
                    if value['owner'] == self.owner and value['id'] == self.draft_id:
                        self.h['new_report'](confirm=False)
                except OSError as error:
                    self.failed(error)
        bar = ttk.Frame(dialog, padding=12)
        bar.pack()
        restore_button = ttk.Button(bar, text='Restore', command=restore_selected)
        restore_button.pack(side='left', padx=4)
        discard_button = ttk.Button(bar, text='Discard', command=discard_selected)
        discard_button.pack(side='left', padx=4)
        ttk.Button(bar, text='Later', command=dialog.destroy).pack(side='left', padx=4)
        def selection_changed(_=None):
            value = selected()
            busy = value and value.get('session') != self.session and fsr_windows_session.draft_is_running(value)
            restore_button.configure(state='disabled' if not value or value['orphan'] or value.get('handed_over') or busy else 'normal')
            discard_button.configure(state='disabled' if not value or busy else 'normal')
        tree.bind('<<TreeviewSelect>>', selection_changed)
        selection_changed()
