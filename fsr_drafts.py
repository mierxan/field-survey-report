"""Local, account-scoped unfinished form checkpoints; never a report writer."""
import copy
import functools
import inspect
from contextlib import contextmanager
import hashlib
import json
import logging
import os
import queue
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger('fsr')
VERSION = 1
ID = re.compile(r'^[0-9a-f]{32}$')
_UNSET = object()


class DraftError(ValueError):
    pass


class DraftConflict(DraftError):
    pass


def now_text():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def folder(environ=None):
    env = os.environ if environ is None else environ
    home = env.get('FSR_HOME', '').strip()
    if home:
        return Path(home) / 'LocalAppData' / 'FieldSurveyReport' / 'Drafts'
    override = env.get('FSR_DRAFT_DIR', '').strip()
    if override:
        return Path(override)
    import fsr_db_location
    result = Path(env.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'FieldSurveyReport/Drafts'
    if fsr_db_location.is_network(result) or fsr_db_location.sync_tool(result, env):
        raise DraftError('Drafts cannot be stored in a synchronized folder or on a network drive.')
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    default=str).encode('utf-8')).hexdigest()


def account_key(account):
    # New accounts have a signed random identity, including recreation within
    # the same minute. Existing accounts retain their stable legacy identity.
    identity = account.get('draft_identity')
    if isinstance(identity, str) and ID.fullmatch(identity):
        return digest(['account', identity])[:32]
    return digest([str(account.get('email', '')).strip().casefold(),
                   account.get('created', ''), account.get('initials', '').casefold()])[:32]


def scope_key(account_file):
    return digest(os.path.normcase(str(Path(account_file).resolve())))[:32]


def differences(before, after, prefix=''):
    """Leaf-level differences, including added/removed fields and rows."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return [d for k in sorted(before.keys() | after.keys())
                for d in differences(before.get(k), after.get(k), f'{prefix}.{k}'.strip('.'))]
    if isinstance(before, list) and isinstance(after, list):
        return [d for i in range(max(len(before), len(after)))
                for d in differences(before[i] if i < len(before) else None,
                                     after[i] if i < len(after) else None, f'{prefix}[{i + 1}]')]
    return [(prefix, before, after)]


class Store:
    def __init__(self, root, scope, owner):
        self.root, self.scope, self.owner = Path(root), scope, owner
        if not ID.fullmatch(scope) or not ID.fullmatch(owner):
            raise DraftError('Invalid draft account scope.')
        self.lock = threading.RLock()

    def path(self, draft_id, owner=None):
        owner = owner or self.owner
        if not ID.fullmatch(draft_id) or not ID.fullmatch(owner):
            raise DraftError('Invalid draft identity.')
        return self.root / f'{self.scope}-{owner}-{draft_id}.draft.json'

    def write(self, value, commit=None):
        value = copy.deepcopy(value)
        value.pop('checksum', None)
        if value.get('scope') != self.scope or value.get('owner') != self.owner:
            raise DraftError('This draft belongs to another account.')
        target = self.path(value['id'])
        validate(value)
        value['checksum'] = digest(value)
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=target.stem + '.', suffix='.tmp', dir=self.root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False, default=str)
                stream.flush()
                os.fsync(stream.fileno())
            with self.lock:
                if commit is None:
                    os.replace(temp, target)
                else:
                    commit(temp, target)
        finally:
            Path(temp).unlink(missing_ok=True)
        return target

    def read(self, path):
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        validate(value)
        checksum = value.pop('checksum', None)
        if not isinstance(checksum, str) or checksum != digest(value):
            raise DraftError('The draft integrity check failed.')
        if Path(path) != self.path(value['id'], value['owner']) or value['scope'] != self.scope:
            raise DraftError('Draft filename and ownership do not match.')
        return value

    def discard(self, draft_id, owner=None):
        with self.lock:
            self.path(draft_id, owner).unlink(missing_ok=True)

    def list(self, active_accounts=None, admin=False):
        """Only own drafts, plus removed-account drafts for discard by admins."""
        found, damaged = [], []
        active = set(active_accounts or ()) | {self.owner}
        for path in sorted(self.root.glob(f'{self.scope}-*.draft.json')):
            parts = path.name.split('-')
            if len(parts) != 3:
                continue
            owner = parts[1]
            orphan = owner not in active
            if owner != self.owner and not (admin and orphan):
                continue
            try:
                value = self.read(path)
                value['orphan'] = owner != self.owner
                changed = datetime.fromisoformat(value['changed'])
                value['old'] = (datetime.now(timezone.utc) - changed).total_seconds() > 30 * 86400
                found.append(value)
            except (OSError, ValueError, TypeError, KeyError):
                # Preserve unreadable content and do not disclose it to another user.
                try:
                    destination = self.root / 'Damaged' / (path.name + '.' + uuid.uuid4().hex)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    path.replace(destination)
                    damaged.append(str(destination))
                except OSError:
                    damaged.append(str(path))
        return found, damaged


def validate(value):
    if (not isinstance(value, dict) or value.get('version') != VERSION
            or not all(ID.fullmatch(str(value.get(k, ''))) for k in ('id', 'owner', 'scope'))
            or not isinstance(value.get('form'), dict)
            or not isinstance(value.get('revision'), int)
            or not isinstance(value.get('editing'), bool)
            or not isinstance(value.get('workbook'), str)
            or not isinstance(value.get('baseline'), dict)):
        raise DraftError('Unrecognized or damaged draft.')
    from fsr_draft_form import validate_snapshot
    if not validate_snapshot(value['form']):
        raise DraftError('The draft form is damaged or has an unsupported format.')
    changed = datetime.fromisoformat(value['changed'])
    if changed.tzinfo is None:
        raise DraftError('Draft time has no timezone.')


class Schedule:
    """Monotonic debounce with a deadline that typing cannot push back."""
    def __init__(self, idle=3., maximum=30.):
        self.idle, self.maximum = idle, maximum
        self.first = self.last = None

    def changed(self, now):
        if self.first is None:
            self.first = now
        self.last = now

    def due(self, now):
        return self.first is not None and (now - self.last >= self.idle or now - self.first >= self.maximum)

    def saved(self):
        self.first = self.last = None


class Writer:
    """A single daemon worker; invalidation and replacement share a lock."""
    def __init__(self, store):
        self.store = store
        self.jobs, self.results = queue.Queue(), queue.Queue()
        self.generation = 0
        self.closed = False
        self.lock = threading.RLock()
        self.thread = threading.Thread(target=self._run, daemon=True, name='Draft checkpoint')
        self.thread.start()

    def submit(self, value):
        with self.lock:
            job = (self.generation, copy.deepcopy(value), threading.Event())
            self.jobs.put(job)
            return job

    def _run(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            generation, value, event = job
            error = None
            try:
                def commit(temp, target, generation=generation):
                    with self.lock:
                        if generation == self.generation and not self.closed:
                            os.replace(temp, target)
                self.store.write(value, commit=commit)
            except Exception as problem:
                error = problem
            finally:
                self.results.put((value['id'], value['revision'], error))
                event.set()
                self.jobs.task_done()

    def invalidate(self, draft_id=None, discard=False):
        with self.store.lock, self.lock:
            self.generation += 1
            if discard and draft_id:
                self.store.discard(draft_id)

    def close(self):
        with self.lock:
            self.generation += 1
            self.closed = True
        self.jobs.put(None)


def retire(ref):
    """Journal replay can retire only the exact draft revision it committed."""
    if not ref:
        return
    store = Store(ref['root'], ref['scope'], ref['owner'])
    path = store.path(ref['id'])
    if path.exists():
        value = store.read(path)
        if value['revision'] <= ref['revision']:
            store.discard(ref['id'])


def file_version(path):
    path = Path(path)
    if not path.exists():
        return None
    info = path.stat()
    return [info.st_size, info.st_mtime_ns]


def saved_state(store, control, linked=False):
    for _ in range(3):
        sqlite = hasattr(store, 'changes')
        path = store.withdrawal_path if linked else store.excel_path
        before = store.changes() if sqlite else file_version(path)
        stamp = store.saved_stamp(control, linked)
        data = None
        if stamp is not None:
            data = store.read_withdrawal_report(control) if linked else store.read_report(control)
            data['other_item_forms'] = store.load_item_forms(control)
        after = store.changes() if sqlite else file_version(path)
        if before == after:
            return {'stamp': stamp, 'data': data, '_revision' if sqlite else '_file': after}
    raise DraftConflict('The saved reports are changing in another session. Try reviewing this draft again.')


def check_stamp(actual, expected):
    if expected is not _UNSET and actual != expected:
        raise DraftConflict('The saved data changed after you reviewed the draft. Review it again; nothing was overwritten.')


_REPORT_LOCKS = {}
_REPORT_GUARD = threading.Lock()
_LOCAL = threading.local()


@contextmanager
def report_lock(path):
    """Cooperating workbook writers share an OS mutex, including imports."""
    key = digest(os.path.normcase(str(Path(path).resolve())))
    with _REPORT_GUARD:
        lock = _REPORT_LOCKS.setdefault(key, threading.RLock())
    with lock:
        held = getattr(_LOCAL, 'held', set())
        if key in held:
            yield
            return
        import sys
        if sys.platform == 'win32':
            import ctypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateMutexW.restype = ctypes.c_void_p
            handle = kernel.CreateMutexW(None, False, 'Local\\FSR-Report-' + key)
            if not handle:
                raise OSError('Could not lock the report workbook.')
            result = kernel.WaitForSingleObject(ctypes.c_void_p(handle), 5000)
            if result not in (0, 0x80):
                kernel.CloseHandle(ctypes.c_void_p(handle))
                raise OSError('Another session is writing this workbook. Try Save again.')
        else:
            import fcntl
            stream = open(Path(tempfile.gettempdir()) / ('fsr-report-' + key + '.lock'), 'a')
            fcntl.flock(stream, fcntl.LOCK_EX)
        _LOCAL.held = held | {key}
        try:
            yield
        finally:
            _LOCAL.held = held
            if sys.platform == 'win32':
                kernel.ReleaseMutex(ctypes.c_void_p(handle))
                kernel.CloseHandle(ctypes.c_void_p(handle))
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
                stream.close()


def report_write_lock(func):
    signature = inspect.signature(func)
    @functools.wraps(func)
    def guarded(*args, **kwargs):
        bound = signature.bind(*args, **kwargs).arguments
        with report_lock(bound.get('main_path', bound['path'])):
            return func(*args, **kwargs)
    return guarded


def workbook_stamp(wb, sheet, control):
    import fsr_storage
    if sheet not in wb.sheetnames:
        return None
    for value in fsr_storage.report_dicts(wb[sheet]):
        if fsr_storage.same_key(value.get('Control #'), control):
            stamp = value.get('Last Saved')
            return stamp.isoformat(timespec='milliseconds') if isinstance(stamp, datetime) else str(stamp) if stamp is not None else ''
    return None


def comparable_state(state):
    """Ignore read-only representation details, but compare every side form."""
    import fsr_mysql_guard
    result = copy.deepcopy(state)
    data = result.get('data')
    if data is not None:
        result['data'] = fsr_mysql_guard.canonical(data)
        result['data']['other_item_forms'] = fsr_mysql_guard.canonical(data.get('other_item_forms') or {})
    result.pop('remote', None)
    result.pop('_revision', None)
    result.pop('_file', None)
    return result
