"""BACKUP_CODE.bat (tools/backup_code.py): every branch and tag in one
dated, checked git bundle; the newest 10 kept; never a bundle with data,
accounts or passwords in it. A throwaway repository in a temporary folder -
the project's own repository is only read by the last test."""
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import backup_code as bc  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None,
                                reason="git is not installed")


def git(repo, *args):
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture
def repo(tmp_path):
    """Two branches and a tag, the way the project has them."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "program.py").write_text("print('one')\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "first")
    git(repo, "tag", "v1")
    git(repo, "checkout", "-q", "-b", "improvements/phase-x")
    (repo / "program.py").write_text("print('two')\n")
    git(repo, "commit", "-q", "-am", "second")
    return repo


WHEN = datetime(2026, 11, 14, 10, 15, 0)


def test_one_checked_bundle_with_every_branch_and_tag(repo, tmp_path):
    folder = tmp_path / "backups"
    bundle, removed = bc.backup(repo, folder, now=WHEN)
    assert bundle == folder / "FSR_code_2026-11-14_101500.bundle"
    assert removed == [] and not list(folder.glob("*.partial"))
    heads = git(repo, "bundle", "list-heads", str(bundle))
    for ref in ("refs/heads/main", "refs/heads/improvements/phase-x",
                "refs/tags/v1"):
        assert ref in heads
    # restoring: a clone of the bundle has both branches and the code
    restored = tmp_path / "restored"
    git(tmp_path, "clone", "-q", str(bundle), str(restored))
    assert (restored / "program.py").read_text() == "print('two')\n"
    remote = git(restored, "branch", "-r")
    assert "origin/main" in remote and "origin/improvements/phase-x" in remote
    git(restored, "checkout", "-q", "main")
    assert (restored / "program.py").read_text() == "print('one')\n"


def test_the_newest_ten_are_kept_and_nothing_else_is_touched(repo, tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    for day in range(1, 12):                 # 11 older backups
        (folder / f"FSR_code_2026-10-{day:02d}_090000.bundle").write_text("x")
    (folder / "my notes.txt").write_text("keep me")
    (folder / "FSR_code_other.bundle").write_text("not one of ours")
    bundle, removed = bc.backup(repo, folder, now=WHEN)
    left = sorted(p.name for p in folder.glob("FSR_code_20*.bundle"))
    assert len(left) == 10 and left[-1] == bundle.name
    assert left[0] == "FSR_code_2026-10-03_090000.bundle"
    assert sorted(p.name for p in removed) == [
        "FSR_code_2026-10-01_090000.bundle",
        "FSR_code_2026-10-02_090000.bundle"]
    assert (folder / "my notes.txt").exists()
    assert (folder / "FSR_code_other.bundle").exists()


@pytest.mark.parametrize("name", [
    "data/json/private/settings.json", "users.json", "db_config.json",
    "data/excel/Field_Survey_Reports.xlsx", ".venv/lib/x.py",
    "Field_Survey_Reports.sqlite3", "field_survey_report.log",
    "private/unfinished.draft.json", "Drafts/unfinished.json"])
def test_no_bundle_when_data_or_passwords_were_ever_committed(repo, tmp_path,
                                                              name):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("secret")
    git(repo, "add", "-f", name)
    git(repo, "commit", "-q", "-m", "oops")
    git(repo, "rm", "-q", "--cached", name)        # gone now - but in history
    git(repo, "commit", "-q", "-m", "removed")
    folder = tmp_path / "backups"
    with pytest.raises(bc.BackupError, match="NOT made"):
        bc.backup(repo, folder, now=WHEN)
    assert not folder.exists() or not list(folder.iterdir())


def test_a_bundle_that_fails_a_check_is_not_kept(repo, tmp_path,
                                                 monkeypatch):
    folder = tmp_path / "backups"
    folder.mkdir()
    older = folder / "FSR_code_2026-10-01_090000.bundle"
    older.write_text("an older backup")

    def broken(repo, bundle, expected):
        raise bc.BackupError("the trial copy is damaged")
    monkeypatch.setattr(bc, "check_bundle", broken)
    with pytest.raises(bc.BackupError, match="damaged"):
        bc.backup(repo, folder, now=WHEN)
    assert sorted(p.name for p in folder.iterdir()) == [older.name]


def test_a_branch_missing_from_the_bundle_is_found(repo, tmp_path):
    bundle = tmp_path / "only_main.bundle"
    git(repo, "bundle", "create", str(bundle), "main")
    with pytest.raises(bc.BackupError, match="not in the bundle"):
        bc.check_bundle(repo, bundle, bc.tips(repo))


def test_uncommitted_changes_are_named(repo):
    (repo / "program.py").write_text("print('not committed')\n")
    (repo / "new.py").write_text("")
    assert sorted(bc.uncommitted(repo)) == ["new.py", "program.py"]


def test_the_command_line_remembers_the_folder(repo, tmp_path, monkeypatch,
                                               capsys):
    monkeypatch.setattr(bc, "repo_root", lambda start: repo)
    folder = tmp_path / "chosen"
    assert bc.main([str(folder), "--yes"]) == 0
    out = capsys.readouterr().out
    assert "Done and checked" in out and "trial copy passed git fsck" in out
    assert bc.remembered(repo) == str(folder)


def test_the_project_history_has_no_data_or_passwords():
    """What a real backup would refuse: nothing, today."""
    assert bc.forbidden_paths(ROOT) == []
