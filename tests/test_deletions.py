from datetime import date

import pytest

import fsr_deletions as deleted
import fsr_storage as storage
import fsr_store
from factories import report
from fake_mysql import FakeServer


@pytest.fixture(params=['excel', 'sqlite'])
def store(request, tmp_path):
    path = tmp_path / 'reports.xlsx'
    original = fsr_store.ExcelStore(path)
    original.write_report(report('FSR-REAL-1', 'Receiving', date(2026, 11, 22)), False)
    if request.param == 'sqlite':
        import fsr_sqlite_migrate
        assert fsr_sqlite_migrate.migrate(path).status == 'migrated'
    return fsr_store.open_store(path)


def database(store):
    server = FakeServer()
    server.put(store.read_report('FSR-REAL-1'))
    db = server.client()
    def remove(control, connection=None):
        server.reports.pop(storage.control_key(control), None)
    db.delete_report = remove
    return db


def test_delete_and_restore_both_copies(store):
    db = database(store)
    before = store.read_report('FSR-REAL-1')
    ident = deleted.delete(store, 'FSR-REAL-1', db, 'Inspector')
    assert not store.list_reports()
    assert not storage.list_saved_reports(store.excel_path)
    assert db.server.get('FSR-REAL-1') is None
    assert deleted.history(store.excel_path)[0]['deleted_by'] == 'Inspector'
    assert deleted.is_deleted(store.excel_path, 'fsr-real-1')
    with pytest.raises(ValueError, match='Deleted History'):
        store.mysql_guard(db).save(before)
    deleted.restore(store, ident, db)
    assert len(store.list_reports()) == 1
    assert len(storage.list_saved_reports(store.excel_path)) == 1
    assert db.server.get('FSR-REAL-1')
    assert deleted.history(store.excel_path)[0]['state'] == 'restored'
    assert not deleted.is_deleted(store.excel_path, 'FSR-REAL-1')


def test_failed_local_delete_keeps_archive_and_can_retry(store, monkeypatch):
    db = database(store)
    remove = store.remove_archived_report
    def fail(control):
        raise PermissionError('Excel is open')
    monkeypatch.setattr(store, 'remove_archived_report', fail)
    with pytest.raises(PermissionError):
        deleted.delete(store, 'FSR-REAL-1', db)
    row = deleted.history(store.excel_path)[0]
    assert row['state'] == 'pending'
    assert store.list_reports()
    monkeypatch.setattr(store, 'remove_archived_report', remove)
    deleted.retry(store, row['id'], db)
    assert not store.list_reports()
    deleted.restore(store, row['id'], db)
    assert store.list_reports()


def test_restore_does_not_overwrite_replacement(store):
    ident = deleted.delete(store, 'FSR-REAL-1')
    replacement = report('FSR-REAL-1', 'Receiving', date(2026, 11, 23))
    # Simulate replacement by an external writer bypassing the application.
    if store.kind == 'sqlite':
        store._write(lambda conn: store._apply_report(conn, replacement, False, None))
    else:
        storage.write_report_to_excel(store.excel_path, replacement, False)
    with pytest.raises(ValueError, match='Nothing was overwritten'):
        deleted.restore(store, ident)
    assert store.read_report('FSR-REAL-1')['general_information']['inspection_date'] == '23-Nov-2026'


def test_archive_failure_prevents_delete(store, monkeypatch):
    def fail(path):
        raise OSError('disk full')
    monkeypatch.setattr(deleted, '_connect', fail)
    with pytest.raises(OSError):
        deleted.delete(store, 'FSR-REAL-1')
    assert store.list_reports()


def test_old_open_form_cannot_recreate_deleted_report(store):
    data = store.read_report('FSR-REAL-1')
    deleted.delete(store, 'FSR-REAL-1')
    with pytest.raises(ValueError, match='Deleted History'):
        store.write_report(data, True)
    assert not store.list_reports()


@pytest.mark.parametrize('activity', ['Receiving', 'Withdrawal'])
def test_deleted_reports_are_hidden_from_monitoring_until_restored(store, monkeypatch, activity):
    from warehouse import store as warehouse
    import db_mysql
    data = report('FSR-REAL-1', activity, date(2026, 11, 22), condition='Bad Order')
    store.write_report(data, True)
    before = store.read_all_reports()
    ident = deleted.delete(store, 'FSR-REAL-1')
    # Even a stale MySQL response or a caller-supplied pre-delete list is hidden.
    monkeypatch.setattr(db_mysql, 'load_all_reports', lambda: before)
    assert warehouse.load_reports(store.excel_path, 'mysql') == []
    for source in ('excel', 'mysql'):
        snap = warehouse.load_snapshot(store.excel_path, source)
        assert snap.reports == []
        assert snap.transactions == []
        assert snap.inventory.items == []
    assert warehouse.load_snapshot(store.excel_path, reports=before).transactions == []
    deleted.restore(store, ident)
    restored = warehouse.load_snapshot(store.excel_path).transactions
    assert len(restored) == 1
    assert restored[0].activity == activity
    assert restored[0].condition == 'Bad Order'


def test_incomplete_delete_stays_hidden_from_monitoring(store, monkeypatch):
    from warehouse import store as warehouse
    def fail(control):
        raise PermissionError('file open')
    monkeypatch.setattr(store, 'remove_archived_report', fail)
    with pytest.raises(PermissionError):
        deleted.delete(store, 'FSR-REAL-1')
    assert store.read_all_reports()  # Physical deletion has not happened yet.
    assert warehouse.load_snapshot(store.excel_path).transactions == []


def test_mysql_delete_rolls_back_children_on_error():
    import db_mysql
    from test_db_mysql import FakeConnection, BASE
    conn = FakeConnection(BASE)
    db_mysql.delete_report('FSR-1', conn)
    assert conn.committed
    assert len(conn.statements) == 5
    assert all(params == ('FSR-1',) for _, params in conn.statements)


def test_restore_resumes_after_mysql_failure(store, monkeypatch):
    db = database(store)
    ident = deleted.delete(store, 'FSR-REAL-1', db)
    save = db.save_report
    def fail(*args):
        raise OSError('connection lost')
    monkeypatch.setattr(db, 'save_report', fail)
    with pytest.raises(OSError):
        deleted.restore(store, ident, db)
    assert deleted.history(store.excel_path)[0]['state'] == 'restoring'
    monkeypatch.setattr(db, 'save_report', save)
    deleted.restore(store, ident, db)
    assert store.list_reports()
    assert db.server.get('FSR-REAL-1')
    assert deleted.history(store.excel_path)[0]['state'] == 'restored'


def test_delete_transaction_failure_rolls_back():
    import db_mysql
    class Cursor:
        def execute(self, sql, params):
            if 'item_lines' in sql:
                raise OSError('delete failed')
        def close(self):
            pass
    class Connection:
        rolled_back = False
        def cursor(self):
            return Cursor()
        def commit(self):
            pytest.fail('failed deletion must not commit')
        def rollback(self):
            self.rolled_back = True
    conn = Connection()
    with pytest.raises(OSError):
        db_mysql.delete_report('FSR-1', conn)
    assert conn.rolled_back
