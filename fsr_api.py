"""
Central API storage for the Field Survey Report program.

Setup: copy api_config.example.json to api_config.json and set "base_url".
If api_config.json is missing (or "enabled" is false) nothing changes and the
program uses Excel / MySQL as before.

This module has the same functions as db_mysql.py, so the program, the Open
Saved Report window, the Weekly Summary and the warehouse modules work on it
unchanged. It talks only to the API over HTTPS: no database login is on this PC.
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from fsr_storage import split_quantity_unit

CONFIG_FILE = Path(__file__).resolve().parent / "api_config.json"
API_PREFIX = "/api/v1"
TIMEOUT = 90             # a sleeping free server takes about a minute to wake
KEEP_AWAKE_SECONDS = 600
WAKING = (502, 503, 504)
PAGE_SIZE = 200
LOCAL_HOSTS = ("localhost", "127.0.0.1", "10.0.2.2")
LIST_SLUGS = {
    "consignee_list": "consignees", "supplier_list": "suppliers", "broker_list": "brokers",
    "hauler_list": "haulers", "location_list": "locations", "destination_list": "destinations",
    "country_of_origin_list": "countries",
}


STARTING_MESSAGE = "The server is starting. Please wait a minute and try again."


class ApiError(Exception):
    """A problem that can be shown to the user as it is."""

    def __init__(self, message, status=None, code=None, details=None):
        super().__init__(message)
        self.status, self.code, self.details = status, code, details

    @property
    def offline(self):
        return self.status is None


class VersionConflict(ApiError):
    """Someone else saved this report first. .server_report is the current copy."""

    @property
    def server_report(self):
        return (self.details or {}).get("server_report") or {}


_lock = threading.RLock()
_tokens = {"access": None, "refresh": None}
_report_meta = {}        # {control #: {"uuid", "version", "prepared_by"}} of reports read or saved
_pending_uuid = {}       # {form's control #: uuid}: a retried save of a new report stays one report
_master_snapshot = {}    # {list key: {name.casefold(): item}} as last read from the server


# ---------- configuration ----------

def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            config = json.load(file)
    except (OSError, ValueError):
        return None
    if not isinstance(config, dict) or not config.get("enabled", True):
        return None
    return config if config.get("base_url") else None


def is_enabled():
    return load_config() is not None


def base_url():
    config = load_config()
    if config is None:
        raise ApiError("The server address is not set up (api_config.json).")
    url = str(config["base_url"]).rstrip("/")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" and parts.hostname not in LOCAL_HOSTS:
        raise ApiError("The server address must start with https://")
    return url


def read_raw_config():
    return dict(load_config() or {})


def write_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as file:
        json.dump(config, file, indent=4)


def connect(config=None):
    raise RuntimeError("The central API is in use: there is no direct database connection.")


def explain_error(error):
    return str(error)


# ---------- requests ----------

def _send(method, path, body=None, query=None, auth=True):
    url = base_url() + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if auth and _tokens["access"]:
        headers["Authorization"] = f"Bearer {_tokens['access']}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            text = response.read().decode("utf-8")
            try:
                return response.status, json.loads(text) if text else {}
            except ValueError:
                raise ApiError(STARTING_MESSAGE) from None
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8")).get("error") or {}
        except ValueError:
            # Not from the API: the hosting service answers while the server wakes.
            payload = {"message": STARTING_MESSAGE} if error.code in WAKING else {}
        return error.code, {"error": payload}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ApiError(
            "The server cannot be reached. Check the internet connection and try again.\n"
            f"({getattr(error, 'reason', error)})") from error


def _raise_for(status, payload):
    error = payload.get("error") or {}
    message = error.get("message") or f"The server answered with an error ({status})."
    details = error.get("details")
    if status == 422 and isinstance(details, list):
        message += "\n" + "\n".join(f"- {d.get('field')}: {d.get('message')}" for d in details)
    kind = VersionConflict if error.get("code") == "version_conflict" else ApiError
    raise kind(message, status=status, code=error.get("code"), details=details)


def _refresh_session():
    refresh = _tokens["refresh"]
    if not refresh:
        return False
    status, payload = _send("POST", f"{API_PREFIX}/auth/refresh", {"refresh_token": refresh}, auth=False)
    if status != 200:
        _tokens.update(access=None, refresh=None)
        return False
    _tokens.update(access=payload["access_token"], refresh=payload["refresh_token"])
    return True


def _call(method, path, body=None, query=None):
    """One API call; an expired access token is renewed once and the call repeated."""
    with _lock:
        status, payload = _send(method, f"{API_PREFIX}{path}", body, query)
        if status == 401 and _refresh_session():
            status, payload = _send(method, f"{API_PREFIX}{path}", body, query)
    if status >= 400:
        if status == 401:
            raise ApiError("Your session has ended. Please sign out and sign in again.", status=401)
        _raise_for(status, payload)
    return payload


def keep_awake(interval=KEEP_AWAKE_SECONDS):
    """While the program is open, stop the free server sleeping, so a save or a
    sign-in does not wait for it to wake. Problems are ignored: this is only a help."""
    def work():
        while True:
            try:
                _send("GET", "/health", auth=False)
            except ApiError:
                pass
            time.sleep(interval)
    threading.Thread(target=work, name="fsr-keep-awake", daemon=True).start()


def test_connection(config=None):
    """(ok, message): the same contract as db_mysql.test_connection."""
    try:
        status, payload = _send("GET", "/health/ready", auth=False)
    except ApiError as error:
        return False, str(error)
    if status != 200:
        return False, (payload.get("error") or {}).get("message") or "The server is not ready."
    return True, f"Connected to {base_url()}"


# ---------- sign in (same methods as app_auth.UserStore) ----------

class ApiUserStore:
    """Accounts on the server. auth_error is app_auth.AuthError, passed in so
    this module stays free of the windows."""

    def __init__(self, auth_error):
        self.auth_error = auth_error

    def _guard(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ApiError as error:
            raise self.auth_error(str(error)) from error

    @staticmethod
    def _as_user(item):
        return {**item, "role": "user" if item.get("role") == "inspector" else item.get("role")}

    def sign_in(self, initials, password):
        def work():
            label = "Windows"
            status, payload = _send("POST", f"{API_PREFIX}/auth/login", {
                "username": (initials or "").strip(), "password": password, "device_label": label}, auth=False)
            if status != 200:
                _raise_for(status, payload)
            _tokens.update(access=payload["access_token"], refresh=payload["refresh_token"])
            return self._as_user(payload["user"])
        return self._guard(work)

    def sign_up(self, first, middle, last, initials, email, password, confirm):
        if password != confirm:
            raise self.auth_error("The two passwords do not match.")
        def work():
            status, payload = _send("POST", f"{API_PREFIX}/auth/register", {
                "first_name": first.strip(), "middle_name": middle.strip(), "last_name": last.strip(),
                "initials": initials.strip().upper(), "email": email.strip().lower(), "password": password},
                auth=False)
            if status >= 400:
                _raise_for(status, payload)
        self._guard(work)

    def list_users(self):
        return [self._as_user(u) for u in self._guard(_call, "GET", "/users")["items"]]

    def pending_count(self):
        try:
            return sum(1 for u in self.list_users() if u.get("status") == "pending")
        except self.auth_error:
            return 0

    def find(self, email):
        email = (email or "").strip().lower()
        return next((u for u in self.list_users() if u.get("email", "").lower() == email), None)

    def _id(self, email):
        user = self.find(email)
        if user is None:
            raise self.auth_error("That account was not found.")
        return user["id"]

    def set_status(self, email, status):
        self._guard(_call, "PATCH", f"/users/{self._id(email)}", {"status": status})

    def delete(self, email):
        self._guard(_call, "DELETE", f"/users/{self._id(email)}")

    def set_password(self, email, password):
        self._guard(_call, "POST", f"/users/{self._id(email)}/reset-password", {"new_password": password})

    def change_own_password(self, email, old, new, confirm):
        if new != confirm:
            raise self.auth_error("The two new passwords do not match.")
        self._guard(_call, "POST", "/auth/change-password", {"current_password": old, "new_password": new})


def sign_out():
    """Best effort: the program is closing, so a failure here must not stop it."""
    refresh = _tokens["refresh"]
    _tokens.update(access=None, refresh=None)
    if refresh:
        try:
            _send("POST", f"{API_PREFIX}/auth/logout", {"refresh_token": refresh}, auth=False)
        except ApiError:
            pass


# ---------- master lists ----------

def refresh_master_lists(master_data):
    """Replace the lists with the server's active names, in place, because the
    comboboxes hold these same list objects. Raises ApiError when offline; the
    lists then stay as cached in master_list.json."""
    payload = _call("GET", "/master-data", query={"include_inactive": "true"})
    snapshot = {}
    for key, items in payload["lists"].items():
        snapshot[key] = {item["name"].casefold(): item for item in items}
        names = sorted((i["name"] for i in items if i["is_active"]), key=str.casefold)
        if key in master_data:
            master_data[key][:] = names
        else:
            master_data[key] = names
    _master_snapshot.clear()
    _master_snapshot.update(snapshot)
    return master_data


def save_master_lists(master_data, connection=None):
    """Send what changed since the last read: new names are added, removed names
    are deactivated. Saved reports keep their text either way. The server decides
    who may do what; its refusal is raised here and the caller rolls back."""
    if not _master_snapshot:
        refresh_master_lists({})
    for key, slug in LIST_SLUGS.items():
        known = _master_snapshot.setdefault(key, {})
        names = {str(n).strip().casefold(): str(n).strip() for n in master_data.get(key, []) if str(n).strip()}
        for folded, name in names.items():
            item = known.get(folded)
            if item is None or not item["is_active"]:
                known[folded] = _call("POST", f"/master-data/{slug}", {"name": name})
        for folded, item in list(known.items()):
            if item["is_active"] and folded not in names:
                known[folded] = _call("PATCH", f"/master-data/{slug}/{item['id']}",
                                      {"base_version": item["version"], "is_active": False})


# ---------- reports ----------

def _remember(document):
    _report_meta[document["control_no"]] = {
        "uuid": document["uuid"], "version": document["version"],
        "prepared_by": document.get("prepared_by") or ""}
    return document


def prepared_by(control_no):
    return (_report_meta.get(control_no) or {}).get("prepared_by") or ""


def forget_pending():
    """A new form was started: the next save is a different report."""
    _pending_uuid.clear()


def accept_server_version(control_no, version):
    """The user reviewed a conflict and keeps their copy: the next save goes on top."""
    _report_meta[control_no]["version"] = version


def save_document(data, editing):
    """Save the form on the server and return the saved document, which has the
    official Control # and the Receiving Refs that follow it. Saving a new report
    twice (say the answer to the first try was lost) still makes one report."""
    document = {k: v for k, v in data.items() if k != "incident_error"}
    control = document["control_no"]
    if not editing:
        document["uuid"] = _pending_uuid.setdefault(control, str(uuid.uuid4()))
        saved = _call("POST", "/reports", document)
        _pending_uuid.pop(control, None)
        return _remember(saved)

    meta = _report_meta.get(control)
    if meta is None:
        meta = _remember(_call("GET", f"/reports/{urllib.parse.quote(control)}"))
    document["uuid"] = meta["uuid"]
    saved = _call("PUT", f"/reports/{urllib.parse.quote(control)}",
                  {"base_version": meta["version"], "op_id": str(uuid.uuid4()), "report": document})
    return _remember(saved)


def save_report(data, connection=None):
    """db_mysql.save_report(): the program itself uses save_document()."""
    save_document(data, data.get("control_no") in _report_meta)
    return []


def sync_reports(reports):
    raise ApiError("Reports are saved on the server directly, so there is nothing to copy.")


def _pages(path, query=None):
    page = 1
    while True:
        payload = _call("GET", path, query={**(query or {}), "page": page, "page_size": PAGE_SIZE})
        yield from payload["items"]
        if page * PAGE_SIZE >= payload["total"]:
            return
        page += 1


def list_reports(connection=None):
    """[(control #, SO number, inspection date, consignee, last saved), ...] newest first."""
    return [(r["control_no"], r["so_number"], r["inspection_date"], r["consignee"], r["last_saved"])
            for r in _pages("/reports")]


def load_report(control_no, connection=None):
    return _remember(_call("GET", f"/reports/{urllib.parse.quote(control_no)}"))


def load_all_reports(connection=None):
    return [_remember(report) for report in _pages("/reports", {"full": "true"})]


def weekly_summary(first_day, last_day, connection=None):
    rows = _call("GET", "/reports/weekly-summary",
                 query={"date_from": first_day.isoformat(), "date_to": last_day.isoformat()})["rows"]
    for row in rows:
        row[20], row[21] = split_quantity_unit(row[20], row[21])
    return rows


def search_index(connection=None):
    return _call("GET", "/reports/search-index")["index"]


def missing_link_columns(connection=None):
    return []


def upgrade_schema(connection=None):
    return []
