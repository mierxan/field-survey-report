"""
MySQL storage for the Field Survey Report program (optional).

Setup:  pip install mysql-connector-python
        copy data/json/db_config.example.json to
        data/json/private/db_config.json and fill in your login.
If db_config.json is missing (or "enabled" is false) the program works
exactly as before and just uses Excel.

The MySQL password is kept in the Windows Credential Manager, not in
db_config.json: the file then has "password": "" and
"password_store": "credential-manager". A password found in the file is
moved there at start (move_password_to_store), and the file is blanked only
after the password was read back from the Credential Manager. Where there
is no Credential Manager the password stays in the file as before.
"""

import hashlib
import json
import logging
import os
from datetime import datetime

from fsr_storage import control_sort_key, split_quantity_unit
import fsr_paths
import fsr_secrets

CONFIG_FILE = fsr_paths.JSON_DIR / "private" / "db_config.json"
DATE_FORMAT = "%d-%b-%Y"
OLD_DATE_FORMAT = "%d-%m-%Y"
OTHER_REMARKS = "Other Important Remarks"
FINDINGS = "Findings and Remarks"

ITEM_COLUMNS = [                      # (key in the form data, MySQL column)
    ("Description of Goods", "description"), ("PO Number", "po_number"),
    ("Packaging", "packaging"), ("Quantity", "quantity"),
    ("Dimensions", "dimensions"), ("Weights", "weights"),
    ("Unit Price", "unit_price"), ("Total Price", "total_price"),
    ("Findings", "findings"),
]
# Warehouse links (Cargo ID, Receiving Ref). Older databases do not have
# these columns yet: the program then saves everything else, and
# upgrade_schema() (Settings > Upgrade MySQL tables) adds them.
# UOM, Currency and Container / Truck No. were added the same way later.
LINK_COLUMNS = [("Cargo ID", "cargo_id"), ("Receiving Ref", "receiving_ref"),
                ("UOM", "uom"), ("Currency", "currency"),
                ("Container / Truck No.", "unit_no")]
LINK_COLUMN_SQL = {"cargo_id": "VARCHAR(100) NULL",
                   "receiving_ref": "VARCHAR(100) NULL",
                   "uom": "VARCHAR(30) NULL",
                   "currency": "VARCHAR(3) NULL",
                   "unit_no": "VARCHAR(100) NULL"}
MASTER_KEYS = ["consignee_list", "supplier_list", "broker_list", "hauler_list",
               "location_list", "destination_list", "country_of_origin_list"]


ACCESS_DENIED = 1142                # the login may not run this command

log = logging.getLogger("fsr")
PASSWORD_STORE = "credential-manager"   # value of "password_store"
SECRET_STORE = None                 # None = the store of this PC (tests set one)


def _secret_store():
    return SECRET_STORE or fsr_secrets.default_store(CONFIG_FILE.parent)


def _secret_name():
    """One entry per db_config.json, so Demo Mode, a test folder and the
    real program never share a password."""
    return "mysql-" + hashlib.sha256(
        str(CONFIG_FILE.resolve()).casefold().encode("utf-8")
    ).hexdigest()[:16]


def _with_password(config):
    """`config` as the program uses it: with the password taken from the
    protected store when the file says it is kept there."""
    if config.get("password_store") != PASSWORD_STORE:
        return config
    config = {k: v for k, v in config.items() if k != "password_store"}
    try:
        password = _secret_store().get(_secret_name())
    except fsr_secrets.SecretStoreError as error:
        log.warning("The MySQL password could not be read: %s", error)
        password = None
    if password is None:
        log.warning("The MySQL password is not in the Credential Manager of "
                    "this Windows login. Type it again in MySQL Settings.")
    config["password"] = password or ""
    return config


def load_config():
    """The settings dict, or None when MySQL is not set up / turned off."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            config = json.load(file)
    except (OSError, ValueError):
        return None
    if not isinstance(config, dict) or not config.get("enabled", True):
        return None
    return _with_password(config) if config.get("user") else None


def is_enabled():
    return load_config() is not None


def read_raw_config():
    """The settings file as it is (also when MySQL is turned off)."""
    defaults = {"enabled": False, "host": "localhost", "port": 3306,
                "user": "fsr_app", "password": "", "database": "field_survey"}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            defaults.update(data)
    except (OSError, ValueError):
        pass
    return _with_password(defaults)


def _protect_password(password):
    """Put the password into the protected store. True only when it is
    there AND was read back unchanged; otherwise it must stay in the file."""
    store = _secret_store()
    if not getattr(store, "protected", False):
        return False
    try:
        store.set(_secret_name(), password)
        return store.get(_secret_name()) == password
    except fsr_secrets.SecretStoreError as error:
        log.warning("The MySQL password stays in db_config.json: the "
                    "Credential Manager could not be used (%s)", error)
        return False


def write_config(config):
    """Save the settings. `config["password"]` is the real password; it goes
    to the Credential Manager when there is one, else into the file."""
    data = {k: v for k, v in config.items() if k != "password_store"}
    password = str(data.get("password") or "")
    if password and _protect_password(password):
        data["password"] = ""
        data["password_store"] = PASSWORD_STORE
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    try:
        with open(temp, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)
        os.replace(temp, CONFIG_FILE)
    finally:
        if temp.exists():
            temp.unlink()


def move_password_to_store():
    """Run at start: a password still written in db_config.json is moved to
    the Credential Manager. Returns "moved", "kept" (no Credential Manager,
    or it failed - the file is unchanged) or "nothing" (no password in the
    file)."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        return "nothing"
    if not isinstance(data, dict) or not str(data.get("password") or ""):
        return "nothing"
    if data.get("password_store") == PASSWORD_STORE:
        return "nothing"
    if not _protect_password(str(data["password"])):
        return "kept"
    write_config(data)          # read back above: now blank it in the file
    return "moved"


def connect(config=None):
    config = config or load_config()
    if config is None:
        raise RuntimeError("MySQL is not set up (db_config.json).")
    try:
        import mysql.connector
    except ImportError as error:
        raise RuntimeError(
            "Install the MySQL driver:  pip install mysql-connector-python"
        ) from error
    return mysql.connector.connect(
        host=config.get("host", "localhost"),
        port=int(config.get("port", 3306)),
        user=config["user"],
        password=config.get("password", ""),
        database=config.get("database", "field_survey"),
        charset="utf8mb4",
        connection_timeout=int(config.get("timeout", 8)),
    )


def explain_error(error):
    """Plain-language reason for a MySQL connection / save error."""
    code = getattr(error, "errno", None)
    config = load_config() or {}
    user = config.get("user", "?")
    if code == 1045:
        return (f"MySQL refused the login for user '{user}'.\n"
                "Check that the user name and password in MySQL Settings are "
                "exactly the ones in MySQL (the user is spelled f-s-r_app). "
                "On a new PC or Windows login the password must be typed "
                "again there.\n"
                f"Original message: {error}")
    if code in (2003, 2002, 2005):
        return ("The program cannot reach the MySQL server.\n"
                "Make sure the MySQL80 service is running (Windows: Services > "
                "MySQL80 > Start) and that host/port in db_config.json are right.\n"
                f"Original message: {error}")
    if code == 1049:
        return ("The database does not exist yet. Run "
                "data/schema/field_survey_schema.sql "
                f"in MySQL Workbench first.\nOriginal message: {error}")
    if code in (1146, 1054):
        return ("A table or column is missing. Run the latest "
                "data/schema/field_survey_schema.sql in Workbench.\n"
                f"Original message: {error}")
    if code == ACCESS_DENIED:
        return (f"The MySQL login '{user}' is not allowed to do this. The "
                "program's login normally only reads and writes rows; changing "
                "tables needs an admin login such as root.\n"
                f"Original message: {error}")
    return str(error)


# Connection could not be made / was lost: normal on a PC that is offline
# or whose MySQL service is stopped.
UNREACHABLE = (2002, 2003, 2005, 2006, 2013, 2055)


def is_unreachable(error):
    """True when `error` only says that the MySQL server cannot be reached
    (as opposed to a refused login, a missing table, bad data ...)."""
    return getattr(error, "errno", None) in UNREACHABLE


def test_connection(config=None):
    """(ok, message) - used by the 'Test MySQL' button and test_mysql.py."""
    config = config or load_config()
    if config is None:
        return False, "db_config.json is missing or has no user."
    try:
        conn = connect(config)
    except Exception as error:
        return False, explain_error(error)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM reports")
        count = cur.fetchone()[0]
        cur.close()
    except Exception as error:
        return False, explain_error(error)
    finally:
        conn.close()
    return True, f"Connected. The database has {count} report(s)."


CONTROL_NO_LENGTH = 40


# ---------- value helpers ----------

def text(value, limit=None):
    value = str(value or "").strip()
    if not value:
        return None
    return value[:limit] if limit else value


def sql_date(value):
    value = str(value or "").strip()
    for pattern in (DATE_FORMAT, OLD_DATE_FORMAT):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


# ---------- save ----------

def item_columns(cur):
    """The Item List columns this database has: the nine form columns plus
    the warehouse link columns that exist."""
    cur.execute("SHOW COLUMNS FROM item_lines")
    present = {row[0] for row in cur.fetchall()}
    return ITEM_COLUMNS + [c for c in LINK_COLUMNS if c[1] in present]


def missing_link_columns(connection=None):
    own = connection is None
    conn = connection or connect()
    try:
        cur = conn.cursor()
        have = {col for _, col in item_columns(cur)}
        cur.close()
        return [col for _, col in LINK_COLUMNS if col not in have]
    finally:
        if own:
            conn.close()


def short_control_tables(connection=None):
    """Tables whose control_no is too short for FSR-<initials>-YYYYMM-NNNN."""
    own = connection is None
    conn = connection or connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT c.table_name FROM information_schema.columns c "
            "JOIN information_schema.tables t ON t.table_schema = c.table_schema "
            "AND t.table_name = c.table_name AND t.table_type = 'BASE TABLE' "
            "WHERE c.table_schema = DATABASE() AND c.column_name = 'control_no' "
            f"AND c.character_maximum_length < {CONTROL_NO_LENGTH}")
        tables = [row[0] for row in cur.fetchall()]
        cur.close()
        return tables
    finally:
        if own:
            conn.close()


def _widen_control_no(conn, tables):
    """Foreign keys must match the column they point to, so they are dropped,
    the columns widened, and the keys put back. Rows are kept."""
    cur = conn.cursor()
    cur.execute(
        "SELECT table_name, constraint_name FROM "
        "information_schema.key_column_usage WHERE table_schema = DATABASE() "
        "AND referenced_table_name = 'reports' "
        "AND referenced_column_name = 'control_no'")
    keys = cur.fetchall()
    for table, name in keys:
        cur.execute(f"ALTER TABLE {table} DROP FOREIGN KEY {name}")
    for table in tables:
        cur.execute(f"ALTER TABLE {table} MODIFY control_no "
                    f"VARCHAR({CONTROL_NO_LENGTH}) NOT NULL")
    for table, name in keys:
        cur.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY "
                    "(control_no) REFERENCES reports (control_no) "
                    "ON DELETE CASCADE ON UPDATE CASCADE")
    cur.close()


def upgrade_schema(connection=None):
    """Add the warehouse link columns to item_lines and widen control_no
    (existing rows are kept). Returns what changed. Needs the ALTER and
    REFERENCES privileges, which the program's own login does not have."""
    own = connection is None
    conn = connection or connect()
    try:
        added = []
        for col in missing_link_columns(conn):
            cur = conn.cursor()
            cur.execute(f"ALTER TABLE item_lines ADD COLUMN {col} "
                        f"{LINK_COLUMN_SQL[col]}")
            cur.close()
            added.append(col)
        if added:
            cur = conn.cursor()
            try:
                cur.execute("CREATE INDEX idx_item_cargo ON item_lines "
                            "(cargo_id)")
            except Exception:
                pass                # index exists / not allowed: not needed
            cur.close()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM reports")
        if "item_form" not in {row[0] for row in cur.fetchall()}:
            cur.execute("ALTER TABLE reports ADD COLUMN item_form "
                        "VARCHAR(20) NULL")
            added.append("item_form")
        cur.close()
        short = short_control_tables(conn)
        if short:
            _widen_control_no(conn, short)
            added.append("control_no")
        conn.commit()
        return added
    finally:
        if own:
            conn.close()


def upgrade_schema_as(user, password):
    """upgrade_schema() with a one-time admin login, which is never saved."""
    conn = connect({**load_config(), "user": user, "password": password})
    try:
        return upgrade_schema(conn)
    finally:
        conn.close()


def save_report(data, connection=None):
    """Insert or update ONE report (all its lines) in a single transaction.
    `data` has the same shape as collect_report_data(). Returns a list of
    notes (e.g. link columns this database cannot store yet)."""
    own = connection is None
    conn = connection or connect()
    try:
        notes = _write_report(conn, data)
        conn.commit()
        return notes
    except Exception:
        conn.rollback()
        raise
    finally:
        if own:
            conn.close()


def _write_report(conn, data):
    cur = conn.cursor()
    control = data["control_no"]
    gi = data["general_information"]
    sc = data["inspection_schedule"]
    tr = data["transport_details"]
    dc = data["documents_used"]
    gt = data.get("goods_types") or {}

    cur.execute(
        """
        INSERT INTO reports (
            control_no, so_number, inspection_date, consignee, supplier,
            brokerage, hauler, location, destination, country_of_origin,
            activity, commenced_date, commenced_time, completion_date,
            completion_time, vessel_carrier, vehicle_type,
            vehicle_plate_number, invoice_number, po_number, jo_number,
            gatepass_number, bl_awb_number, dr_number, other_documents,
            cargo_condition, goods_new, goods_used, goods_food_stuffs,
            goods_vehicle, goods_pharma_chemicals, goods_others,
            goods_others_text)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            so_number=VALUES(so_number), inspection_date=VALUES(inspection_date),
            consignee=VALUES(consignee), supplier=VALUES(supplier),
            brokerage=VALUES(brokerage), hauler=VALUES(hauler),
            location=VALUES(location), destination=VALUES(destination),
            country_of_origin=VALUES(country_of_origin),
            activity=VALUES(activity), commenced_date=VALUES(commenced_date),
            commenced_time=VALUES(commenced_time),
            completion_date=VALUES(completion_date),
            completion_time=VALUES(completion_time),
            vessel_carrier=VALUES(vessel_carrier),
            vehicle_type=VALUES(vehicle_type),
            vehicle_plate_number=VALUES(vehicle_plate_number),
            invoice_number=VALUES(invoice_number), po_number=VALUES(po_number),
            jo_number=VALUES(jo_number), gatepass_number=VALUES(gatepass_number),
            bl_awb_number=VALUES(bl_awb_number), dr_number=VALUES(dr_number),
            other_documents=VALUES(other_documents),
            cargo_condition=VALUES(cargo_condition),
            goods_new=VALUES(goods_new), goods_used=VALUES(goods_used),
            goods_food_stuffs=VALUES(goods_food_stuffs),
            goods_vehicle=VALUES(goods_vehicle),
            goods_pharma_chemicals=VALUES(goods_pharma_chemicals),
            goods_others=VALUES(goods_others),
            goods_others_text=VALUES(goods_others_text)
        """,
        (
            control, text(gi["so_number"], 100), sql_date(gi["inspection_date"]),
            text(gi["consignee"], 200), text(gi["supplier"], 200),
            text(gi["brokerage"], 200), text(gi["hauler"], 200),
            text(gi["location"], 200), text(gi["destination"], 200),
            text(gi["country_of_origin"], 100),
            text(sc["activity"], 50), sql_date(sc["commenced_date"]),
            text(sc["commenced_time"], 5), sql_date(sc["completion_date"]),
            text(sc["completion_time"], 5),
            text(tr["vessel_carrier"], 200), text(tr["vehicle_type"], 100),
            text(tr["vehicle_plate_number"], 50),
            text(dc["invoice_number"], 100), text(dc["po_number"], 100),
            text(dc["jo_number"], 100), text(dc["gatepass_number"], 100),
            text(dc["bl_awb_number"], 100), text(dc["dr_number"], 100),
            text(dc["other_documents"], 255),
            "Bad Order" if data.get("cargo_condition") == "Bad Order"
            else "Good Order",
            int(bool(gt.get("new"))), int(bool(gt.get("used"))),
            int(bool(gt.get("food_stuffs"))), int(bool(gt.get("vehicle"))),
            int(bool(gt.get("pharma_chemicals"))), int(bool(gt.get("others"))),
            text(gt.get("others_text"), 255),
        ),
    )

    # Child rows are simply rewritten (inside the same transaction).
    # Local/Import and Containerized columns (added later). An older
    # database without them still saves everything else.
    try:
        cur.execute(
            "UPDATE reports SET shipment_type = %s, container_type = %s "
            "WHERE control_no = %s",
            (text(tr.get("shipment_type"), 20),
             text(tr.get("container_type"), 30), control))
    except Exception:
        pass
    # Item List form (Default / Containerized / Loading), added later too.
    try:
        cur.execute("UPDATE reports SET item_form = %s WHERE control_no = %s",
                    (text(data.get("item_form"), 20) or "Default", control))
    except Exception:
        pass

    for table in ("declared_goods", "item_lines", "remarks", "incident_reports"):
        cur.execute(f"DELETE FROM {table} WHERE control_no = %s", (control,))
    # incident_lines are removed automatically (ON DELETE CASCADE).

    columns_used = item_columns(cur)
    notes = []
    missing = [key for key, col in LINK_COLUMNS
               if (key, col) not in columns_used and any(
                   str(row.get(key) or "").strip()
                   for section in data.get("item_lists") or []
                   for row in section.get("rows") or [])]
    if missing:
        notes.append("The MySQL table item_lines has no "
                     + " / ".join(missing) + " columns yet, so those were "
                     "saved to Excel only. Use Settings > Upgrade MySQL "
                     "tables.")

    line = 0
    for item in data.get("declared_goods") or []:
        if not any(str(item.get(k) or "").strip()
                   for k in ("description", "quantity", "packaging")):
            continue
        line += 1
        cur.execute(
            "INSERT INTO declared_goods (control_no, line_no, description, "
            "quantity, packaging) VALUES (%s,%s,%s,%s,%s)",
            (control, line, text(item.get("description"), 500),
             text(item.get("quantity"), 100), text(item.get("packaging"), 100)))

    for number, section in enumerate(data.get("item_lists") or [], start=1):
        name = text(section.get("name"), 100) or f"Item List {number}"
        line = 0
        for row in section.get("rows") or []:
            values = [text(row.get(key), 500) for key, _ in columns_used]
            if not any(values):
                continue
            line += 1
            columns = ", ".join(col for _, col in columns_used)
            cur.execute(
                f"INSERT INTO item_lines (control_no, item_list, line_no, "
                f"{columns}) VALUES (%s,%s,%s,{','.join(['%s'] * len(values))})",
                (control, name, line, *values))

    for section, lines in ((OTHER_REMARKS, data.get("other_important_remarks")),
                           (FINDINGS, data.get("findings_and_remarks"))):
        line = 0
        for remark in lines or []:
            if not str(remark or "").strip():
                continue
            line += 1
            cur.execute(
                "INSERT INTO remarks (control_no, section, line_no, remark) "
                "VALUES (%s,%s,%s,%s)", (control, section, line, str(remark).strip()))

    if data.get("cargo_condition") == "Bad Order":
        number = 0
        for report in data.get("incident_reports") or []:
            lines = [str(t).strip() for t in report.get("lines") or []
                     if str(t).strip()][:15]
            if not lines:
                continue
            number += 1
            cur.execute(
                "INSERT INTO incident_reports (control_no, report_no, vessel, "
                "voyage, client, so_number, port, incident_date, operation) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (control, number, text(report.get("vessel"), 200),
                 text(report.get("voyage"), 100), text(report.get("client"), 200),
                 text(report.get("so_number"), 100), text(report.get("port"), 200),
                 sql_date(report.get("date")), text(report.get("operation"), 200)))
            incident_id = cur.lastrowid
            for index, line_text in enumerate(lines, start=1):
                cur.execute(
                    "INSERT INTO incident_lines (incident_report_id, line_no, "
                    "line_text) VALUES (%s,%s,%s)", (incident_id, index, line_text))
    cur.close()
    return notes


def save_master_lists(master_data, connection=None):
    """Add any new names of the master lists (never deletes)."""
    own = connection is None
    conn = connection or connect()
    try:
        cur = conn.cursor()
        for key in MASTER_KEYS:
            for name in master_data.get(key, []):
                name = str(name).strip()
                if name:
                    cur.execute("INSERT IGNORE INTO master_list (list_name, "
                                "item_name) VALUES (%s,%s)", (key, name[:200]))
        conn.commit()
        cur.close()
    finally:
        if own:
            conn.close()


def sync_reports(reports):
    """Save many reports (a list of data dicts). Returns (saved, errors)."""
    conn = connect()
    saved, errors = 0, []
    try:
        for data in reports:
            try:
                save_report(data, conn)
                saved += 1
            except Exception as error:
                errors.append(f"{data.get('control_no')}: {explain_error(error)}")
    finally:
        conn.close()
    return saved, errors


# ---------- read back (open / edit a report from MySQL) ----------

def _show_date(value):
    return value.strftime(DATE_FORMAT) if hasattr(value, "strftime") else ""


def _show(value):
    """Database value -> text for an entry box ('12.000' -> '12')."""
    if value is None:
        return ""
    if hasattr(value, "as_tuple"):                      # Decimal
        value = format(value.normalize(), "f")
    return str(value)


def list_reports(connection=None):
    """[(control #, SO number, inspection date, consignee, last saved), ...]
    newest first - the same shape as the Excel list."""
    own = connection is None
    conn = connection or connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT control_no, so_number, inspection_date, consignee, "
            "last_saved FROM reports ORDER BY control_no DESC")
        rows = [(
            control, _show(so), _show_date(day), _show(consignee),
            last.strftime("%d-%b-%Y %H:%M") if hasattr(last, "strftime") else "",
        ) for control, so, day, consignee, last in cur.fetchall()]
        cur.close()
        # Initials in a Control # would otherwise sort by inspector, not by age.
        rows.sort(key=lambda row: control_sort_key(row[0]), reverse=True)
        return rows
    finally:
        if own:
            conn.close()


def load_report(control_no, connection=None):
    """One report in the same shape as collect_report_data()."""
    own = connection is None
    conn = connection or connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT so_number, inspection_date, consignee, supplier, brokerage, "
            "hauler, location, destination, country_of_origin, activity, "
            "commenced_date, commenced_time, completion_date, completion_time, "
            "vessel_carrier, vehicle_type, vehicle_plate_number, invoice_number, "
            "po_number, jo_number, gatepass_number, bl_awb_number, dr_number, "
            "other_documents, cargo_condition, goods_new, goods_used, "
            "goods_food_stuffs, goods_vehicle, goods_pharma_chemicals, "
            "goods_others, goods_others_text FROM reports WHERE control_no = %s",
            (control_no,))
        r = cur.fetchone()
        if r is None:
            raise ValueError(f"Control # {control_no} was not found in MySQL.")
        extra = ("", "")
        try:
            cur.execute("SELECT shipment_type, container_type FROM reports "
                        "WHERE control_no = %s", (control_no,))
            row = cur.fetchone()
            extra = (_show(row[0]), _show(row[1]))
        except Exception:
            pass                    # older database without the columns
        item_form = "Default"
        try:
            cur.execute("SELECT item_form FROM reports WHERE control_no = %s",
                        (control_no,))
            item_form = _show(cur.fetchone()[0]) or "Default"
        except Exception:
            pass                    # older database without the column
        (so, insp, consignee, supplier, brokerage, hauler, location,
         destination, country, activity, c_date, c_time, e_date, e_time,
         vessel, vtype, plate, invoice, po, jo, gatepass, bl, dr, other_docs,
         condition, g_new, g_used, g_food, g_vehicle, g_pharma, g_others,
         g_others_text) = r

        cur.execute("SELECT description, quantity, packaging FROM "
                    "declared_goods WHERE control_no = %s ORDER BY line_no",
                    (control_no,))
        declared = [{"description": _show(a), "quantity": _show(b),
                     "packaging": _show(c)} for a, b, c in cur.fetchall()]

        columns_used = item_columns(cur)
        cur.execute("SELECT item_list, " + ", ".join(c for _, c in columns_used)
                    + " FROM item_lines WHERE control_no = %s "
                    "ORDER BY id", (control_no,))
        # Rows were saved list by list, line by line, so ORDER BY id keeps
        # "Item List 2" before "Item List 10" (text order would not).
        lists = {}
        for name, *values in cur.fetchall():
            row = {key: "" for key, _ in ITEM_COLUMNS + LINK_COLUMNS}
            row.update({key: _show(value)
                        for (key, _), value in zip(columns_used, values)})
            lists.setdefault(name, []).append(row)
        item_lists = [{"name": name, "rows": rows}
                      for name, rows in lists.items()]

        remarks = {OTHER_REMARKS: [], FINDINGS: []}
        cur.execute("SELECT section, remark FROM remarks WHERE control_no = %s "
                    "ORDER BY section, line_no", (control_no,))
        for section, remark in cur.fetchall():
            remarks.setdefault(section, []).append(_show(remark))

        cur.execute("SELECT id, vessel, voyage, client, so_number, port, "
                    "incident_date, operation FROM incident_reports "
                    "WHERE control_no = %s ORDER BY report_no", (control_no,))
        incidents = []
        for iid, vessel_, voyage, client, iso, port, idate, operation in cur.fetchall():
            incidents.append({
                "_id": iid, "vessel": _show(vessel_), "voyage": _show(voyage),
                "client": _show(client), "so_number": _show(iso),
                "port": _show(port), "date": _show_date(idate),
                "operation": _show(operation), "lines": []})
        for report in incidents:
            cur.execute("SELECT line_text FROM incident_lines WHERE "
                        "incident_report_id = %s ORDER BY line_no",
                        (report.pop("_id"),))
            report["lines"] = [_show(t[0]) for t in cur.fetchall()]
        cur.close()
    finally:
        if own:
            conn.close()

    return {
        "control_no": control_no,
        "cargo_condition": _show(condition) or "Good Order",
        "item_form": item_form,
        "goods_types": {
            "new": bool(g_new), "used": bool(g_used),
            "food_stuffs": bool(g_food), "vehicle": bool(g_vehicle),
            "pharma_chemicals": bool(g_pharma), "others": bool(g_others),
            "others_text": _show(g_others_text)},
        "incident_reports": incidents,
        "incident_error": None,
        "general_information": {
            "so_number": _show(so), "inspection_date": _show_date(insp),
            "consignee": _show(consignee), "supplier": _show(supplier),
            "brokerage": _show(brokerage), "hauler": _show(hauler),
            "location": _show(location), "destination": _show(destination),
            "country_of_origin": _show(country)},
        "inspection_schedule": {
            "activity": _show(activity), "commenced_date": _show_date(c_date),
            "commenced_time": _show(c_time), "completion_date": _show_date(e_date),
            "completion_time": _show(e_time)},
        "transport_details": {
            "vessel_carrier": _show(vessel), "vehicle_type": _show(vtype),
            "vehicle_plate_number": _show(plate),
            "shipment_type": extra[0], "container_type": extra[1]},
        "documents_used": {
            "invoice_number": _show(invoice), "po_number": _show(po),
            "jo_number": _show(jo), "gatepass_number": _show(gatepass),
            "bl_awb_number": _show(bl), "dr_number": _show(dr),
            "other_documents": _show(other_docs)},
        "declared_goods": declared,
        "other_important_remarks": remarks[OTHER_REMARKS],
        "item_lists": item_lists,
        "findings_and_remarks": remarks[FINDINGS],
    }


def load_all_reports(connection=None):
    """Every report in the database (same shape as load_report()), for the
    dashboard and the warehouse monitoring."""
    own = connection is None
    conn = connection or connect()
    try:
        return [load_report(row[0], conn) for row in list_reports(conn)]
    finally:
        if own:
            conn.close()


# ---------- weekly summary report ----------

def weekly_summary(first_day, last_day, connection=None):
    """One row per item line (or one row for a report without items) of every
    report whose inspection date is between the two dates (inclusive).
    Each row has the 28 fields of the Weekly Summary, as text."""
    own = connection is None
    conn = connection or connect()
    try:
        cur = conn.cursor()
        have = {col for _, col in item_columns(cur)}
        uom = "i.uom" if "uom" in have else "NULL"
        currency = "i.currency" if "currency" in have else "NULL"
        cur.execute("SHOW COLUMNS FROM reports")
        shipment = ("r.shipment_type"
                    if "shipment_type" in {row[0] for row in cur.fetchall()}
                    else "NULL")
        cur.execute(
            "SELECT r.so_number, r.inspection_date, r.activity, "
            f"{shipment}, r.supplier, r.brokerage, "
            "r.hauler, r.destination, r.country_of_origin, r.invoice_number, "
            "r.po_number, r.jo_number, r.gatepass_number, r.bl_awb_number, "
            "r.dr_number, r.vehicle_type, r.vehicle_plate_number, "
            f"i.description, i.po_number, i.packaging, i.quantity, {uom}, "
            f"i.dimensions, i.weights, {currency}, i.unit_price, "
            "i.total_price, r.cargo_condition "
            "FROM reports r LEFT JOIN item_lines i ON i.control_no = r.control_no "
            "WHERE r.inspection_date BETWEEN %s AND %s "
            "ORDER BY r.inspection_date, r.control_no, i.item_list, i.id",
            (first_day, last_day))
        rows = []
        for row in cur.fetchall():
            row = list(row)
            row[1] = _show_date(row[1])
            row = [_show(value) for value in row]
            row[20], row[21] = split_quantity_unit(row[20], row[21])
            rows.append(row)
        cur.close()
        return rows
    finally:
        if own:
            conn.close()


def search_index(connection=None):
    """{control #: {"so": [...], "bl": [...], "po": [...], "dr": [...],
    "gatepass": [...], "description": [...]}} - what the Open Saved Report
    search looks through (PO covers the report PO and every item PO;
    Description covers the declared goods and the item lists)."""
    own = connection is None
    conn = connection or connect()
    try:
        cur = conn.cursor()
        index = {}

        def entry(control):
            return index.setdefault(control, {
                "so": [], "bl": [], "po": [], "dr": [], "gatepass": [],
                "description": []})

        cur.execute("SELECT control_no, so_number, bl_awb_number, po_number, "
                    "dr_number, gatepass_number FROM reports")
        for control, so, bl, po, dr, gatepass in cur.fetchall():
            item = entry(control)
            for key, value in (("so", so), ("bl", bl), ("po", po),
                               ("dr", dr), ("gatepass", gatepass)):
                if _show(value):
                    item[key].append(_show(value))
        cur.execute("SELECT control_no, description, po_number "
                    "FROM item_lines")
        for control, description, po in cur.fetchall():
            item = entry(control)
            if _show(description):
                item["description"].append(_show(description))
            if _show(po):
                item["po"].append(_show(po))
        cur.execute("SELECT control_no, description FROM declared_goods")
        for control, description in cur.fetchall():
            if _show(description):
                entry(control)["description"].append(_show(description))
        cur.close()
        return index
    finally:
        if own:
            conn.close()
