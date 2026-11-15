"""Back up the program's code: every branch and tag in ONE dated git bundle,
checked before it counts, in a folder you choose; the newest 10 are kept.

  BACKUP_CODE.bat [<folder>]        asks for the folder when none is given
                                    (and remembers the last one)
  python tools/backup_code.py [<folder>] [--yes] [--keep N]

What a bundle holds: the commits of every branch and every tag - the code
and its whole history, nothing else. It holds no data: the reports, the
accounts, the settings, the MySQL settings and passwords and the .venv are
never committed (.gitignore), and the backup stops if any such file appears
in any commit of any branch. Changes that are not committed are NOT in a
bundle; the tool says so before it starts.

A bundle counts only after three checks: `git bundle verify`, every branch
and tag of the repository is in it at the same commit, and a trial clone of
it passes `git fsck`. Until then it is written as "....bundle.partial" and
removed if a check fails.

Restoring: docs/BACKUP_CODE.md.
"""
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

KEEP = 10
NAME = re.compile(r"^FSR_code_\d{4}-\d{2}-\d{2}_\d{6}\.bundle$")
REMEMBER = "fsr_backup_code.json"         # inside .git: never committed

# Paths that must never be in a commit (data, accounts, passwords, .venv).
FORBIDDEN = [re.compile(p, re.IGNORECASE) for p in (
    r"(^|/)Drafts/",
    r"\.draft\.",
    r"(^|/)\.venv/",
    r"\.sqlite3",
    r"(^|/)users[^/]*\.json$",
    r"(^|/)db_config\.json$",
    r"(^|/)settings[^/]*\.json$",
    r"(^|/)secrets\.json$",
    r"(^|/)auth_seed\.json$",
    r"(^|/)data/json/private/",
    r"(^|/)data/schema/private/",
    r"\.log$",
    r"(^|/)(Field_Survey_Reports|Withdrawal_Reports|PO_Master|Withdrawn_Item)"
    r"[^/]*\.xlsx$",
    r"_mysql_ledger\.json$",
    r"_pending_saves\.json$",
    r"_imported_reports\.json$",
    r"_import_review\.json$",
    r"_import_history\.jsonl$",
    r"_handovers\.json$",
    r"(^|/)Backups/",
    r"(^|/)(Incident Reports|Item Forms|Report Forms|MySQL Replaced)/",
    r"(^|/)(set_password|allow_network_access)\.sql$",
    r"(^|/)MYSQL_SETUP\.txt$",
)]


class BackupError(Exception):
    """The backup was not made; the message says why in plain words."""


def git(repo, *args, check=True):
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    if check and done.returncode != 0:
        raise BackupError(f"git {' '.join(args)} failed:\n"
                          f"{(done.stderr or done.stdout).strip()}")
    return done


def repo_root(start):
    found = git(start, "rev-parse", "--show-toplevel")
    return Path(found.stdout.strip())


def tips(repo):
    """{ref name: commit or tag id} of every branch and tag."""
    out = git(repo, "for-each-ref", "--format=%(objectname) %(refname)",
              "refs/heads", "refs/tags").stdout
    return dict(reversed(line.split(" ", 1)) for line in out.splitlines()
                if line.strip())


def forbidden_paths(repo):
    """Every path ever committed, on any branch, that must not be there."""
    out = git(repo, "log", "--all", "--format=", "--name-only").stdout
    paths = sorted({line.strip() for line in out.splitlines() if line.strip()})
    return [p for p in paths if any(rule.search(p) for rule in FORBIDDEN)]


def uncommitted(repo):
    """Changed or new files that are not committed (not in a bundle)."""
    out = git(repo, "status", "--porcelain").stdout
    return [line[3:] for line in out.splitlines() if line.strip()]


def _remove_tree(path):
    """Remove a folder, also the read-only files git makes."""
    def writable(func, target, _):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    shutil.rmtree(path, onexc=writable)


def check_bundle(repo, bundle, expected):
    """The three checks. Returns nothing; raises BackupError."""
    verify = git(repo, "bundle", "verify", str(bundle), check=False)
    if verify.returncode != 0:
        raise BackupError("git bundle verify found a problem:\n"
                          + (verify.stderr or verify.stdout).strip())
    heads = git(repo, "bundle", "list-heads", str(bundle)).stdout
    inside = dict(reversed(line.split(" ", 1)) for line in heads.splitlines()
                  if line.strip())
    missing = [ref for ref, sha in expected.items() if inside.get(ref) != sha]
    if missing:
        raise BackupError("These branches or tags are not in the bundle as "
                          "they are in the repository: " + ", ".join(missing))
    trial = Path(tempfile.mkdtemp(prefix="fsr_bundle_check_"))
    try:
        target = trial / "clone.git"
        clone = subprocess.run(["git", "clone", "--mirror", "-q", str(bundle),
                                str(target)], capture_output=True, text=True)
        if clone.returncode != 0:
            raise BackupError("A trial copy could not be made from the "
                              "bundle:\n" + clone.stderr.strip())
        fsck = git(target, "fsck", "--full", check=False)
        if fsck.returncode != 0:
            raise BackupError("The trial copy of the bundle is damaged:\n"
                              + (fsck.stderr or fsck.stdout).strip())
        if tips(target) != expected:
            raise BackupError("The trial copy does not have every branch and "
                              "tag at the same commit.")
    finally:
        _remove_tree(trial)


def keep_newest(folder, keep=KEEP):
    """Remove the oldest bundles beyond `keep` - only files named by this
    tool (FSR_code_<date>_<time>.bundle); nothing else is touched."""
    bundles = sorted((p for p in Path(folder).iterdir()
                      if p.is_file() and NAME.match(p.name)),
                     key=lambda p: p.name, reverse=True)
    removed = []
    for old in bundles[keep:]:
        old.unlink()
        removed.append(old)
    return removed


def backup(repo, folder, keep=KEEP, now=None):
    """Make, check and keep one bundle. Returns (bundle path, removed)."""
    repo = Path(repo)
    folder = Path(folder)
    bad = forbidden_paths(repo)
    if bad:
        raise BackupError(
            "The backup was NOT made: these files are in the history and look "
            "like data, accounts, passwords or the .venv:\n  "
            + "\n  ".join(bad[:20]))
    expected = tips(repo)
    if not expected:
        raise BackupError("The repository has no branches to back up.")
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    final = folder / f"FSR_code_{stamp}.bundle"
    if final.exists():
        raise BackupError(f"{final.name} exists already; try again in a "
                          "second.")
    partial = final.with_name(final.name + ".partial")
    try:
        git(repo, "bundle", "create", str(partial), "HEAD", "--branches",
            "--tags")
        check_bundle(repo, partial, expected)
        os.replace(partial, final)
    finally:
        if partial.exists():
            partial.unlink()
    return final, keep_newest(folder, keep)


# ---------- the folder, remembered ----------

def remembered(repo):
    try:
        data = json.loads((Path(repo) / ".git" / REMEMBER).read_text(
            encoding="utf-8"))
        return data.get("folder") or ""
    except (OSError, ValueError):
        return ""


def remember(repo, folder):
    try:
        (Path(repo) / ".git" / REMEMBER).write_text(
            json.dumps({"folder": str(folder)}), encoding="utf-8")
    except OSError:
        pass


def ask_folder(start):
    """A folder picker (or a typed path when no window can be shown)."""
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(
            title="Where should the code backup go?",
            initialdir=start or str(Path.home()), mustexist=False)
        root.destroy()
        return chosen or ""
    except Exception:
        return input("Folder for the code backup: ").strip().strip('"')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("folder", nargs="?")
    parser.add_argument("--yes", action="store_true",
                        help="do not ask about uncommitted changes")
    parser.add_argument("--keep", type=int, default=KEEP)
    args = parser.parse_args(argv)
    try:
        repo = repo_root(Path(__file__).resolve().parent)
        folder = args.folder or ask_folder(remembered(repo))
        if not folder:
            print("No folder chosen: nothing was backed up.")
            return 2
        folder = Path(folder)
        pending = uncommitted(repo)
        if pending:
            print(f"{len(pending)} change(s) are NOT committed and will NOT "
                  "be in the backup, for example:")
            for line in pending[:8]:
                print("   ", line)
            if not args.yes and input("Back up the committed code anyway? "
                                      "(y/n) ").strip().lower() != "y":
                print("Nothing was backed up.")
                return 2
        print(f"Backing up every branch to {folder} ...")
        bundle, removed = backup(repo, folder, keep=args.keep)
    except BackupError as error:
        print(f"\nTHE BACKUP WAS NOT MADE.\n{error}")
        return 1
    remember(repo, folder)
    size = bundle.stat().st_size / 1024 / 1024
    branches = len([r for r in tips(repo) if r.startswith("refs/heads/")])
    print(f"\nDone and checked: {bundle}\n  {size:.1f} MB, {branches} "
          "branch(es); verified, complete, and a trial copy passed git fsck.")
    if removed:
        print(f"  {len(removed)} older backup(s) removed (the newest "
              f"{args.keep} are kept).")
    print("To restore: docs/BACKUP_CODE.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
