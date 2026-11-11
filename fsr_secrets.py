"""Small secrets kept outside the program's own data files.

One interface, three places:

  WindowsCredentialStore  Windows Credential Manager (per Windows login,
                          protected by Windows). Used by the real program.
  FileSecretStore         a plain JSON file. Only a fallback (no Credential
                          Manager, test sandboxes started with FSR_HOME): it
                          keeps the program working but protects nothing.
  MemorySecretStore       nothing leaves the process. Used by the tests.

Kept here: the "this PC is set up" record and signing key of users.json
(app_auth.py) and the MySQL password (db_mysql.py).
"""
import json
import os
import sys
from pathlib import Path

TARGET_PREFIX = "FieldSurveyReport/"
NOT_FOUND = 1168                    # Windows: ERROR_NOT_FOUND


class SecretStoreError(OSError):
    """The protected storage could not be read or written."""


class MemorySecretStore:
    """Values live in this object only."""
    protected = False

    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = str(value)

    def delete(self, name):
        self.values.pop(name, None)


class FileSecretStore:
    """A JSON file. NOT protected - see the module text."""
    protected = False

    def __init__(self, path):
        self.path = Path(path)

    def _read(self):
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as error:
            raise SecretStoreError(
                f"The file {self.path} could not be read: {error}") from error
        return data if isinstance(data, dict) else {}

    def _write(self, data):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(self.path.name + ".tmp")
            with open(temp, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)
            os.replace(temp, self.path)
        except OSError as error:
            raise SecretStoreError(
                f"The file {self.path} could not be written: {error}"
            ) from error

    def get(self, name):
        return self._read().get(name)

    def set(self, name, value):
        data = self._read()
        data[name] = str(value)
        self._write(data)

    def delete(self, name):
        data = self._read()
        if name in data:
            del data[name]
            self._write(data)


class WindowsCredentialStore:
    """Generic credentials named FieldSurveyReport/<name> in the Windows
    Credential Manager of the signed-in Windows user."""
    protected = True

    def __init__(self):
        try:
            import pywintypes
            import win32cred
            # Reading an entry returns its "last written" time, which
            # pywin32 builds with win32timezone - loaded only at that
            # moment. Imported here so the installer always contains it
            # and a PC without it falls back instead of failing later.
            import win32timezone  # noqa: F401
        except ImportError as error:
            raise SecretStoreError(
                "The Windows Credential Manager is not available "
                f"({error}).") from error
        self._cred = win32cred
        self._error = pywintypes.error

    def get(self, name):
        try:
            found = self._cred.CredRead(
                TARGET_PREFIX + name, self._cred.CRED_TYPE_GENERIC)
        except self._error as error:
            if error.winerror == NOT_FOUND:
                return None
            raise SecretStoreError(
                f"Windows Credential Manager: {error.strerror}") from error
        blob = found.get("CredentialBlob") or b""
        return blob.decode("utf-16-le") if isinstance(blob, bytes) else blob

    def set(self, name, value):
        try:
            self._cred.CredWrite({
                "Type": self._cred.CRED_TYPE_GENERIC,
                "TargetName": TARGET_PREFIX + name,
                "UserName": "FieldSurveyReport",
                "CredentialBlob": str(value),
                "Persist": self._cred.CRED_PERSIST_LOCAL_MACHINE,
            }, 0)
        except self._error as error:
            raise SecretStoreError(
                f"Windows Credential Manager: {error.strerror}") from error

    def delete(self, name):
        try:
            self._cred.CredDelete(
                TARGET_PREFIX + name, self._cred.CRED_TYPE_GENERIC)
        except self._error as error:
            if error.winerror != NOT_FOUND:
                raise SecretStoreError(
                    f"Windows Credential Manager: {error.strerror}"
                ) from error


_MEMORY = MemorySecretStore()


def default_store(fallback_dir, environ=None, frozen=None):
    """The store the program uses for the data folder `fallback_dir`.

    The installed program always uses the Credential Manager when Windows
    has one. FSR_SECRET_STORE=memory (the automated tests) and FSR_HOME (a
    sandbox folder) are honoured so a test never touches the real one."""
    environ = os.environ if environ is None else environ
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    fallback = FileSecretStore(Path(fallback_dir) / "secrets.json")
    if not frozen and environ.get("FSR_SECRET_STORE", "").lower() == "memory":
        return _MEMORY
    if str(environ.get("FSR_HOME", "")).strip():
        return fallback
    try:
        return WindowsCredentialStore()
    except SecretStoreError:
        return fallback
