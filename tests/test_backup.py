"""Daily workbook backup: one copy before the first save of a day, the
newest N kept, and nothing but its own files ever removed."""
from datetime import date, timedelta

import pytest

import fsr_backup as b

DAY = date(2026, 11, 12)


@pytest.fixture
def book(tmp_path):
    path = tmp_path / "Field_Survey_Reports.xlsx"
    path.write_bytes(b"workbook as it was this morning")
    return path


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def test_first_save_of_the_day_copies_the_workbook_as_it_was(book):
    result = b.backup_before_save(book, today=DAY)

    target = book.parent / "Backups" / \
        "Field_Survey_Reports_backup_20261112.xlsx"
    assert result == {"created": target, "removed": [], "kept": 1}
    assert target.read_bytes() == b"workbook as it was this morning"
    assert book.read_bytes() == b"workbook as it was this morning"
    assert names(target.parent) == [target.name]        # no temp file left


def test_later_saves_of_the_same_day_keep_the_morning_copy(book):
    first = b.backup_before_save(book, today=DAY)["created"]
    book.write_bytes(b"after the first save")

    result = b.backup_before_save(book, today=DAY)

    assert result["created"] is None
    assert first.read_bytes() == b"workbook as it was this morning"


def test_next_day_gets_its_own_copy(book):
    b.backup_before_save(book, today=DAY)
    book.write_bytes(b"end of day one")
    second = b.backup_before_save(book, today=DAY + timedelta(days=1))
    assert second["created"].name.endswith("_backup_20261113.xlsx")
    assert second["created"].read_bytes() == b"end of day one"
    assert second["kept"] == 2


def test_no_workbook_yet_means_no_backup(tmp_path):
    result = b.backup_before_save(tmp_path / "new.xlsx", today=DAY)
    assert result["created"] is None
    assert not (tmp_path / "Backups").exists()


def test_only_the_newest_n_are_kept(book):
    for offset in range(20):
        book.write_bytes(f"day {offset}".encode())
        result = b.backup_before_save(book, keep=14,
                                      today=DAY + timedelta(days=offset))
    kept = b.list_backups(book)
    assert len(kept) == 14 == result["kept"]
    assert kept[0][0] == DAY + timedelta(days=19)        # newest first
    assert kept[-1][0] == DAY + timedelta(days=6)
    assert kept[-1][1].read_bytes() == b"day 6"
    assert len(result["removed"]) == 1


def test_default_is_fourteen():
    assert b.DEFAULT_KEEP == 14
    assert b.keep_setting({}) == 14 and b.keep_setting(None) == 14
    assert b.keep_setting({"backup_keep": 30}) == 30
    assert b.keep_setting({"backup_keep": 0}) == 0
    for bad in (-1, "30", 2.5, True, None, 99999):
        assert b.keep_setting({"backup_keep": bad}) == 14


def test_keep_zero_turns_the_backup_off(book):
    assert b.backup_before_save(book, keep=0, today=DAY)["created"] is None
    assert not (book.parent / "Backups").exists()


def test_lowering_the_number_removes_the_oldest_at_the_next_save(book):
    for offset in range(6):
        b.backup_before_save(book, keep=14, today=DAY + timedelta(offset))
    result = b.backup_before_save(book, keep=2, today=DAY + timedelta(5))
    assert [day for day, _ in b.list_backups(book)] == [
        DAY + timedelta(5), DAY + timedelta(4)]
    assert len(result["removed"]) == 4


def test_pruning_touches_nothing_but_this_workbooks_backups(book):
    folder = book.parent / "Backups"
    folder.mkdir()
    keep_out = [
        "Field_Survey_Reports_backup_20200101.xlsx.bak",   # extra ending
        "Field_Survey_Reports_backup_2020010.xlsx",        # 7 digits
        "Field_Survey_Reports_backup_20209999.xlsx",       # impossible date
        "Field_Survey_Reports_backup_20200101 (1).xlsx",   # a hand-made copy
        "Field_Survey_Reports_before_import_20200101.xlsx",
        "Withdrawal_Reports_backup_20200101.xlsx",         # another workbook
        "My_Field_Survey_Reports_backup_20200101.xlsx",
        "notes.txt",
        "Field_Survey_Reports.xlsx",
    ]
    for name in keep_out:
        (folder / name).write_bytes(b"not mine")
    (folder / "Field_Survey_Reports_backup_20200102.xlsx").mkdir()   # folder
    beside = book.parent / "Field_Survey_Reports_backup_20200101.xlsx"
    beside.write_bytes(b"same pattern, but not in the Backups folder")
    for year in (2020, 2021, 2022):                         # real old backups
        (folder / f"Field_Survey_Reports_backup_{year}0303.xlsx"
         ).write_bytes(b"old")

    result = b.backup_before_save(book, keep=2, today=DAY)

    assert sorted(p.name for p in result["removed"]) == [
        "Field_Survey_Reports_backup_20200303.xlsx",
        "Field_Survey_Reports_backup_20210303.xlsx"]
    left = names(folder)
    for name in keep_out:
        assert name in left
    assert "Field_Survey_Reports_backup_20200102.xlsx" in left
    assert "Field_Survey_Reports_backup_20220303.xlsx" in left
    assert "Field_Survey_Reports_backup_20261112.xlsx" in left
    assert beside.exists() and book.exists()


def test_each_workbook_has_its_own_backups(book):
    other = book.with_name("Withdrawal_Reports.xlsx")
    other.write_bytes(b"withdrawals")
    for offset in range(3):
        b.backup_before_save(book, keep=1, today=DAY + timedelta(offset))
        b.backup_before_save(other, keep=3, today=DAY + timedelta(offset))
    assert len(b.list_backups(book)) == 1
    assert len(b.list_backups(other)) == 3


def test_failed_copy_raises_and_leaves_everything_as_it_was(book,
                                                            monkeypatch):
    b.backup_before_save(book, today=DAY)

    def no_space(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(b.shutil, "copy2", no_space)
    with pytest.raises(b.BackupError, match="disk full"):
        b.backup_before_save(book, today=DAY + timedelta(days=1))
    assert book.read_bytes() == b"workbook as it was this morning"
    assert len(b.list_backups(book)) == 1                 # nothing removed
    assert not list((book.parent / "Backups").glob("*.tmp"))


def test_failed_swap_removes_the_temporary_file(book, monkeypatch):
    def locked(source, target):
        raise PermissionError("in use")

    monkeypatch.setattr(b.os, "replace", locked)
    with pytest.raises(b.BackupError):
        b.backup_before_save(book, today=DAY)
    assert names(book.parent / "Backups") == []


def test_backup_that_cannot_be_removed_does_not_stop_the_save(
        book, monkeypatch):
    for offset in range(3):
        b.backup_before_save(book, keep=14, today=DAY + timedelta(offset))
    from pathlib import Path
    real = Path.unlink

    def stubborn(self, *args, **kwargs):
        if self.name.endswith("_backup_20261112.xlsx"):
            raise PermissionError("open in Excel")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", stubborn)
    result = b.backup_before_save(book, keep=1, today=DAY + timedelta(2))
    assert [p.name[-13:-5] for p in result["removed"]] == ["20261113"]
    assert result["kept"] == 2
