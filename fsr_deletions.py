"""Recoverable report deletion. Archive commits before either copy is removed.

Incomplete operations remain visible and can be retried from Deleted History.
The archive is local to this workbook; it is never pruned automatically.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import fsr_paths
import fsr_storage
from fsr_sqlite_store import encode, decode


def history_path(path):
    path = Path(path)
    return fsr_paths.json_dir_for_workbook(path) / (path.stem + '_deleted.sqlite3')


@contextmanager
def _connect(path):
    target = history_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('''CREATE TABLE IF NOT EXISTS deleted (
            id INTEGER PRIMARY KEY, control_no TEXT NOT NULL,
            deleted_at TEXT NOT NULL, deleted_by TEXT NOT NULL,
            payload TEXT NOT NULL, state TEXT NOT NULL, restored_at TEXT)''')
        with conn:
            yield conn
    finally:
        conn.close()


def history(path):
    with _connect(path) as conn:
        return [dict(row) for row in conn.execute(
            'SELECT id, control_no, deleted_at, deleted_by, state, restored_at '
            'FROM deleted ORDER BY id DESC')]


def is_deleted(path, control):
    if not history_path(path).exists():
        return False
    with _connect(path) as conn:
        return any(fsr_storage.same_key(row['control_no'], control)
                   for row in conn.execute(
                       "SELECT control_no FROM deleted WHERE state != 'restored'"))


def active_deleted_controls(path):
    """Controls hidden from live views until recovery fully succeeds."""
    if not history_path(path).exists():
        return set()
    with _connect(path) as conn:
        return {fsr_storage.control_key(row['control_no']) for row in conn.execute(
            "SELECT control_no FROM deleted WHERE state != 'restored'")}


def check_write(path, data):
    """An old open form or queued save must not recreate a deleted report."""
    if not is_deleted(path, data['control_no']):
        return
    from fsr_mysql_guard import fingerprint
    for row in history(path):
        if row['state'] == 'restored' or not fsr_storage.same_key(row['control_no'], data['control_no']):
            continue
        if row['state'] == 'restoring':
            _, payload = _record(path, row['id'])
            if fingerprint(data) == fingerprint(payload['local'] or payload['remote']):
                continue
        raise ValueError('This report is in Deleted History. Restore it before saving it again.')


def _record(path, ident):
    with _connect(path) as conn:
        row = conn.execute('SELECT * FROM deleted WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise ValueError('Deleted report history entry was not found.')
    return dict(row), json.loads(row['payload'], object_hook=decode)


def _state(path, ident, state):
    with _connect(path) as conn:
        conn.execute('UPDATE deleted SET state=?, restored_at=? WHERE id=?',
                     (state, datetime.now().isoformat(timespec='seconds')
                      if state == 'restored' else None, ident))


def _export(store):
    if store.kind == 'sqlite':
        import fsr_sqlite_export
        fsr_sqlite_export.write_export(store)


def delete(store, control, db=None, user=''):
    """Archive both versions, then remove MySQL, local storage and Excel."""
    if store.owns_withdrawal(control):
        raise ValueError('PO-linked Withdrawal reports cannot be deleted here.')
    if is_deleted(store.excel_path, control):
        raise ValueError('This report already has a deletion in progress. Use Deleted History.')
    guard = store.mysql_guard(db, user=user)
    with guard.local_write():
        if is_deleted(store.excel_path, control):
            raise ValueError('This report already has a deletion in progress. Use Deleted History.')
        conn = db.connect() if db else None
        locked = False
        try:
            if db:
                locked = db.lock_report(conn, control)
                if not locked:
                    raise ValueError('This report is busy in MySQL. Try again.')
            local = next((r for r in store.read_all_reports()
                          if fsr_storage.same_key(r['control_no'], control)), None)
            remote = db.load_report(control, conn) if db and db.report_exists(conn, control) else None
            if local is None and remote is None:
                raise ValueError('The report no longer exists.')
            payload = dict(local=local, remote=remote, mysql=bool(db),
                           incidents=store.load_incidents(control) if local else
                           (remote or {}).get('incident_reports', []))
            with _connect(store.excel_path) as archive:
                ident = archive.execute(
                    'INSERT INTO deleted (control_no, deleted_at, deleted_by, payload, state) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (control, datetime.now().isoformat(timespec='seconds'), user,
                     json.dumps(payload, default=encode, ensure_ascii=False), 'pending')).lastrowid
            _finish(store, ident, control, payload, db, conn)
            return ident
        finally:
            if conn:
                if locked:
                    db.unlock_report(conn, control)
                conn.close()


def _finish(store, ident, control, payload, db, conn):
    if payload['mysql']:
        if db is None:
            raise ValueError('Reconnect MySQL to finish this deletion.')
        db.delete_report(control, conn)
    store.remove_archived_report(control)
    store.delete_incidents(control)
    _export(store)
    _state(store.excel_path, ident, 'deleted')


def retry(store, ident, db=None):
    row, payload = _record(store.excel_path, ident)
    if row['state'] != 'pending':
        raise ValueError('Only an incomplete deletion can be retried.')
    # Retry only the original snapshots. Never silently delete a replacement.
    control = row['control_no']
    guard = store.mysql_guard(db)
    with guard.local_write():
        conn = db.connect() if db else None
        locked = False
        try:
            if db:
                locked = db.lock_report(conn, control)
                if not locked:
                    raise ValueError('This report is busy in MySQL.')
                if db.report_exists(conn, control):
                    from fsr_mysql_guard import fingerprint
                    if payload['remote'] is None or fingerprint(db.load_report(control, conn)) != fingerprint(payload['remote']):
                        raise ValueError('MySQL contains a changed report. Deletion was stopped.')
            from fsr_mysql_guard import fingerprint
            for report in store.read_all_reports():
                if fsr_storage.same_key(report['control_no'], control):
                    if payload['local'] is None or fingerprint(report) != fingerprint(payload['local']):
                        raise ValueError('The local report changed. Deletion was stopped.')
            _finish(store, ident, control, payload, db, conn)
        finally:
            if conn:
                if locked:
                    db.unlock_report(conn, control)
                conn.close()


def restore(store, ident, db=None):
    row, payload = _record(store.excel_path, ident)
    if row['state'] not in ('deleted', 'restoring'):
        raise ValueError('Finish the deletion before restoring it, or this entry was already restored.')
    control = row['control_no']
    if payload['mysql'] and db is None:
        raise ValueError('Reconnect MySQL before restoring this report.')
    guard = store.mysql_guard(db)
    with guard.local_write():
        conn = db.connect() if payload['mysql'] else None
        locked = False
        try:
            from fsr_mysql_guard import fingerprint
            data = payload['local'] or payload['remote']
            remote_data = payload['remote'] or data
            remote_present = False
            if conn:
                locked = db.lock_report(conn, control)
                if not locked:
                    raise ValueError('This report is busy in MySQL.')
                if db.report_exists(conn, control):
                    if row['state'] != 'restoring' or fingerprint(db.load_report(control, conn)) != fingerprint(remote_data):
                        raise ValueError('MySQL already contains this Control #. Nothing was overwritten.')
                    remote_present = True
            local = next((r for r in store.read_all_reports()
                          if fsr_storage.same_key(r['control_no'], control)), None)
            if local is not None and (row['state'] != 'restoring' or fingerprint(local) != fingerprint(data)):
                raise ValueError('This PC already contains this Control #. Nothing was overwritten.')
            _state(store.excel_path, ident, 'restoring')
            if local is None:
                store.write_report(data, False)
            store.save_incidents(control, data['general_information']['so_number'], payload['incidents'])
            if conn and not remote_present:
                db.save_report(remote_data, conn)
            _export(store)
            _state(store.excel_path, ident, 'restored')
        finally:
            if conn:
                if locked:
                    db.unlock_report(conn, control)
                conn.close()
