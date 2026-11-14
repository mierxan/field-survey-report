"""Draft durability and isolation; all report data is invented and temporary."""
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

import fsr_drafts as d
from fsr_draft_form import validate_snapshot


def snapshot():
    return {'simple': {'SO_number_entry': 'INVENTED'}, 'date': 'not finished',
            'condition': '', 'goods': {}, 'others': False, 'others_text': '',
            'item_form': 'Default', 'item_cache': {}, 'other_item_forms': {},
            'items': [{'rows': [{'cells': {'Quantity': '1,'}, 'hidden': {}, 'po_link': {}, 'manual': []}]}],
            'declared': [['', '', '']], 'remarks': ['', 'middle', ''], 'findings': [''],
            'incidents': [], 'schedule_entries': {}, 'transport_entries': {}, 'document_entries': {},
            'withdrawal': {'po': '', 'owned': False, 'activity': '', 'editing': None}}


def value(store, **extra):
    result = {'version': 1, 'id': uuid4().hex, 'scope': store.scope, 'owner': store.owner,
              'revision': 1, 'changed': d.now_text(), 'workbook': 'invented.xlsx',
              'editing': False, 'control': '', 'baseline': {}, 'form': snapshot()}
    result.update(extra)
    return result


@pytest.fixture
def store(tmp_path):
    return d.Store(tmp_path / 'Drafts', 'a' * 32, 'b' * 32)


def test_idle_and_continuous_typing_deadline():
    timer = d.Schedule()
    assert not timer.due(500)
    timer.changed(10)
    assert not timer.due(12.99)
    assert timer.due(13)
    for t in range(11, 40):
        timer.changed(t)
        assert not timer.due(t)
    timer.changed(40)
    assert timer.due(40)
    timer.saved()
    assert not timer.due(999)


def test_roundtrip_preserves_incomplete_input_and_blank_rows(store):
    item = value(store)
    assert validate_snapshot(item['form'])
    path = store.write(item)
    assert store.read(path) == item
    assert len(list(store.root.glob('*.draft.json'))) == 1
    assert not list(store.root.glob('*.tmp'))


def test_failed_replacement_keeps_previous_checkpoint(store, monkeypatch):
    item = value(store)
    path = store.write(item)
    item['revision'] = 2
    def fail(*_):
        raise OSError('invented disk failure')
    monkeypatch.setattr(d.os, 'replace', fail)
    with pytest.raises(OSError):
        store.write(item)
    assert store.read(path)['revision'] == 1


def test_accounts_are_isolated_and_admin_can_only_list_removed_accounts(store):
    own = value(store)
    store.write(own)
    other = d.Store(store.root, store.scope, 'c' * 32)
    theirs = value(other)
    other.write(theirs)
    found, _ = store.list([store.owner, other.owner])
    assert [v['id'] for v in found] == [own['id']]
    found, _ = store.list([store.owner, other.owner], admin=True)
    assert len(found) == 1
    found, _ = store.list([store.owner], admin=True)
    assert len(found) == 2
    assert next(v for v in found if v['id'] == theirs['id'])['orphan']
    with pytest.raises(d.DraftError):
        store.write(theirs)
    store.discard(theirs['id'], other.owner)
    assert not other.path(theirs['id']).exists()


def test_recreated_account_and_separate_account_store_have_different_identity(tmp_path):
    user = {'email': 'sample@example.invalid', 'initials': 'T', 'created': 'one'}
    assert d.account_key(user) != d.account_key({**user, 'created': 'two'})
    assert d.scope_key(tmp_path / 'a/users.json') != d.scope_key(tmp_path / 'b/users.json')


@pytest.mark.parametrize('contents', ['{broken', '[]', '{}', '{"version": 900}'])
def test_damaged_draft_is_preserved_aside(store, contents):
    path = store.path(uuid4().hex)
    path.parent.mkdir()
    path.write_text(contents)
    found, damaged = store.list()
    assert not found and len(damaged) == 1
    assert not path.exists()
    assert Path(damaged[0]).read_text() == contents


def test_malformed_nested_form_is_set_aside(store):
    item = value(store)
    path = store.write(item)
    item['form']['items'][0]['rows'] = 'broken'
    path.write_text(json.dumps(item))
    found, damaged = store.list()
    assert not found and damaged


def test_old_drafts_are_flagged_not_deleted(store):
    item = value(store, changed=(datetime.now(timezone.utc) - timedelta(days=31)).isoformat())
    path = store.write(item)
    found, damaged = store.list()
    assert found[0]['old'] and not damaged and path.exists()


def test_writer_invalidation_cannot_recreate_discarded_draft(store):
    writer = d.Writer(store)
    try:
        item = value(store)
        job = writer.submit(item)
        writer.invalidate(item['id'], discard=True)
        assert job[2].wait(5)
        assert not store.path(item['id']).exists()
    finally:
        writer.close()


def test_journal_retirement_keeps_newer_draft_revision(store):
    item = value(store, revision=3)
    store.write(item)
    ref = {**{k: item[k] for k in ('id', 'scope', 'owner')}, 'root': str(store.root), 'revision': 2}
    d.retire(ref)
    assert store.path(item['id']).exists()
    ref['revision'] = 3
    d.retire(ref)
    assert not store.path(item['id']).exists()


@pytest.mark.parametrize('moment', ['before', 'after'])
def test_killed_process_leaves_complete_old_or_new_checkpoint(store, tmp_path, moment):
    item = value(store)
    path = store.write(item)
    item['revision'] = 2
    input_file = tmp_path / 'input.json'
    input_file.write_text(json.dumps(item))
    marker = tmp_path / 'ready'
    script = r'''
import json, os, sys, time
from pathlib import Path
import fsr_drafts as d
root, input_file, marker, moment = sys.argv[1:]
v = json.loads(Path(input_file).read_text())
replace = os.replace
def cut(temp, target):
    if moment == 'after': replace(temp, target)
    Path(marker).write_text('ready')
    time.sleep(60)
os.replace = cut
d.Store(root, v['scope'], v['owner']).write(v)
'''
    proc = subprocess.Popen([sys.executable, '-c', script, str(store.root), str(input_file), str(marker), moment],
                            cwd=Path(__file__).resolve().parent.parent,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail('Disposable draft process exited before the interruption point')
            time.sleep(.02)
        assert marker.exists()
        proc.kill()  # Abrupt termination: no finally/atexit or GUI close handler.
        proc.wait(timeout=5)
        assert store.read(path)['revision'] == (1 if moment == 'before' else 2)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_draft_paths_respect_sandbox_and_test_overrides(tmp_path):
    assert d.folder({'FSR_HOME': str(tmp_path)}) == tmp_path / 'LocalAppData/FieldSurveyReport/Drafts'
    assert d.folder({'FSR_DRAFT_DIR': str(tmp_path)}) == tmp_path


def test_autosave_has_no_report_or_network_side_effects(store, monkeypatch, tmp_path):
    import fsr_storage
    import db_mysql
    def forbidden(*a, **k):
        pytest.fail('A draft attempted to save a report or connect to MySQL')
    monkeypatch.setattr(fsr_storage, 'write_report_to_excel', forbidden)
    monkeypatch.setattr(db_mysql, 'connect', forbidden)
    item = value(store)
    store.write(item)
    assert not list(tmp_path.rglob('*.xlsx'))
    assert not list(tmp_path.rglob('*.sqlite3'))
    assert item['control'] == ''


def test_difference_lists_nested_and_removed_values():
    changes = d.differences({'a': ['one', 'two']}, {'a': ['new']})
    assert changes == [('a[1]', 'one', 'new'), ('a[2]', 'two', None)]


@pytest.mark.parametrize('backend', ['excel', 'sqlite'])
def test_conditional_save_refuses_newer_report(tmp_path, backend):
    from factories import report
    from datetime import date
    import fsr_store
    import fsr_sqlite_store
    path = tmp_path / 'excel/Reports.xlsx'
    path.parent.mkdir()
    store = fsr_store.ExcelStore(path) if backend == 'excel' else fsr_sqlite_store.new_store(path)
    original = report('FSR-TEST-202611-0001', 'Receiving', date(2026, 11, 14))
    store.write_report(original, False)
    stamp = store.saved_stamp(original['control_no'], False)
    newer = copy_report = json.loads(json.dumps(original))
    newer['general_information']['so_number'] = 'IMPORTED-NEWER'
    store.write_report(copy_report, True)
    with pytest.raises(d.DraftConflict):
        store.write_report(original, True, expected_stamp=stamp)
    assert store.read_report(original['control_no'])['general_information']['so_number'] == 'IMPORTED-NEWER'
    current = store.saved_stamp(original['control_no'], False)
    store.write_report(original, True, expected_stamp=current)
    assert store.read_report(original['control_no'])['general_information']['so_number'] == 'SO-1'


def test_autosave_worker_does_not_block_submit_or_mutate_caller(store, monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    original = store.write
    def slow(value, commit=None):
        entered.set()
        assert release.wait(5)
        return original(value, commit)
    monkeypatch.setattr(store, 'write', slow)
    writer = d.Writer(store)
    try:
        item = value(store)
        job = writer.submit(item)
        assert entered.wait(5)
        item['form']['simple']['SO_number_entry'] = 'new typing while disk waits'
        second = writer.submit({**item, 'revision': 2})
        assert not job[2].is_set()
        release.set()
        assert second[2].wait(5)
        assert store.read(store.path(item['id']))['form']['simple']['SO_number_entry'] == 'new typing while disk waits'
    finally:
        release.set()
        writer.close()


def journal_fixture(tmp_path):
    from factories import report
    from datetime import date
    import fsr_save_journal as journal
    root = tmp_path / 'Drafts'
    draft_store = d.Store(root, 'a' * 32, 'b' * 32)
    item = value(draft_store)
    draft_store.write(item)
    ref = {**{k: item[k] for k in ('id', 'owner', 'scope', 'revision')}, 'root': str(root)}
    data = report('FSR-TEST-202611-0001', 'Receiving', date(2026, 11, 14))
    path = tmp_path / 'excel/Reports.xlsx'
    path.parent.mkdir()
    j = journal.Journal(path)
    stores = journal.Stores(path)
    stores.draft_ref = ref
    return journal, draft_store, item, data, j, stores


def test_failed_normal_save_does_not_retire_draft(tmp_path, monkeypatch):
    journal, store, item, data, j, stores = journal_fixture(tmp_path)
    record = journal.open_save(j, stores, data, False, False, False)
    def failed(_):
        raise OSError('invented report write failure')
    monkeypatch.setattr(stores, 'workbook', failed)
    with pytest.raises(OSError):
        journal.run(j, record, stores)
    journal.discard(j, record)
    assert store.path(item['id']).exists()


def test_committed_draft_is_retired_without_waiting_for_mysql(tmp_path):
    journal, store, item, data, j, stores = journal_fixture(tmp_path)
    record = journal.open_save(j, stores, data, False, False, True)
    journal.run(j, record, stores, mysql=False, lists=False)
    assert not store.path(item['id']).exists()
    assert j.pending()[0]['steps']['mysql'] == journal.PENDING


def test_interrupted_report_save_is_repaired_before_draft_retirement(tmp_path, monkeypatch):
    journal, store, item, data, j, stores = journal_fixture(tmp_path)
    record = journal.open_save(j, stores, data, False, False, False)
    original = stores.incidents
    def interrupted(_):
        raise SystemExit('simulated abrupt exit after report commitment')
    monkeypatch.setattr(stores, 'incidents', interrupted)
    with pytest.raises(SystemExit):
        journal.run(j, record, stores)
    assert store.path(item['id']).exists()
    assert j.pending()
    monkeypatch.setattr(stores, 'incidents', original)
    journal.repair(j, stores, mysql=False)
    assert not store.path(item['id']).exists()
    assert not j.pending()


def test_sqlite_precondition_detects_rewrite_even_with_identical_timestamp(tmp_path):
    from datetime import date, datetime
    from factories import report
    import fsr_sqlite_store
    store = fsr_sqlite_store.new_store(tmp_path / 'Reports.xlsx')
    data = report('FSR-TEST-202611-0001', 'Receiving', date(2026, 11, 14))
    stamp = datetime(2026, 11, 14, 12)
    store.write_report(data, False, saved_at=stamp)
    revision = store.changes()
    expected = store.saved_stamp(data['control_no'], False)
    data['general_information']['so_number'] = 'NEWER-SAME-TIME'
    store.write_report(data, True, saved_at=stamp)
    with pytest.raises(d.DraftConflict):
        store.write_report(data, True, expected_stamp=expected, expected_revision=revision)


def test_recreated_accounts_get_distinct_signed_draft_identities(tmp_path):
    import secrets
    import app_auth
    import fsr_secrets
    store = app_auth.UserStore(tmp_path / 'users.json', secrets=fsr_secrets.MemorySecretStore(), use_seed=False)
    credential = secrets.token_urlsafe(24)
    args = ('Draft', '', 'Tester', 'DT', 'draft-tester@example.invalid', credential)
    store.sign_up(*args, credential)
    first = store.find('draft-tester@example.invalid')
    first_identity = first['draft_identity']
    first_key = d.account_key(first)
    store.delete('draft-tester@example.invalid')
    store.sign_up(*args, credential)
    second = store.find('draft-tester@example.invalid')
    assert first_identity != second['draft_identity']
    assert first_key != d.account_key(second)
    # Both identities survive a normal signed-account-file reload.
    reloaded = app_auth.UserStore(store.path, secrets=store.secrets, use_seed=False)
    assert d.account_key(reloaded.find('draft-tester@example.invalid')) == d.account_key(second)


def test_valid_json_content_damage_is_detected_and_preserved_aside(store):
    item = value(store)
    path = store.write(item)
    damaged = json.loads(path.read_text(encoding='utf-8'))
    damaged['form']['simple']['SO_number_entry'] = 'CORRUPTED-BUT-STILL-VALID-JSON'
    path.write_text(json.dumps(damaged), encoding='utf-8')
    found, preserved = store.list()
    assert not found and len(preserved) == 1
    assert json.loads(Path(preserved[0]).read_text())['form']['simple']['SO_number_entry'] == 'CORRUPTED-BUT-STILL-VALID-JSON'
