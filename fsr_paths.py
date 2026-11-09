"""Canonical project-data paths and managed workbook sidecar routing."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_ROOT = PROJECT_ROOT / "data"
SCHEMA_DIR = DATA_ROOT / "schema"
JSON_DIR = DATA_ROOT / "json"
EXCEL_DIR = DATA_ROOT / "excel"

# The Withdrawal workbook lives beside the active workbook, so Demo Mode, test
# sandboxes and a workbook chosen with "Change Excel File" each keep their own.
WITHDRAWAL_WORKBOOK_NAME = "Withdrawal_Reports.xlsx"
PO_MASTER_NAME = "PO_Master.xlsx"
WITHDRAWN_ITEM_NAME = "Withdrawn_Item.xlsx"


def withdrawal_workbook_path(active_workbook, required_root=None):
    """The Withdrawal workbook beside `active_workbook`. Raises ValueError
    when `active_workbook` is that file, or when the result would fall outside
    `required_root` (Demo Mode must stay inside its demo folder)."""
    active = Path(active_workbook).resolve()
    path = active.with_name(WITHDRAWAL_WORKBOOK_NAME)
    if path == active:
        raise ValueError(
            f"{WITHDRAWAL_WORKBOOK_NAME} cannot be used as the main Excel file.")
    if required_root is not None:
        root = Path(required_root).resolve()
        if root != path.parent and root not in path.parents:
            raise ValueError(
                f"The Withdrawal workbook would be created outside {root}:\n"
                f"{path}")
    return path


def configure_data_dirs(data_root, json_dir=None, excel_dir=None):
    """Set data roots for the active install, test sandbox, or demo profile."""
    global DATA_ROOT, JSON_DIR, EXCEL_DIR
    DATA_ROOT = Path(data_root)
    JSON_DIR = Path(json_dir) if json_dir is not None else DATA_ROOT / "json"
    EXCEL_DIR = Path(excel_dir) if excel_dir is not None else DATA_ROOT / "excel"


def json_dir_for_workbook(workbook_path):
    """Use the matching JSON tree for managed workbooks, otherwise stay local."""
    workbook_parent = Path(workbook_path).resolve().parent
    excel_root = EXCEL_DIR.resolve()
    try:
        relative_parent = workbook_parent.relative_to(excel_root)
    except ValueError:
        return workbook_parent
    return JSON_DIR / relative_parent
