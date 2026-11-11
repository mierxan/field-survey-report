"""Wrong passwords: growing wait, 15-minute lock, and a PC clock that is
changed while an account is locked."""
import json
from datetime import datetime, timedelta

import pytest

import app_auth
import fsr_secrets

GOOD = "administrator-pass"
START = datetime(2026, 11, 11, 9, 0, 0)


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now

    def forward(self, **kw):
        self.now += timedelta(**kw)


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    secrets = fsr_secrets.MemorySecretStore()
    path = tmp_path / "users.json"

    def open_store():
        return app_auth.UserStore(path, secrets=secrets, use_seed=False,
                                  clock=clock)

    store = open_store()
    store.create_administrator("Site", "", "Admin", "SA",
                               "admin@example.invalid", GOOD, GOOD)
    store.sign_up("Test", "", "User", "TU", "user@example.invalid",
                  "correct-horse", "correct-horse")
    store.set_status("user@example.invalid", "approved")
    return store, clock, path, open_store


def saved(path, initials):
    users = json.loads(path.read_text(encoding="utf-8"))["users"]
    return next(u for u in users if u["initials"] == initials)


def rewrite(store, path, change):
    """Change the file as the program itself would (signed again): these
    tests are about odd lock values, not about the signature."""
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    document["signature"] = app_auth.sign_document(
        document, store.recovery_code())
    path.write_text(json.dumps(document), encoding="utf-8")
    store._copy_last_good()


def fail(store, initials="SA"):
    with pytest.raises(app_auth.AuthError) as error:
        store.sign_in(initials, "wrong-password")
    return str(error.value)


def lock(store, clock, initials="SA"):
    """Five wrong passwords, each after its wait is over."""
    for _ in range(app_auth.MAX_FAILURES - 1):
        assert "Incorrect" in fail(store, initials)
        clock.forward(seconds=11)
    message = fail(store, initials)
    assert "now locked for 15 minutes" in message


def test_first_wrong_password_needs_no_wait(env):
    store, clock, path, _ = env
    assert fail(store) == "Incorrect initials or password."
    assert store.sign_in("SA", GOOD)["role"] == "admin"
    assert "failed_count" not in saved(path, "SA")


def test_wait_grows_with_every_wrong_password(env):
    store, clock, _, _ = env
    fail(store)                                   # 1st: no wait
    fail(store)                                   # 2nd: 2 seconds
    assert fail(store) == "Please wait 2 seconds before trying again."
    with pytest.raises(app_auth.AuthError, match="Please wait 2 seconds"):
        store.sign_in("SA", GOOD)                 # right password: still wait
    clock.forward(seconds=2)
    fail(store)                                   # 3rd: 5 seconds
    assert "wait 5 seconds" in fail(store)
    clock.forward(seconds=4)
    assert "wait 1 second " in fail(store)
    clock.forward(seconds=1)
    fail(store)                                   # 4th: 10 seconds
    assert "wait 10 seconds" in fail(store)


def test_attempts_during_a_wait_are_not_counted(env):
    store, clock, path, _ = env
    fail(store)
    fail(store)
    for _ in range(20):
        assert "Please wait" in fail(store)
    assert saved(path, "SA")["failed_count"] == 2


def test_fifth_wrong_password_locks_for_15_minutes(env):
    store, clock, path, _ = env
    lock(store, clock)
    assert "locked for 15 more minutes" in fail(store)
    with pytest.raises(app_auth.AuthError, match="locked for 15 more"):
        store.sign_in("SA", GOOD)
    clock.forward(minutes=14, seconds=30)
    assert "Please wait 30 seconds" in fail(store)
    clock.forward(seconds=30)
    assert store.sign_in("SA", GOOD)["role"] == "admin"
    record = saved(path, "SA")
    assert "blocked_until" not in record and "failed_count" not in record


def test_lock_survives_a_restart(env):
    store, clock, path, open_store = env
    lock(store, clock)
    again = open_store()
    with pytest.raises(app_auth.AuthError, match="locked for"):
        again.sign_in("SA", GOOD)


def test_lock_is_per_account(env):
    store, clock, _, _ = env
    lock(store, clock, "TU")
    assert store.sign_in("SA", GOOD)["role"] == "admin"


def test_success_resets_the_count(env):
    store, clock, path, _ = env
    for _ in range(3):
        fail(store)
        clock.forward(seconds=11)
    store.sign_in("SA", GOOD)
    for _ in range(4):                 # four more: still not locked
        assert "Incorrect" in fail(store)
        clock.forward(seconds=11)
    assert store.sign_in("SA", GOOD)


def test_count_starts_again_after_a_lock(env):
    store, clock, _, _ = env
    lock(store, clock)
    clock.forward(minutes=15)
    assert fail(store) == "Incorrect initials or password."
    assert store.sign_in("SA", GOOD)


def test_unknown_initials_are_slowed_down_too(env):
    store, clock, path, _ = env
    before = path.read_bytes()
    fail(store, "ZZ")
    fail(store, "ZZ")
    assert "Please wait" in fail(store, "ZZ")
    assert path.read_bytes() == before       # nothing is saved for them
    assert store.sign_in("SA", GOOD)


def test_administrator_reset_ends_a_lock(env):
    store, clock, _, _ = env
    lock(store, clock, "TU")
    store.set_password("user@example.invalid", "fresh-passphrase")
    assert store.sign_in("TU", "fresh-passphrase")["role"] == "user"


# ---------- the PC clock ----------

def test_clock_set_back_keeps_the_lock_active(env):
    store, clock, _, _ = env
    lock(store, clock)
    clock.forward(minutes=5)
    fail(store)                               # the program sees 5 min pass
    clock.now = START - timedelta(days=2)     # clock set back two days
    assert "locked for 10 more minutes" in fail(store)
    with pytest.raises(app_auth.AuthError, match="locked for"):
        store.sign_in("SA", GOOD)
    clock.forward(minutes=10)
    assert store.sign_in("SA", GOOD)


def test_clock_set_forward_then_back_cannot_stretch_the_lock(env):
    store, clock, _, open_store = env
    lock(store, clock)
    clock.now = START + timedelta(days=400)
    assert store.sign_in("SA", GOOD)          # the lock is over
    clock.now = START
    assert open_store().sign_in("SA", GOOD)   # and stays over


@pytest.mark.parametrize("role_initials", ["SA", "TU"])
def test_no_lock_is_ever_longer_than_15_minutes(env, role_initials):
    """Even with a hand-edited or far-future lock in the file."""
    store, clock, path, open_store = env

    def far_future(document):
        for user in document["users"]:
            user["blocked_until"] = "2099-01-01T00:00:00"
            user["failed_count"] = 10**6

    rewrite(store, path, far_future)
    store = open_store()
    assert store.problem is None
    assert "locked for 15 more minutes" in fail(store, role_initials)
    clock.forward(minutes=15)
    password = GOOD if role_initials == "SA" else "correct-horse"
    assert store.sign_in(role_initials, password)


def test_clock_set_back_with_far_future_lock_still_ends_in_15_minutes(env):
    store, clock, path, open_store = env
    lock(store, clock)
    rewrite(store, path, lambda document: document["users"][0].update(
        blocked_until="2099-01-01T00:00:00"))
    clock.now = START - timedelta(days=30)
    store = open_store()
    assert store.problem is None
    assert "locked for 15 more minutes" in fail(store)
    clock.forward(minutes=15)
    assert store.sign_in("SA", GOOD)


@pytest.mark.parametrize("junk", ["soon", 12, None, "", []])
def test_unreadable_lock_values_do_not_block(env, junk):
    store, clock, path, open_store = env

    def spoil(document):
        document["users"][0]["blocked_until"] = junk
        document["users"][0]["failed_count"] = junk
        document["time_seen"] = junk

    rewrite(store, path, spoil)
    store = open_store()
    assert store.problem is None
    assert store.sign_in("SA", GOOD)
    assert store.problem is None


def test_pending_account_with_right_password_is_not_counted(env):
    store, clock, path, _ = env
    store.sign_up("New", "", "Person", "NP", "new@example.invalid",
                  "correct-horse", "correct-horse")
    for _ in range(8):
        with pytest.raises(app_auth.AuthError, match="waiting"):
            store.sign_in("NP", "correct-horse")
    assert "blocked_until" not in saved(path, "NP")
