"""Build check: the User edition must not contain private account data.

build_installer.bat runs this on dist\\User\\FieldSurveyReport before the
Setup file is made, and stops the build when it reports a problem:

  * a file that never belongs in a User installer (auth_seed.json,
    users.json, db_config.json, settings.json, secrets.json), or
  * any email, salt or password hash of an account of this PC - the owner's
    seed and the local users.json - anywhere inside any file.

  python fsr_build_check.py dist\\User\\FieldSurveyReport
"""
import json
import sys
import zipfile
from pathlib import Path

FORBIDDEN_NAMES = ("auth_seed.json", "users.json", "db_config.json",
                   "settings.json", "secrets.json")
PRIVATE_DIR = Path(__file__).resolve().parent / "data" / "json" / "private"
ACCOUNT_FILES = ("auth_seed.json", "users.json")
MIN_LENGTH = 6                      # shorter values would match by accident


def _accounts(data):
    """Every account dictionary of a seed or users file."""
    if not isinstance(data, dict):
        return []
    found = [data.get("owner")]
    for key in ("built_in_users", "users"):
        value = data.get(key)
        found.extend(value if isinstance(value, list) else [])
    return [a for a in found if isinstance(a, dict)]


def private_values(private_dir=PRIVATE_DIR):
    """{text that must not be in the build: where it came from}."""
    values = {}
    for name in ACCOUNT_FILES:
        try:
            data = json.loads(
                (Path(private_dir) / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for account in _accounts(data):
            for key in ("email", "salt", "hash"):
                value = str(account.get(key) or "").strip()
                if len(value) >= MIN_LENGTH:
                    values[value] = f"{key} of an account in {name}"
    return values


def _needles(values):
    result = []
    for value, source in values.items():
        for variant in {value, value.lower(), value.upper()}:
            result.append((variant.encode("utf-8"), source))
            result.append((variant.encode("utf-16-le"), source))
    return result


def _contents(path):
    """(label, bytes) of a file and, for zip archives, of every member."""
    try:
        yield str(path), path.read_bytes()
    except OSError as error:
        raise SystemExit(f"Could not read {path}: {error}")
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                yield f"{path} > {member}", archive.read(member)


def find_problems(build_dir, values=None):
    """A list of plain-language problems; empty when the build is clean."""
    build_dir = Path(build_dir)
    if not build_dir.is_dir():
        return [f"The folder does not exist: {build_dir}"]
    needles = _needles(private_values() if values is None else values)
    problems = []
    for path in sorted(p for p in build_dir.rglob("*") if p.is_file()):
        if path.name.lower() in FORBIDDEN_NAMES:
            problems.append(f"{path}: this file must not be in the User "
                            "edition")
        for label, content in _contents(path):
            sources = sorted({source for needle, source in needles
                              if needle in content})
            for source in sources:
                problems.append(f"{label}: contains the {source}")
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    values = private_values()
    problems = find_problems(argv[0], values)
    if problems:
        print("PRIVATE DATA FOUND in the User edition:")
        for problem in problems:
            print("  " + problem)
        return 1
    print(f"User edition is clean: no account file and none of the "
          f"{len(values)} private account value(s) of this PC were found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
