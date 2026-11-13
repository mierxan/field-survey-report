"""
Field Survey Report  -  modernised version

Requirements (pip install ...):
    ttkbootstrap openpyxl
Optional (PDF / print):
    pypdf, pywin32 (Windows + Microsoft Excel)  or  LibreOffice

Files expected next to this script:
    data/json/master_list.json and data/excel/*.xlsx
Files created in data/:
    json/private/settings.json, json/private/users.json, excel/*.xlsx
"""

import json
import logging
import calendar
import copy
import os
import socket
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter
from datetime import date, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import ttk, PhotoImage, messagebox, filedialog
from tkinter import font as tkfont
from types import SimpleNamespace

try:
    import ttkbootstrap as tb
except ImportError:
    print("This program needs ttkbootstrap.\nInstall it with:  pip install ttkbootstrap")
    sys.exit(1)

try:
    from ttkbootstrap.style import ThemeDefinition
except ImportError:
    ThemeDefinition = None
# ToolTip / ToastNotification live in ttkbootstrap (2.x) or in
# ttkbootstrap.tooltip / ttkbootstrap.toast (1.x). Without them the program
# still works (no tooltips; the status bar shows the message).
try:
    from ttkbootstrap import ToolTip
except ImportError:
    try:
        from ttkbootstrap.tooltip import ToolTip  # pyright: ignore[reportMissingImports]
    except ImportError:
        ToolTip = None

try:
    from ttkbootstrap import ToastNotification
except ImportError:
    try:
        from ttkbootstrap.toast import ToastNotification  # pyright: ignore[reportMissingImports]
    except ImportError:
        ToastNotification = None

# Excel support: pip install openpyxl
try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None

# Optional MySQL storage (db_mysql.py + private db_config.json).
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import db_mysql
except ImportError:
    db_mysql = None

# Field definitions + Excel storage (fsr_storage.py beside this script).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fsr_paths
import fsr_edition                 # Owner app (Excel + MySQL) or User app
import fsr_backup                  # daily backup copy of the workbook
import fsr_import                  # Master Data files from the sites/phones
import fsr_master_export           # one Master Data file for the owner
import fsr_mysql_guard             # never overwrite another copy's report
import fsr_mysql_sender            # MySQL in the background
import fsr_save_journal            # finishes a save that stopped halfway
import fsr_store                   # the ONE storage interface
from fsr_forms import (  # the official report forms (moved)
    convert_form_to_pdf,  # noqa: F401 - tests reach it as g["convert_form_to_pdf"]
    print_name,
    remark_capacity,
    FORM_FOLDER_NAME,
    parse_any_date,
    form_date,
    create_report_form,
    item_forms_to_print,
    create_cargo_form,
    create_incident_form,
    merge_workbooks,
    report_workbook_path,
    make_report_pdf,
    send_to_printer,
)
import fsr_withdrawal              # PO-linked Withdrawal reports
import fsr_withdrawal_ui
from fsr_withdrawal_ui import WithdrawalPanel
from fsr_storage import (          # plain data layer
    Workbook,
    CHOICE_VALUES, CONDITION_BAD, CONDITION_GOOD,
    DATE_FORMAT, DOCUMENT_FIELDS, empty_goods_types,
    GOODS_TYPES, INCIDENT_HEADER_FIELDS,
    INCIDENT_MAX_LINES, incident_title, ITEM_HEADERS, ITEM_LINE_HEADERS,
    ITEM_FORM_CONTAINERIZED, ITEM_FORM_DEFAULT, ITEM_FORM_LOADING,
    item_form_name, ITEM_FORMS, ITEM_LINK_HEADERS, UNIT_NO_HEADER,
    UNIT_NO_LABELS,
    CURRENCIES, split_quantity_unit, UOM_CHOICES,
    WEIGHT_UNIT_CHOICES,
    normalize_field, parse_date, recent_date_options, safe_filename, SCHEDULE_FIELDS,
    set_control_initials,
    to_number, TRANSPORT_FIELDS, TYPEABLE_CHOICES,
    write_json_atomic, same_key,
)

# Sign in / sign up (app_auth.py beside this script). Without it the
# program does not start - nobody gets in unsigned.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import app_auth
except ImportError:
    app_auth = None


# write_json_atomic() is in fsr_storage.py

def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings():
    try:
        write_json_atomic(SETTINGS_FILE, settings)
    except (OSError, TypeError):
        log.exception("Could not save settings")


def make_night_theme():
    """Register the dark navy theme (works with ttkbootstrap 1.x and 2.x).
    Returns True when it is available."""
    if ThemeDefinition is None:
        return False
    for options in ({"mode": "dark"}, {"themetype": "dark"}):
        try:
            style.register_theme(
                ThemeDefinition(NIGHT_THEME, dict(NIGHT_COLORS), **options)
            )
            return True
        except TypeError:
            continue            # other ttkbootstrap version: try the other name
        except Exception:
            log.exception("Night theme could not be registered")
            return False
    return False


def apply_window_icon():
    global logo
    try:
        if LOGO_ICO.exists() and sys.platform.startswith("win"):
            window.iconbitmap(default=str(LOGO_ICO))
    except tkinter.TclError:
        pass
    try:
        if logo is None:
            logo = PhotoImage(file=str(LOGO_PNG))
        window.iconphoto(True, logo)
    except tkinter.TclError:
        pass

# =====================================================
# SIGN IN  (the Field Survey Report opens only after signing in)
# =====================================================
def icon_for_dialog(dialog):
    try:
        if LOGO_ICO.exists() and sys.platform.startswith("win"):
            dialog.iconbitmap(str(LOGO_ICO))
        elif logo is not None:
            dialog.iconphoto(False, logo)
    except tkinter.TclError:
        pass


def title_prefix():
    if not TEST_COPY:
        return ""
    real = False
    if db_mysql is not None and MYSQL_ALLOWED:
        try:
            config = db_mysql.load_config()
            real = bool(config) and str(config.get(
                "database", db_mysql.PRODUCTION_DATABASE)).strip().lower() \
                == db_mysql.PRODUCTION_DATABASE and config.get(
                    db_mysql.ALLOW_REAL) is True
        except Exception:
            real = False
    return "TEST COPY (REAL DATABASE) - " if real else "TEST COPY - "


def center_window(win, width, height, top_margin=10):
    """Open the window at the top-center of any screen size."""
    screen_w = win.winfo_screenwidth()
    screen_h = win.winfo_screenheight()

    width = min(width, screen_w - 40)
    height = min(height, screen_h - 100)   # room for title bar + taskbar

    x = (screen_w - width) // 2
    y = top_margin
    win.geometry(f"{width}x{height}+{x}+{y}")


def log_unhandled(exc_type, exc_value, exc_tb):
    log.error("Unhandled error", exc_info=(exc_type, exc_value, exc_tb))
    messagebox.showerror(
        "Unexpected Error",
        f"Something went wrong:\n{exc_value}\n\n"
        f"Details were written to:\n{LOG_FILE}",
        parent=window
    )


def initial_excel_path():
    saved = settings.get("excel_path")
    if saved and Path(saved).parent.exists():
        return Path(saved)
    return DATA_DIR / DEFAULT_EXCEL_NAME


def data_store(path=None, root="default"):
    """The storage of the Excel file in use (fsr_store.ExcelStore): every
    read and write of report data goes through it. `path`: another
    workbook; `root`: the Demo Mode folder (default: as the program
    runs)."""
    if root == "default":
        root = DATA_DIR if DEMO_MODE else None
    return fsr_store.ExcelStore(path or excel_state["path"], root)


def withdrawal_book():
    """The Withdrawal workbook beside the Excel file in use. In Demo Mode it
    must stay inside the demo folder (ValueError otherwise)."""
    return fsr_paths.withdrawal_workbook_path(
        excel_state["path"], DATA_DIR if DEMO_MODE else None)


class ScrollFrame(tb.Frame):
    """A frame that scrolls vertically (and optionally horizontally).
    Put widgets into `.body`."""

    def __init__(self, parent, horizontal=False):
        super().__init__(parent)
        self.horizontal = horizontal

        self.canvas = tkinter.Canvas(
            self, highlightthickness=0, bd=0, yscrollincrement=20,
            xscrollincrement=20, background=style.colors.bg
        )
        self.vsb = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview
        )
        self.canvas.configure(yscrollcommand=self.vsb.set)

        self.vsb.pack(side="right", fill="y")
        if horizontal:
            self.hsb = ttk.Scrollbar(
                self, orient="horizontal", command=self.canvas.xview
            )
            self.canvas.configure(xscrollcommand=self.hsb.set)
            self.hsb.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.body = tb.Frame(self.canvas, padding=16)
        self.body.columnconfigure(0, weight=1)
        self._window_id = self.canvas.create_window(
            (0, 0), window=self.body, anchor="nw"
        )

        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        scroll_frames.append(self)

    def _on_body(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event):
        width = event.width
        if self.horizontal:
            width = max(self.body.winfo_reqwidth(), event.width)
        self.canvas.itemconfigure(self._window_id, width=width)

    def apply_theme(self):
        self.canvas.configure(background=style.colors.bg)

    def contains(self, widget):
        while widget is not None:
            if widget is self.body:
                return True
            widget = getattr(widget, "master", None)
        return False

    def ensure_visible(self, widget):
        """Scroll just enough to show `widget`."""
        try:
            self.canvas.update_idletasks()
            top = widget.winfo_rooty() - self.body.winfo_rooty()
            bottom = top + widget.winfo_height()
            total = max(self.body.winfo_height(), 1)
            view = self.canvas.winfo_height()

            if total > view:
                y0 = self.canvas.canvasy(0)
                if top < y0 + 20:
                    self.canvas.yview_moveto(max(top - 20, 0) / total)
                elif bottom > y0 + view - 20:
                    self.canvas.yview_moveto((bottom - view + 20) / total)

            if self.horizontal:
                left = widget.winfo_rootx() - self.body.winfo_rootx()
                right = left + widget.winfo_width()
                total_w = max(self.body.winfo_width(), 1)
                view_w = self.canvas.winfo_width()

                if total_w > view_w:
                    x0 = self.canvas.canvasx(0)
                    if left < x0 + 20:
                        self.canvas.xview_moveto(max(left - 20, 0) / total_w)
                    elif right > x0 + view_w - 20:
                        self.canvas.xview_moveto(
                            (right - view_w + 20) / total_w
                        )
        except tkinter.TclError:
            pass


def active_scroll_frame():
    try:
        tab = notebook.nametowidget(notebook.select())
    except (tkinter.TclError, KeyError, NameError):
        return None
    return tab if isinstance(tab, ScrollFrame) else None


def inspection_visible():
    shell = globals().get("app_shell")
    return shell is None or shell.is_inspection()


def on_mousewheel(event):
    """Scroll the visible tab with the mouse wheel."""
    try:
        if event.widget.winfo_toplevel() is not window:
            return      # ignore pop-ups (calendar, dialogs, drop-downs)
    except (AttributeError, KeyError, tkinter.TclError):
        return
    if not inspection_visible():
        return          # another module is shown (it scrolls itself)

    sf = active_scroll_frame()
    if sf is None:
        return

    if event.num == 4:          # Linux scroll up
        direction = -1
    elif event.num == 5:        # Linux scroll down
        direction = 1
    else:                       # Windows / macOS
        direction = -1 if event.delta > 0 else 1

    if sf.horizontal and (event.state & 0x1):      # Shift + wheel
        sf.canvas.xview_scroll(direction * 3, "units")
        return

    if sf.body.winfo_reqheight() <= sf.canvas.winfo_height():
        return
    sf.canvas.yview_scroll(direction * 3, "units")


def scroll_instead_of_change(combo):
    """Mouse wheel over a drop-down scrolls the page and does NOT
    silently change the selected value."""

    def handler(event):
        on_mousewheel(event)
        return "break"

    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        combo.bind(sequence, handler)


def scroll_to_widget(widget):
    for sf in scroll_frames:
        if sf.contains(widget):
            sf.ensure_visible(widget)
            return


def on_focus_in(event):
    try:
        if event.widget.winfo_class() in ("TEntry", "TCombobox"):
            scroll_to_widget(event.widget)
    except (AttributeError, KeyError, tkinter.TclError):
        pass        # e.g. the drop-down list of a combobox (a plain string)


def field_is_usable(widget):
    try:
        return (widget.winfo_ismapped()
                and str(widget.cget("state")) != "disabled")
    except tkinter.TclError:
        return False


def fields_in(container):
    """Every visible text box / drop-down inside `container`."""
    found = []
    try:
        children = container.winfo_children()
    except tkinter.TclError:
        return found
    for child in children:
        try:
            if child.winfo_class() in FIELD_CLASSES and field_is_usable(child):
                found.append(child)
        except tkinter.TclError:
            continue
        found.extend(fields_in(child))
    return found


def neighbour_field(widget, direction):
    """The nearest box above (-1) or below (+1) `widget` on the page."""
    page = next((sf for sf in scroll_frames if sf.contains(widget)), None)
    if page is None:
        return None

    x0, y0 = widget.winfo_rootx(), widget.winfo_rooty()
    candidates = []
    for other in fields_in(page.body):
        if other is widget:
            continue
        distance = (other.winfo_rooty() - y0) * direction
        if distance > 8:                            # a different row
            candidates.append((distance, abs(other.winfo_rootx() - x0), other))
    if not candidates:
        return None

    nearest = min(c[0] for c in candidates)
    same_row = [c for c in candidates if c[0] <= nearest + 8]
    return min(same_row, key=lambda c: c[1])[2]


def move_to_neighbour(event, direction):
    try:
        if event.widget.winfo_toplevel() is not window:
            return None
        target = neighbour_field(event.widget, direction)
    except (AttributeError, KeyError, tkinter.TclError):
        return None
    if target is None:
        return None             # nothing there: keep the normal behaviour

    target.focus_set()
    try:
        target.select_range(0, "end")
        target.icursor("end")
    except (AttributeError, tkinter.TclError):
        pass
    scroll_to_widget(target)
    return "break"


def scroll_page(event, kind):
    """Page Up / Page Down / Ctrl+Home / Ctrl+End scroll the visible tab."""
    try:
        if event.widget.winfo_toplevel() is not window:
            return None
    except (AttributeError, KeyError, tkinter.TclError):
        return None
    if not inspection_visible():
        return None
    sf = active_scroll_frame()
    if sf is None:
        return None
    if kind == "top":
        sf.canvas.yview_moveto(0)
    elif kind == "bottom":
        sf.canvas.yview_moveto(1)
    else:
        sf.canvas.yview_scroll(kind, "pages")
    return "break"


def set_dirty(flag):
    if report_state["dirty"] != flag:
        report_state["dirty"] = flag
        # update_status() is defined further down; while the tabs are
        # still being built there is nothing to show yet.
        if "update_status" in globals():
            update_status()


def mark_dirty(*_):
    set_dirty(True)


def on_any_key(event):
    try:
        widget = event.widget
        if widget.winfo_toplevel() is not window:
            return
        if widget.winfo_class() not in ("TEntry", "TCombobox"):
            return
        if str(widget.cget("state")) == "readonly":
            return
    except (AttributeError, KeyError, tkinter.TclError):
        return

    if (widget is control_entry or widget is globals().get("search_entry")
            or event.keysym in IGNORED_KEYS):
        return
    if (event.state & 0x4) and event.keysym.lower() not in ("v", "x"):
        return                      # Ctrl+S, Ctrl+C ... are not edits
    mark_dirty()


def on_combo_selected(event):
    try:
        if (event.widget.winfo_toplevel() is window
                and not getattr(event.widget, "no_dirty", False)):
            mark_dirty()
    except (AttributeError, KeyError, tkinter.TclError):
        pass

# =====================================================
# JSON MASTER LIST CONFIGURATION
# =====================================================

def clean_list(values):
    """Strip, remove blanks and case-insensitive duplicates, sort A-Z."""
    seen, result = set(), []
    for value in values:
        text = str(value).strip()
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            result.append(text)
    return sorted(result, key=str.casefold)


def load_master_lists():
    """Load master lists from the JSON file."""

    try:
        with open(MASTER_LIST_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        required_keys = [
            "consignee_list",
            "supplier_list",
            "broker_list",
            "hauler_list",
            LOCATION_LIST_KEY,
            DESTINATION_LIST_KEY,
            COUNTRY_LIST_KEY,
        ]

        missing = [
            key for key in required_keys
            if key not in data or not isinstance(data[key], list)
        ]
        if missing:
            raise ValueError(
                "Missing or invalid list(s) in master_list.json:\n- "
                + "\n- ".join(missing)
            )

        for key in required_keys:
            data[key] = clean_list(data[key])

        return data

    except FileNotFoundError:
        log.error("master_list.json not found: %s", MASTER_LIST_FILE)
        messagebox.showerror(
            "File Not Found",
            f"Could not find master_list.json:\n{MASTER_LIST_FILE}"
        )

    except (json.JSONDecodeError, ValueError) as error:
        log.exception("master_list.json is invalid")
        messagebox.showerror(
            "JSON Error",
            f"Unable to load master lists:\n{error}"
        )

    window.destroy()
    sys.exit(1)


def save_master_lists():
    """Save all master lists to the JSON file (atomic)."""

    try:
        write_json_atomic(MASTER_LIST_FILE, master_data)
        return True

    except (OSError, TypeError) as error:
        log.exception("Could not save master_list.json")
        messagebox.showerror(
            "Save Error",
            f"Unable to save master_list.json:\n{error}"
        )
        return False


def create_searchable_combobox(parent, list_key, width=30):
    """
    Searchable combobox:
    1. Allows users to type any characters.
    2. Filters existing names while typing (open the arrow to see them).
    3. Asks for confirmation before adding a new name (on Enter, and
       again when the report is saved).
    4. Prevents duplicate names (case-insensitive).
    5. Saves confirmed new names (sorted) to master_list.json.
    """

    master_list = master_data[list_key]

    combo = tb.Combobox(
        parent, values=master_list, width=width, state="normal"
    )
    scroll_instead_of_change(combo)
    declined = set()
    # The drop-down is rebuilt every time it opens, and when the box is
    # left, so a filtered list can never stay behind.
    combo.configure(postcommand=lambda: combo.configure(values=shown_values()))

    def filter_list(event=None):
        if event and event.keysym in NAV_KEYS:
            return

        combo["values"] = shown_values()

    def shown_values():
        """The whole list, or the names that contain what was typed.
        Never an empty list (a new name that matches nothing, or a box
        that was cleared, must not make the list look lost)."""
        typed_text = combo.get().strip()
        if not typed_text or any(
                item.casefold() == typed_text.casefold()
                for item in master_list):
            return list(master_list)      # empty, or a complete name
        found = [
            item for item in master_list
            if typed_text.casefold() in item.casefold()
        ]
        return found or list(master_list)

    def commit(event=None):
        new_value = combo.get().strip()
        if not new_value:
            return

        existing_value = next(
            (item for item in master_list
             if item.casefold() == new_value.casefold()),
            None
        )

        if existing_value is not None:
            combo.set(existing_value)
            combo["values"] = master_list
            return

        if new_value.casefold() in declined:
            return

        confirm = messagebox.askyesno(
            "Add New Name",
            f'"{new_value}" is not in the master list.\n\n'
            "Do you want to add this name to the master list?",
            parent=window
        )

        if confirm:
            master_list.append(new_value)
            master_list.sort(key=str.casefold)

            if save_master_lists():
                combo["values"] = master_list
                combo.set(new_value)
            else:
                master_list.remove(new_value)      # roll back
                combo["values"] = master_list
        else:
            declined.add(new_value.casefold())
            combo["values"] = master_list

    def on_return(event):
        commit()
        return "break"

    combo.bind("<KeyRelease>", filter_list)
    combo.bind("<FocusOut>",
               lambda e: combo.configure(values=list(master_list)), add="+")
    combo.bind("<Return>", on_return)
    combo.bind(
        "<<ComboboxSelected>>",
        lambda e: combo.configure(values=master_list), add="+"
    )

    combo.commit = commit
    searchable_combos.append(combo)
    return combo


def add_button_text(used, limit):
    left = limit - used
    return "Limit reached" if left <= 0 else f"+ Add Line ({left} left)"


def update_line_counter(label, used, limit):
    """e.g. '7 of 30 lines used' - orange when nearly full, red at the limit."""
    left = limit - used

    if left <= 0:
        text, color = f"{used} of {limit} lines used - limit reached", "danger"
    elif left <= LOW_LINES_WARNING:
        text, color = f"{used} of {limit} lines used - only {left} left", "warning"
    else:
        text, color = f"{used} of {limit} lines used", "secondary"

    label.configure(text=text, bootstyle=color)


def total_item_rows():
    """Item lines that will actually be printed (blank rows don't count)."""
    return sum(section.filled_count() for section in item_frames)


def refresh_findings_counter():
    """Item lines changed -> update the lines left in Additional Details."""
    if findings_frame is not None:
        findings_frame.refresh_counter()


# =====================================================
# REUSABLE "REMARKS" SECTION (with Add / Remove line)
# =====================================================

def create_remarks_section(parent, title, entry_width,
                           initial_rows=5, max_rows=20, capacity_func=None):
    """
    Build a Labelframe with remark entries and + / - buttons.
    Returns (section_frame, entries).

    capacity_func (optional) returns (lines that fit on the printed page,
    item lines sharing that page). Only lines with text are counted.
    section_frame.refresh_counter() redraws the numbers.
    """

    section_frame = tb.Labelframe(parent, text=title, padding=10)
    section_frame.columnconfigure(0, weight=1)
    entries = []

    buttons_frame = tb.Frame(section_frame)

    def update_buttons(event=None):
        if capacity_func is None:
            used = len(entries)
            add_btn.configure(text=add_button_text(used, max_rows))
            update_line_counter(counter_label, used, max_rows)
        else:
            used = sum(1 for e in entries if e.get().strip())
            capacity, item_lines = capacity_func()
            left = capacity - used
            shared = (f"shared with {item_lines} item "
                      f"line{'s' if item_lines != 1 else ''}")

            if capacity <= 0:
                text = (f"{used} lines - no room left on the Cargo Details "
                        f"page ({shared}); all of it prints on a blank "
                        f"Additional Details form")
                color = "warning"
            elif used > capacity:
                text = (f"{used} lines - more than the {capacity} lines "
                        f"left on the page ({shared}); all of it will "
                        f"print on a blank Additional Details form")
                color = "danger"
            elif left == 0:
                text = (f"{used} of {capacity} lines used - page full "
                        f"(page {shared}); one more line moves everything "
                        f"to a blank Additional Details form")
                color = "warning"
            else:
                text = f"{used} of {capacity} lines used (page {shared})"
                color = "warning" if left <= LOW_LINES_WARNING else "secondary"

            counter_label.configure(text=text, bootstyle=color)
            add_btn.configure(
                text=f"+ Add Line ({left} left)" if left > 0
                else "+ Add Line (page full)"
            )

        if len(entries) >= max_rows:
            add_btn.configure(text="Limit reached", state="disabled")
        else:
            add_btn.configure(state="normal")

        remove_btn.configure(state="disabled" if len(entries) <= 1 else "normal")

    def place_buttons():
        buttons_frame.grid(
            row=len(entries), column=0, padx=8, pady=(8, 2), sticky="w"
        )

    def add_row():
        if len(entries) >= max_rows:
            return

        entry = tb.Entry(section_frame, width=entry_width)
        entry.grid(row=len(entries), column=0, padx=8, pady=3, sticky="we")
        entry.bind("<KeyRelease>", update_buttons, add="+")
        entries.append(entry)

        place_buttons()
        update_buttons()
        mark_dirty()

    def remove_row():
        if len(entries) <= 1:
            return

        entries.pop().destroy()

        place_buttons()
        update_buttons()
        mark_dirty()

    add_btn = tb.Button(
        buttons_frame, text="+ Add Line", width=20, command=add_row,
        bootstyle="primary-outline"
    )
    add_btn.grid(row=0, column=0, padx=(0, 6))

    remove_btn = tb.Button(
        buttons_frame, text="- Remove Line", command=remove_row,
        bootstyle="secondary-outline"
    )
    remove_btn.grid(row=0, column=1)

    counter_label = tb.Label(buttons_frame, anchor="w")
    counter_label.grid(row=0, column=2, padx=(15, 0), sticky="w")

    def set_row_count(count):
        """Used when a saved report is loaded or the form is cleared."""
        count = max(1, min(count, max_rows))
        while len(entries) < count:
            add_row()
        while len(entries) > count:
            remove_row()

    section_frame.set_row_count = set_row_count
    section_frame.refresh_counter = update_buttons

    for _ in range(initial_rows):
        add_row()

    return section_frame, entries


# =====================================================
# FIELD DEFINITIONS + FORMAT HELPERS
# =====================================================
# Field definitions, date / time helpers, Good / Bad Order,
# Types of Goods and the incident report JSON files are in
# fsr_storage.py (plain data helpers - no widgets).

# ---- GUI helpers (need the window) ----

def mark_entry(entry, invalid):
    """Red text for an invalid box (plain Entry boxes only)."""
    if isinstance(entry, ttk.Combobox):
        return
    try:
        entry.configure(foreground="red" if invalid else "")
    except tkinter.TclError:
        pass


def format_entry(entry, kind):
    """On leaving a date/time box: tidy it, or mark it red if invalid."""
    normalized = normalize_field(entry.get(), kind)

    if normalized is None:
        mark_entry(entry, True)
        return

    mark_entry(entry, False)
    if normalized != entry.get():
        set_entry(entry, normalized)


def build_field_row(parent, fields, layout=None):
    """
    Label above a box for every field. Returns {key: widget}.
    layout: optional [(row, column)] per field; by default the fields fill
    FIELD_COLUMNS columns, left to right.
    """
    entries = {}

    for col in range(FIELD_COLUMNS):
        parent.columnconfigure(col, weight=1, uniform="field")

    for index, (label_text, key, _width, kind, _) in enumerate(fields):
        row, col = (layout[index] if layout
                    else divmod(index, FIELD_COLUMNS))
        tb.Label(parent, text=label_text.replace("\n", " ")).grid(
            row=row * 2, column=col, padx=8, pady=(6, 0), sticky="w"
        )
        if kind == "date":
            # Drop-down list: blank, today, then the previous 7 days.
            # Rebuilt every time it is opened, so it stays correct if the
            # program stays open past midnight.
            # (the user may also type a date: dd-MMM-yyyy)
            entry = tb.Combobox(
                parent,
                state="normal",
                values=[""] + recent_date_options()
            )
            entry.bind(
                "<FocusOut>",
                lambda e, k=kind: format_entry(e.widget, k), add="+"
            )
            entry.configure(
                postcommand=lambda c=entry: c.configure(
                    values=[""] + recent_date_options()
                )
            )
            scroll_instead_of_change(entry)
        elif kind == "choice":
            # Fixed drop-down list (for example Activity).
            entry = tb.Combobox(
                parent,
                state="normal" if key in TYPEABLE_CHOICES else "readonly",
                values=[""] + CHOICE_VALUES[key]
            )
            scroll_instead_of_change(entry)
        else:
            entry = tb.Entry(parent)
            if kind == "time":
                entry.bind(
                    "<FocusOut>",
                    lambda e, k=kind: format_entry(e.widget, k)
                )

        entry.grid(row=row * 2 + 1, column=col, padx=8, pady=(0, 6),
                   sticky="we")
        entries[key] = entry

    return entries


def validate_format_fields():
    """Check every date / time box before saving."""
    messages = {
        "date": "Please use dd-MMM-yyyy, for example 25-Oct-2026.",
        "time": "Please use 4 digits followed by H, from 0000H to 2400H, "
                "for example 1800H.",
    }

    # Inspection date (required).
    normalized = normalize_field(get_inspection_date(), "date")
    if not normalized:
        notebook.select(general_tab)
        messagebox.showwarning(
            "Invalid Format",
            f"Inspection Date\n\n{messages['date']}",
            parent=window
        )
        inspection_date_entry.entry.focus_set()
        return False
    set_inspection_date(normalized)

    for fields, entries, tab in (
        (SCHEDULE_FIELDS, schedule_entries, general_tab),
        (TRANSPORT_FIELDS, transport_entries, general_tab),
    ):
        for label, key, _, kind, _ in fields:
            if kind not in messages:
                continue

            entry = entries[key]
            normalized = normalize_field(entry.get(), kind)

            if normalized is None:
                mark_entry(entry, True)
                notebook.select(tab)
                messagebox.showwarning(
                    "Invalid Format",
                    f"{label.replace(chr(10), ' ')}\n\n{messages[kind]}",
                    parent=window
                )
                entry.focus_set()
                return False

            format_entry(entry, kind)

    return True


def notify(message, bootstyle="success"):
    """Short non-blocking message (status bar + toast)."""
    status_var.set(message)
    window.after(
        8000,
        lambda: status_var.set("") if status_var.get() == message else None
    )
    if ToastNotification is None:
        return
    try:
        ToastNotification(
            title="Field Survey Report", message=message,
            duration=2500, bootstyle=bootstyle
        ).show_toast()
    # Broad on purpose: a notice that cannot be shown must never stop the
    # action it reports (ttkbootstrap's own errors are not documented).
    except Exception:
        log.debug("Toast notice not shown", exc_info=True)


def mysql_away(error, what_now):
    """A MySQL server that cannot be reached is normal (the service is
    stopped, the PC is offline): no error box. Shows the orange notice
    "MySQL was not reached - <what_now>" and returns True; returns False
    for any other error, which the caller reports as before."""
    if db_mysql is None or not getattr(
            db_mysql, "is_unreachable", lambda e: False)(error):
        return False
    log.info("MySQL was not reached: %s", error)
    if "set_mysql_dots" in globals():
        set_mysql_dots("bad", "MySQL was not reached. Is the MySQL80 "
                              "service running?")
    notify(f"MySQL was not reached  -  {what_now}", bootstyle="warning")
    return True


def add_tip(widget, text):
    if ToolTip is None:
        return
    try:
        ToolTip(widget, text=text)
    except Exception:                   # broad: only a tooltip
        log.debug("Tooltip not added", exc_info=True)


def section_title(parent, text, first=False):
    label = tb.Label(parent, text=text.upper(), font=small_font,
                     bootstyle="info")
    label.pack(anchor="w", pady=(0 if first else 16, 5))
    return label


def rebuild_account_menu():
    account_menu.delete(0, "end")
    if IS_OWNER:
        waiting = user_store.pending_count()
        account_menu.add_command(
            label="Manage Users" + (f"  ({waiting} waiting)" if waiting else ""),
            command=lambda: app_auth.open_manage_users(
                window, user_store, current_user,
                on_change=rebuild_account_menu))
        account_menu.add_command(
            label="Recovery Code...",
            command=lambda: app_auth.open_recovery_code(
                window, user_store, current_user))
    if IS_OWNER_EDITION:
        account_menu.add_command(
            label="MySQL Settings...", command=lambda: open_mysql_settings())
        waiting_now = len(waiting_conflicts()) \
            if "waiting_conflicts" in globals() else 0
        account_menu.add_command(
            label="MySQL Conflicts..." + (
                f"  ({waiting_now} waiting)" if waiting_now else ""),
            command=lambda: open_mysql_conflicts())
    account_menu.add_command(
        label="Change Password...",
        command=lambda: app_auth.open_change_password(
            window, user_store, current_user))
    account_menu.add_separator()
    account_menu.add_command(label="Sign Out", command=lambda: sign_out())
    if IS_OWNER:
        waiting = user_store.pending_count()
        account_menu_button.configure(
            bootstyle="warning-outline" if waiting else "secondary-outline")


def restart_program():
    save_settings()
    try:
        subprocess.Popen([sys.executable] if FROZEN
                         else [sys.executable, *sys.argv])
    except OSError:
        pass
    window.destroy()


def sign_out():
    """Close this session and start the program again at the sign in."""
    if not confirm_discard("Sign Out", "Sign out now?"):
        return
    restart_program()


def open_mysql_settings():
    """Fill in the MySQL connection (no file editing needed)."""
    if not IS_OWNER_EDITION:
        messagebox.showinfo(
            "MySQL", "This is the User edition: reports are kept on this PC. "
            "Use Export Master Data and send the file to the owner.",
            parent=window)
        return
    if DEMO_MODE:
        messagebox.showinfo(
            "MySQL", "MySQL is switched off in Demo Mode, so the sample "
            "(TEST) data can never reach the real database.", parent=window)
        return
    if db_mysql is None:
        messagebox.showinfo(
            "MySQL", "The MySQL module (db_mysql.py) was not found.",
            parent=window)
        return

    config = db_mysql.read_raw_config()
    dialog = tb.Toplevel(window)
    dialog.title("MySQL Settings")
    dialog.transient(window)
    dialog.resizable(False, False)
    body = tb.Frame(dialog, padding=22)
    body.pack(fill="both", expand=True)

    tb.Label(
        body, text="Connection to the MySQL database",
        font=bold_font
    ).grid(row=0, column=0, columnspan=2, sticky="w")
    tb.Label(
        body, wraplength=360, justify="left", bootstyle="secondary",
        text="Host = the name or IP address of the PC that has MySQL "
             "(localhost if it is this PC). The other PCs use the same "
             "settings."
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 10))

    enabled = tkinter.BooleanVar(value=bool(config.get("enabled")))
    tb.Checkbutton(body, text="Use MySQL (save and open reports from it)",
                   variable=enabled).grid(row=2, column=0, columnspan=2,
                                          sticky="w", pady=(0, 8))
    boxes = {}
    for row, (key, label, secret) in enumerate((
            ("host", "Host", False), ("port", "Port", False),
            ("user", "User", False), ("password", "Password", True),
            ("database", "Database", False)), start=3):
        tb.Label(body, text=label).grid(row=row, column=0, sticky="w",
                                        pady=4, padx=(0, 12))
        entry = tb.Entry(body, width=28, show="*" if secret else "")
        entry.insert(0, str(config.get(key, "")))
        entry.grid(row=row, column=1, sticky="we", pady=4)
        boxes[key] = entry

    result = tb.Label(body, text="", wraplength=360, justify="left")
    result.grid(row=9, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def current():
        port = boxes["port"].get().strip()
        return {
            "enabled": enabled.get(),
            "host": boxes["host"].get().strip() or "localhost",
            "port": int(port) if port.isdigit() else 3306,
            "user": boxes["user"].get().strip(),
            "password": boxes["password"].get(),
            "database": boxes["database"].get().strip() or "field_survey",
        }

    def test():
        result.configure(text="Testing...", bootstyle="secondary")
        dialog.update_idletasks()
        try:
            ok, message = busy(db_mysql.test_connection, current())
        except Exception as error:
            ok, message = False, str(error)
        result.configure(text=message, bootstyle="success" if ok else "danger")

    def save():
        try:
            db_mysql.write_config(current())
        except OSError as error:
            messagebox.showerror("MySQL Settings",
                                 f"Could not save the settings:\n{error}",
                                 parent=dialog)
            return
        dialog.destroy()
        # The settings are read from the file every time MySQL is used, so
        # no restart is needed: the status at the top right is checked
        # again right now with what was just saved.
        if "check_mysql_status" in globals():
            check_mysql_status()
        notify("MySQL settings saved - checking the connection...")

    row = tb.Frame(body)
    row.grid(row=10, column=0, columnspan=2, sticky="we", pady=(14, 0))
    tb.Button(row, text="Test Connection", bootstyle="secondary-outline",
              command=test).pack(side="left")
    tb.Button(row, text="Save", bootstyle="info", command=save,
              width=10).pack(side="right")
    tb.Button(row, text="Cancel", bootstyle="secondary-outline",
              command=dialog.destroy, width=10).pack(side="right", padx=8)
    dialog.bind("<Escape>", lambda e: dialog.destroy())

# the pages (their own tab strip is hidden; the sections menu drives them)
def hide_notebook_tabs():
    """Layouts belong to a theme, so this also runs after a theme change."""
    try:
        style.layout("Hidden.TNotebook.Tab", [])
        style.configure("Hidden.TNotebook", borderwidth=0, tabmargins=0)
        return True
    except Exception:
        log.exception("Could not hide the tab strip")
        return False


def refresh_condition_buttons(*_):
    value = condition_var.get()
    good_button.configure(
        bootstyle="success" if value == CONDITION_GOOD else "secondary-outline")
    bad_button.configure(
        bootstyle="danger" if value == CONDITION_BAD else "secondary-outline")


def choose_condition(value):
    if condition_var.get() == value:
        return
    first_choice = not condition_var.get()
    condition_var.set(value)
    on_condition_clicked()
    if first_choice and condition_var.get():
        # the form just unlocked: start at the first box
        notebook.select(general_tab)
        SO_number_entry.focus_set()


def form_is_locked():
    if condition_var.get():
        return False
    try:
        current = notebook.select()
    except tkinter.TclError:
        return True
    return current != str(globals().get("summary_tab", ""))


def update_form_lock(*_):
    if form_is_locked():
        lock_cover.place(in_=notebook, x=0, y=0, relwidth=1, relheight=1)
        lock_cover.lift()
    else:
        lock_cover.place_forget()


def keep_focus_out_of_locked_form(event):
    """While locked, Tab / clicks may not put the cursor inside a page."""
    if not form_is_locked():
        return
    try:
        widget = event.widget
        if str(widget).startswith(str(notebook)):
            good_button.focus_set()
    except (AttributeError, tkinter.TclError):
        pass


def toggle_theme():
    new_theme = THEME_DARK if style.theme.name == THEME_LIGHT else THEME_LIGHT
    style.theme_use(new_theme)
    settings["theme"] = new_theme
    save_settings()
    hide_notebook_tabs()
    for sf in scroll_frames:
        sf.apply_theme()
    if "dots_canvas" in globals():
        try:
            dots_canvas.configure(background=style.colors.bg)
        except tkinter.TclError:
            pass
    if "refresh_nav" in globals():
        refresh_nav()
    if globals().get("app_shell") is not None:
        app_shell.theme_changed()


# =====================================================
# TAB 1 - GENERAL INFORMATION
# =====================================================

def add_field(parent, label_text, widget, row, col):
    """Label above widget, in grid cell (row, col)."""
    tb.Label(parent, text=label_text).grid(
        row=row * 2, column=col, padx=8, pady=(6, 0), sticky="w"
    )
    widget.grid(row=row * 2 + 1, column=col, padx=8, pady=(0, 6), sticky="we")


def get_inspection_date():
    return inspection_date_entry.entry.get().strip()


def set_inspection_date(text):
    inspection_date_entry.entry.delete(0, "end")
    inspection_date_entry.entry.insert(0, text)


def sync_commenced_date(event=None):
    new = normalize_field(get_inspection_date(), "date")
    if not new:
        return
    commenced = schedule_entries["commenced_date"]
    if commenced.get().strip() in ("", date_sync["last"]):
        set_entry(commenced, new)
        mark_entry(commenced, False)
    date_sync["last"] = new


def on_others_toggled():
    others_entry.configure(
        state="normal" if others_var.get() else "disabled"
    )
    if others_var.get():
        others_entry.focus_set()
    mark_dirty()


def collect_goods_types():
    types = {key: bool(var.get()) for key, var in goods_type_vars.items()}
    types["others"] = bool(others_var.get())
    types["others_text"] = (
        others_entry.get().strip() if types["others"] else ""
    )
    return types


def set_goods_types(types):
    types = {**empty_goods_types(), **(types or {})}
    for key, var in goods_type_vars.items():
        var.set(bool(types.get(key)))
    others_var.set(bool(types["others"]))
    others_entry.configure(state="normal")
    set_entry(others_entry, types["others_text"] if types["others"] else "")
    others_entry.configure(
        state="normal" if types["others"] else "disabled"
    )


class ItemLine(list):
    """The entry widgets of one line, plus its hidden saved values."""

    def __init__(self):
        super().__init__()
        self.hidden = {}
        self.po_link = {}       # Withdrawal fields of a PO-linked line


class ItemListSection:
    """One 'Item List' card with its rows, buttons and subtotal. It shows
    the columns of the Item List form chosen for the report."""

    def __init__(self, parent, number):
        self.form = item_form_var.get()
        self.headers, self.widths = ITEM_FORM_COLUMNS[self.form]
        self.hidden_headers = [h for h in ITEM_LINE_HEADERS
                               if h not in self.headers]
        self.priced = "Total Price" in self.headers

        title = f"Item List {number}"
        if self.form != ITEM_FORM_DEFAULT:
            title += f" - {self.form}"
        self.frame = tb.Labelframe(parent, text=title, padding=10)
        self.frame.grid(row=number - 1, column=0, pady=6, sticky="we")
        self.rows = []          # list of ItemLine (Entry widgets)

        for col_index, header in enumerate(self.headers):
            heading = tb.Label(self.frame, text=self.label(header),
                               font=bold_font)
            heading.grid(
                row=0, column=col_index, padx=3, pady=(0, 4), sticky="w"
            )
            if header in ITEM_HEADER_TIPS:
                add_tip(heading, ITEM_HEADER_TIPS[header])

        toolbar = tb.Frame(self.frame)
        toolbar.grid(row=MAX_ROWS + 1, column=0,
                     columnspan=len(self.headers),
                     pady=(10, 0), sticky="we")
        toolbar.columnconfigure(3, weight=1)

        self.add_btn = tb.Button(
            toolbar, text="+ Add Line", width=20, command=self.add_line,
            bootstyle="primary-outline"
        )
        self.add_btn.grid(row=0, column=0, padx=(0, 6))

        self.remove_btn = tb.Button(
            toolbar, text="- Remove Line", command=self.remove_line,
            bootstyle="secondary-outline"
        )
        self.remove_btn.grid(row=0, column=1)

        self.counter_label = tb.Label(toolbar, anchor="w")
        self.counter_label.grid(row=0, column=2, padx=(15, 0), sticky="w")

        # Containerized / Loading have no prices: no subtotal.
        self.subtotal_label = tb.Label(toolbar, anchor="e", font=bold_font)
        if self.priced:
            self.subtotal_label.grid(row=0, column=3, sticky="e")

        for _ in range(5):
            self.create_row()
        self.update_buttons()
        self.update_subtotal()

    def label(self, header):
        """The heading shown for a column on this form."""
        if self.form == ITEM_FORM_DEFAULT:
            return header
        if header == UNIT_NO_HEADER:
            return UNIT_NO_LABELS[self.form]
        return UNIT_FORM_LABELS.get(header, header)

    def cell(self, widgets, header):
        return widgets[self.headers.index(header)]

    # ---- rows ----

    def create_row(self):
        row_no = len(self.rows) + 1
        widgets = ItemLine()

        for col_index, (header, width) in enumerate(
                zip(self.headers, self.widths)):
            if header == "UOM":
                entry = tb.Combobox(self.frame, width=width,
                                    values=UOM_CHOICES)
                scroll_instead_of_change(entry)
            elif header == "Weight Unit":
                entry = tb.Combobox(self.frame, width=width,
                                    values=WEIGHT_UNIT_CHOICES)
                scroll_instead_of_change(entry)
            elif header == "Currency":
                entry = tb.Combobox(self.frame, width=width,
                                    values=[""] + CURRENCIES)
                entry.bind(
                    "<<ComboboxSelected>>",
                    lambda e, w=widgets: self.row_changed(w, "Currency"),
                    add="+")
                entry.bind(
                    "<FocusOut>",
                    lambda e, w=widgets: self.upper_currency(w), add="+")
                scroll_instead_of_change(entry)
            else:
                entry = tb.Entry(self.frame, width=width)
            entry.grid(row=row_no, column=col_index, padx=3, pady=2,
                       sticky="w")
            entry.manual_total = False
            entry.bind(
                "<KeyRelease>",
                lambda e, w=widgets, h=header: self.row_changed(w, h),
                add="+"
            )
            widgets.append(entry)

        self.cell(widgets, "Quantity").bind(
            "<FocusOut>", lambda e, w=widgets: self.split_quantity(w),
            add="+")
        self.cell(widgets, "Weights").bind(
            "<FocusOut>", lambda e, w=widgets: self.split_weight(w),
            add="+")
        fsr_withdrawal_ui.bind_line(self, widgets, lambda: withdrawal_panel)
        self.rows.append(widgets)
        refresh_findings_counter()

    def add_line(self):
        if len(self.rows) < MAX_ROWS:
            self.create_row()
            self.update_buttons()
            mark_dirty()

    def remove_line(self):
        if len(self.rows) > 1:
            for widget in self.rows.pop():
                widget.destroy()
            self.update_buttons()
            self.update_subtotal()
            refresh_findings_counter()
            mark_dirty()

    def set_row_count(self, count):
        """Used when a saved report is loaded or the form is cleared."""
        count = max(1, min(count, MAX_ROWS))
        while len(self.rows) < count:
            self.add_line()
        while len(self.rows) > count:
            self.remove_line()

    # ---- numbers ----

    def split_quantity(self, widgets):
        """'12 pcs' typed in Quantity -> Quantity 12, UOM PCS."""
        if fsr_withdrawal_ui.is_linked(widgets):
            return
        quantity_box = self.cell(widgets, "Quantity")
        uom_box = self.cell(widgets, "UOM")
        typed = quantity_box.get().strip()
        quantity, uom = split_quantity_unit(typed, uom_box.get())
        if quantity != typed:
            set_entry(quantity_box, quantity)
            set_entry(uom_box, uom.upper())
            self.row_changed(widgets, "Quantity")

    def split_weight(self, widgets):
        """'1,250 kg' typed in Weights -> Weights 1,250, Weight Unit KG."""
        weight_box = self.cell(widgets, "Weights")
        unit_box = self.cell(widgets, "Weight Unit")
        typed = weight_box.get().strip()
        weight, unit = split_quantity_unit(typed, unit_box.get())
        if weight != typed:
            set_entry(weight_box, weight)
            set_entry(unit_box, unit.upper())

    def upper_currency(self, widgets):
        """A typed currency 'usd' -> 'USD' (one subtotal per code)."""
        currency = self.cell(widgets, "Currency")
        typed = currency.get()
        if typed != typed.strip().upper():
            set_entry(currency, typed.strip().upper())
            self.update_subtotal()

    def row_changed(self, widgets, header):
        """Auto Total Price = Quantity x Unit Price (unless typed by hand)."""
        if self.priced:
            total = self.cell(widgets, "Total Price")

            if header == "Total Price":
                total.manual_total = bool(total.get().strip())
            elif header in ("Quantity", "Unit Price") and not total.manual_total:
                qty = to_number(self.cell(widgets, "Quantity").get())
                unit = to_number(self.cell(widgets, "Unit Price").get())
                numeric = (int, float)
                if isinstance(qty, numeric) and isinstance(unit, numeric):
                    set_entry(total, f"{qty * unit:,.2f}")
                else:
                    set_entry(total, "")
            if header in ("Unit Price", "Total Price"):
                self.default_currency(widgets)

        self.update_subtotal()
        self.update_buttons()
        refresh_findings_counter()

    def default_currency(self, widgets):
        """A line given a price takes the currency of the line above."""
        currency = self.cell(widgets, "Currency")
        if currency.get() or not (
                self.cell(widgets, "Unit Price").get().strip()
                or self.cell(widgets, "Total Price").get().strip()):
            return
        above = [self.cell(w, "Currency").get()
                 for w in self.rows[:self.rows.index(widgets)]
                 if self.cell(w, "Currency").get()]
        if above:
            currency.set(above[-1])

    def filled_count(self):
        return sum(
            1 for widgets in self.rows
            if any(w.get().strip() for w in widgets)
        )

    def subtotals(self):
        """{currency: amount}; '' for prices without a currency."""
        amounts = {}
        if not self.priced:
            return amounts
        for widgets in self.rows:
            value = to_number(self.cell(widgets, "Total Price").get())
            if isinstance(value, (int, float)):
                code = self.cell(widgets, "Currency").get()
                amounts[code] = amounts.get(code, 0.0) + value
        return amounts

    def update_subtotal(self):
        amounts = self.subtotals() or {"": 0.0}
        text = "  |  ".join(
            f"{code} {amount:,.2f}".strip()
            for code, amount in sorted(amounts.items()))
        self.subtotal_label.configure(text=f"Subtotal: {text}")

    def update_buttons(self):
        used = len(self.rows)
        self.add_btn.configure(
            text=add_button_text(used, MAX_ROWS),
            state="disabled" if used >= MAX_ROWS else "normal"
        )
        self.remove_btn.configure(state="disabled" if used <= 1 else "normal")
        update_line_counter(self.counter_label, used, MAX_ROWS)

    def line_values(self, widgets):
        """One line as {header: text} (every saved column), or None when
        it is empty."""
        row = {header: widget.get().strip()
               for header, widget in zip(self.headers, widgets)}
        weight, unit = split_quantity_unit(row["Weights"],
                                           row.pop("Weight Unit"))
        row["Weights"] = " ".join(filter(None, (weight, unit)))
        row.update({h: widgets.hidden.get(h, "")
                    for h in self.hidden_headers})
        row.update(widgets.po_link)
        return row if any(row[h] for h in SAVED_LINE_HEADERS) else None

    def values(self):
        """The filled lines as {header: text} (every saved column)."""
        return [row for row in map(self.line_values, self.rows) if row]

    def set_values(self, lines):
        """Fill rows from a list of {header: text} dictionaries."""
        self.set_row_count(max(5, len(lines)))
        for widgets, row in zip(self.rows, lines):
            self.fill_line(widgets, row)
        self.update_subtotal()
        refresh_findings_counter()

    def fill_line(self, widgets, row):
        """Fill one line from a {header: text} dictionary."""
        fsr_withdrawal_ui.unlock_line(self, widgets)
        row = dict(row)
        if not row.get(fsr_withdrawal.LINE_NO_HEADER):
            row["Quantity"], row["UOM"] = split_quantity_unit(
                row.get("Quantity"), row.get("UOM"))
        row["Weights"], row["Weight Unit"] = split_quantity_unit(
            row.get("Weights"))
        for header, widget in zip(self.headers, widgets):
            set_entry(widget, str(row.get(header) or ""))
        widgets.hidden = {h: str(row.get(h) or "")
                          for h in self.hidden_headers}
        if self.priced:
            total = self.cell(widgets, "Total Price")
            total.manual_total = bool(total.get().strip())
        fsr_withdrawal_ui.restore_link(self, widgets, row)

    def clear(self):
        for widgets in self.rows:
            fsr_withdrawal_ui.unlock_line(self, widgets)
            for widget in widgets:
                set_entry(widget, "")
                widget.manual_total = False
            widgets.hidden = {}
        self.update_subtotal()

    def destroy(self):
        self.frame.destroy()


def create_item_frame():
    section = ItemListSection(item_lists_frame, len(item_frames) + 1)
    item_frames.append(section)
    refresh_findings_counter()


def update_item_list_buttons():
    remove_frame_button.configure(
        state="disabled" if len(item_frames) <= 1 else "normal"
    )


def add_item_frame():
    create_item_frame()
    update_item_list_buttons()
    mark_dirty()


def remove_item_frame():
    # Always keep at least one Item List.
    if len(item_frames) <= 1:
        return

    confirm = messagebox.askyesno(
        "Remove Item List",
        f"Remove Item List {len(item_frames)}?\n\n"
        "All data entered in it will be deleted.",
        parent=window
    )

    if not confirm:
        return

    item_frames.pop().destroy()

    update_item_list_buttons()
    refresh_findings_counter()
    mark_dirty()


def set_item_list_count(count):
    """Show exactly `count` Item Lists (no confirmation prompt)."""
    count = max(1, count)

    while len(item_frames) < count:
        create_item_frame()
    while len(item_frames) > count:
        item_frames.pop().destroy()

    update_item_list_buttons()
    refresh_findings_counter()


def collect_other_item_forms():
    """{form: item lists} of the forms not shown that have lines."""
    return {
        form: [{"name": f"Item List {index}", "rows": lines}
               for index, (lines, _) in enumerate(sections, start=1)]
        for form, sections in item_form_store.items()
        if any(lines for lines, _ in sections)
    }


def set_item_form(form):
    """Show the Item Lists of `form` (Default / Containerized / Loading).
    The lines of the form shown so far are put aside and that form's own
    lines (none yet: empty Item Lists) come back."""
    form = item_form_name(form)
    item_form_var.set(form)
    items_hint.configure(text=ITEM_FORM_HINTS[form])
    if all(section.form == form for section in item_frames):
        return

    if item_frames:
        item_form_store[item_frames[0].form] = [
            (section.values(), len(section.rows)) for section in item_frames]
    for section in item_frames:
        section.destroy()
    item_frames.clear()

    for lines, row_count in item_form_store.pop(form, None) or [([], 5)]:
        create_item_frame()
        item_frames[-1].set_values(lines)
        item_frames[-1].set_row_count(max(row_count, len(lines)))

    update_item_list_buttons()
    refresh_findings_counter()


def choose_item_form():
    """A form picked with the buttons above the Item Lists."""
    if not withdrawal_panel.context_changed():
        return
    if any(section.form != item_form_var.get() for section in item_frames):
        set_item_form(item_form_var.get())
        mark_dirty()


def week_span(year, month, week):
    """(first day, last day) of a week of the month, or None when the month
    has no such week. Week 1 = days 1-7 ... Week 5 = day 29 to month end;
    week 0 = the whole month."""
    last = calendar.monthrange(year, month)[1]
    if week == 0:
        return 1, last
    first = (week - 1) * 7 + 1
    if first > last:
        return None
    return first, (last if week >= 5 else min(week * 7, last))


def report_to_weekly_rows(data):
    """One report -> weekly summary rows (a row per item line)."""
    info = data["general_information"]
    docs = data["documents_used"]
    transport = data["transport_details"]
    head = [
        info["so_number"], info["inspection_date"],
        data["inspection_schedule"].get("activity", ""),
        transport.get("shipment_type", ""), info["supplier"],
        info["brokerage"], info["hauler"], info["destination"],
        info["country_of_origin"], docs["invoice_number"], docs["po_number"],
        docs["jo_number"], docs["gatepass_number"], docs["bl_awb_number"],
        docs["dr_number"], transport["vehicle_type"],
        transport["vehicle_plate_number"],
    ]
    items = [
        row for section in data["item_lists"] for row in section["rows"]
        if any(str(row.get(key) or "").strip() for key in ITEM_HEADERS)
    ]
    tail = [data["cargo_condition"]]
    if not items:
        return [head + [""] * len(WEEKLY_ITEM_KEYS) + tail]
    lines = []
    for row in items:
        row = dict(row)
        row["Quantity"], row["UOM"] = split_quantity_unit(
            row.get("Quantity"), row.get("UOM"))
        lines.append(
            head + [str(row.get(key) or "") for key in WEEKLY_ITEM_KEYS]
            + tail)
    return lines


def weekly_rows_from_excel(first_day, last_day):
    path = excel_state["path"]
    rows = []
    for entry in data_store(path).list_reports():
        day = parse_date(entry[2])
        if not isinstance(day, datetime):
            continue
        if first_day <= day.date() <= last_day:
            rows.append((day, entry[0], report_to_weekly_rows(
                data_store(path).read_report(entry[0]))))
    for report in data_store().read_all_withdrawal_reports():
        day = parse_date(report["general_information"]["inspection_date"])
        if isinstance(day, datetime) and first_day <= day.date() <= last_day:
            rows.append((day, report["control_no"],
                         report_to_weekly_rows(report)))
    rows.sort(key=lambda item: (item[0], item[1]))
    return [line for _, _, lines in rows for line in lines]


def weekly_rows(year, month, week, source):
    span = week_span(year, month, week)
    if span is None:
        return []
    first_day, last_day = date(year, month, span[0]), date(year, month, span[1])
    if source == "mysql":
        return db_mysql.weekly_summary(first_day, last_day)
    return weekly_rows_from_excel(first_day, last_day)


def weekly_cells(line):
    """28 weekly fields -> the 26 columns: (text, None) per column, or
    (currency, amount text) for the two price columns."""
    line = [str(value or "").strip() for value in line]
    currency = line[WEEKLY_CURRENCY]
    quantity = " ".join(filter(None, (line[WEEKLY_QTY], line[WEEKLY_UOM])))
    return (line[:WEEKLY_QTY] + [quantity] + line[WEEKLY_UOM + 1:WEEKLY_CURRENCY]
            + [(currency, line[WEEKLY_CURRENCY + 1]),
               (currency, line[WEEKLY_CURRENCY + 2])]
            + line[WEEKLY_CURRENCY + 3:])


def price_text(currency, amount):
    """('jpy', '460000') -> 'jpy 460,000.00'."""
    value = to_number(amount)
    if isinstance(value, (int, float)):
        amount = f"{value:,.2f}"
    return " ".join(filter(None, (currency, amount or "")))


def weekly_display(line):
    return [price_text(*cell) if isinstance(cell, tuple) else cell
            for cell in weekly_cells(line)]


def weekly_title(year, month, week):
    span = week_span(year, month, week)
    name = calendar.month_name[month]
    if week == 0 or span is None:
        return f"Weekly Summary Report - {name} {year} (whole month)"
    return (f"Weekly Summary Report - {name} {year}, Week {week} "
            f"({span[0]}-{span[1]} {name})")


def write_weekly_workbook(path, title, rows):
    """Save the rows as a formatted Excel sheet."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Weekly Summary"
    last_col = len(WEEKLY_COLUMNS)
    headings = [h for h, _ in WEEKLY_COLUMNS]

    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    blue = PatternFill("solid", fgColor="2E75B6")
    header_row = 1
    for index, (heading, width) in enumerate(WEEKLY_COLUMNS, start=1):
        cell = ws.cell(row=header_row, column=index, value=heading)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = blue
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center",
                                   wrap_text=True)
        ws.column_dimensions[get_column_letter(index)].width = max(width // 7, 9)

    def money_format(currency):
        # The currency shows in front of the amount; the cell stays a number.
        currency = currency.replace('"', "")
        return f'"{currency} "#,##0.00' if currency else "#,##0.00"

    totals = {}                     # currency -> sum of Total Price
    row_no = header_row
    for line in rows:
        row_no += 1
        for index, (heading, value) in enumerate(
                zip(headings, weekly_cells(line)), start=1):
            number_format = None
            if heading == "Date":
                value = parse_date(value)
                if isinstance(value, datetime):
                    number_format = "dd-mmm-yyyy"
                else:
                    value = str(value or "")
            elif heading in WEEKLY_NUMBER_COLUMNS:
                currency, amount = value
                value = to_number(amount)
                if isinstance(value, (int, float)):
                    number_format = money_format(currency)
                    if heading == "Total Price":
                        totals[currency] = totals.get(currency, 0) + value
                else:
                    value = price_text(currency, amount)
            cell = ws.cell(row=row_no, column=index, value=value or None)
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if number_format:
                cell.number_format = number_format

    if rows:
        # One TOTAL per currency (amounts in different currencies are
        # never added together).
        total_col = headings.index("Total Price") + 1
        for offset, currency in enumerate(sorted(totals), start=1):
            total_row = row_no + offset
            label = ws.cell(row=total_row, column=total_col - 1,
                            value=f"TOTAL {currency.upper()}".strip())
            label.font = Font(bold=True)
            label.alignment = Alignment(horizontal="right")
            total = ws.cell(row=total_row, column=total_col,
                            value=totals[currency])
            total.font = Font(bold=True)
            total.number_format = money_format(currency)
        ws.auto_filter.ref = (f"A{header_row}:"
                              f"{get_column_letter(last_col)}{row_no}")

    ws.oddHeader.center.text = title
    ws.freeze_panes = ws.cell(row=header_row + 1, column=2)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{header_row}:{header_row}"
    wb.save(path)


def weekly_selection():
    return int(year_var.get()), MONTH_LIST.index(month_var.get()) + 1, \
        week_var.get()


def choose_week(week):
    week_var.set(week)
    refresh_weekly()


def refresh_weekly(*_):
    """Reload the table for the chosen month / week."""
    try:
        year, month, week = weekly_selection()
    except (ValueError, tkinter.TclError):
        return
    for number, button in week_buttons.items():
        button.configure(
            bootstyle="info" if number == week else "secondary-outline")
    span = week_span(year, month, week)
    if span is None:
        range_label.configure(text=f"{calendar.month_name[month]} {year} "
                                   "has no Week 5.")
    else:
        range_label.configure(text="%s to %s  (by Inspection Date)" % (
            date(year, month, span[0]).strftime(DATE_FORMAT),
            date(year, month, span[1]).strftime(DATE_FORMAT)))

    problem = None
    try:
        rows = busy(weekly_rows, year, month, week, source_var_weekly.get())
    except PermissionError:
        rows, problem = [], "The Excel file is open in Excel - close it."
    except Exception as error:
        log.exception("Weekly summary failed")
        rows = []
        problem = (db_mysql.explain_error(error)
                   if source_var_weekly.get() == "mysql" else str(error))

    weekly_state["rows"] = rows
    summary_tree.delete(*summary_tree.get_children())
    for line in rows:
        summary_tree.insert("", "end", values=weekly_display(line))
    reports = len({(line[0], line[1]) for line in rows})
    summary_note.configure(
        text=problem or (f"{len(rows)} line(s) from {reports} report(s)"
                         if rows else "No reports in this period."),
        bootstyle="danger" if problem else "secondary")


def export_weekly_summary():
    rows = weekly_state["rows"]
    if not rows:
        messagebox.showinfo("Weekly Summary",
                            "There is nothing to export for this period.",
                            parent=window)
        return
    if Workbook is None:
        excel_missing_message()
        return
    year, month, week = weekly_selection()
    folder = Path(excel_state["path"]).parent / FORM_FOLDER_NAME
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = Path(excel_state["path"]).parent
    name = (f"Weekly Summary {calendar.month_name[month]} {year} "
            + ("Whole Month" if week == 0 else f"Week {week}") + ".xlsx")
    chosen = filedialog.asksaveasfilename(
        parent=window, title="Export the Weekly Summary",
        defaultextension=".xlsx", initialdir=str(folder), initialfile=name,
        filetypes=[("Excel Workbook", "*.xlsx")]
    )
    if not chosen:
        return
    try:
        busy(write_weekly_workbook, chosen, weekly_title(year, month, week),
             rows)
    except PermissionError:
        messagebox.showerror(
            "File In Use",
            f"Cannot write to:\n{chosen}\n\nClose it in Excel and try again.",
            parent=window)
        return
    except Exception as error:
        log.exception("Weekly summary export failed")
        messagebox.showerror("Export Error", f"Could not export:\n{error}",
                             parent=window)
        return
    notify(f"Exported {len(rows)} line(s) to {Path(chosen).name}")


def incident_header_defaults():
    """What the header of an Incident Report is filled with."""
    return {
        "vessel": transport_entries["vessel_carrier"].get().strip(),
        "client": consignee_combobox.get().strip(),
        "so_number": SO_number_entry.get().strip(),
        "port": location_combobox.get().strip(),
        "date": form_date(get_inspection_date()),
        "operation": schedule_entries["activity"].get().strip(),
    }


class IncidentSection:
    """One Incident Report card: header fields + up to 15 lines."""

    def __init__(self, parent, number, on_change):
        self.number = number
        self.on_change = on_change
        self.touched = set()        # header fields the user changed
        self.rows = []

        self.frame = tb.Labelframe(parent, text=incident_title(number),
                                   padding=12)
        self.frame.grid(row=number - 1, column=0, pady=6, sticky="we")
        self.frame.columnconfigure(0, weight=1)

        head = tb.Frame(self.frame)
        head.grid(row=0, column=0, sticky="we")
        for col in range(4):
            head.columnconfigure(col, weight=1, uniform="inc")

        self.fields = {}
        positions = {"vessel": (0, 0), "voyage": (0, 1), "client": (0, 2),
                     "so_number": (0, 3), "port": (1, 0), "date": (1, 1),
                     "operation": (1, 2)}
        for label, key in INCIDENT_HEADER_FIELDS:
            if key == "date":
                widget = tb.DateEntry(
                    head, dateformat=DATE_FORMAT, firstweekday=0,
                    bootstyle="primary"
                )
                typing = widget.entry
                widget.bind("<<DateEntrySelected>>",
                            lambda e, k=key: (self._touch(k), mark_dirty()),
                            add="+")
            elif key == "operation":
                widget = tb.Combobox(
                    head, state="normal",
                    values=[""] + CHOICE_VALUES["activity"]
                )
                typing = widget
                scroll_instead_of_change(widget)
                widget.bind("<<ComboboxSelected>>",
                            lambda e, k=key: self._touch(k), add="+")
            else:
                widget = tb.Entry(head)
                typing = widget
            typing.bind("<KeyRelease>",
                        lambda e, k=key: self._touch(k), add="+")
            row, col = positions[key]
            add_field(head, label, widget, row, col)
            self.fields[key] = widget

        self.lines_frame = tb.Frame(self.frame)
        self.lines_frame.grid(row=1, column=0, sticky="we", pady=(10, 0))
        self.lines_frame.columnconfigure(0, weight=1)

        self.toolbar = tb.Frame(self.frame)
        self.toolbar.grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.add_btn = tb.Button(
            self.toolbar, text="+ Add Line", width=20,
            command=self.add_line, bootstyle="primary-outline"
        )
        self.add_btn.grid(row=0, column=0, padx=(0, 6))
        self.remove_btn = tb.Button(
            self.toolbar, text="- Remove Line", command=self.remove_line,
            bootstyle="secondary-outline"
        )
        self.remove_btn.grid(row=0, column=1)
        self.counter = tb.Label(self.toolbar, anchor="w")
        self.counter.grid(row=0, column=2, padx=(15, 0), sticky="w")

        for _ in range(5):
            self.add_line(notify_change=False)
        self.refresh()

    # ---- header ----
    def _touch(self, key):
        self.touched.add(key)

    def get(self, key):
        widget = self.fields[key]
        entry = widget.entry if key == "date" else widget
        return entry.get().strip()

    def set(self, key, text):
        widget = self.fields[key]
        entry = widget.entry if key == "date" else widget
        set_entry(entry, text)

    def autofill(self, values):
        """Fill header fields the user has not edited."""
        for key, text in values.items():
            if key not in self.touched:
                self.set(key, text)

    # ---- lines ----
    def filled_count(self):
        return sum(1 for entry in self.rows if entry.get().strip())

    def is_full(self):
        return (len(self.rows) >= INCIDENT_MAX_LINES
                and self.filled_count() >= INCIDENT_MAX_LINES)

    def refresh(self, event=None):
        add_text = add_button_text(len(self.rows), INCIDENT_MAX_LINES)
        self.add_btn.configure(
            text=add_text,
            state="disabled" if len(self.rows) >= INCIDENT_MAX_LINES
            else "normal"
        )
        self.remove_btn.configure(
            state="disabled" if len(self.rows) <= 1 else "normal"
        )
        update_line_counter(self.counter, self.filled_count(),
                            INCIDENT_MAX_LINES)
        self.on_change()

    def add_line(self, notify_change=True):
        if len(self.rows) >= INCIDENT_MAX_LINES:
            return
        entry = tb.Entry(self.lines_frame, width=110)
        entry.grid(row=len(self.rows), column=0, padx=4, pady=3, sticky="we")
        entry.bind("<KeyRelease>", self.refresh, add="+")
        self.rows.append(entry)
        if notify_change:
            self.refresh()
            mark_dirty()

    def remove_line(self, notify_change=True):
        if len(self.rows) <= 1:
            return
        self.rows.pop().destroy()
        if notify_change:
            self.refresh()
            mark_dirty()

    def set_line_count(self, count):
        count = max(1, min(count, INCIDENT_MAX_LINES))
        while len(self.rows) < count:
            self.add_line(notify_change=False)
        while len(self.rows) > count:
            self.remove_line(notify_change=False)

    # ---- data ----
    def get_data(self):
        data = {key: self.get(key) for _, key in INCIDENT_HEADER_FIELDS}
        data["lines"] = [e.get().strip() for e in self.rows
                         if e.get().strip()]
        return data

    def set_data(self, data):
        """Fill the card; every header value stays as given."""
        data = data or {}
        for _, key in INCIDENT_HEADER_FIELDS:
            self.set(key, str(data.get(key) or ""))
        # A saved card keeps its header; a blank one follows the report.
        self.touched = ({key for _, key in INCIDENT_HEADER_FIELDS}
                        if data else set())
        lines = list(data.get("lines") or [])
        self.set_line_count(max(5, len(lines)))
        for entry in self.rows:
            entry.delete(0, "end")
        for entry, text in zip(self.rows, lines):
            entry.insert(0, text)
        self.refresh()

    def destroy(self):
        self.frame.destroy()


def refresh_incident_buttons():
    if not incident_cards:
        return
    last = incident_cards[-1]
    add_more_button.configure(state="normal" if last.is_full() else "disabled")
    remove_last_button.configure(
        state="normal" if len(incident_cards) > 1 else "disabled"
    )
    if last.is_full():
        incident_hint.configure(
            text="All 15 lines are used - add an Additional Incident Report "
                 "to continue.", bootstyle="warning"
        )
    else:
        incident_hint.configure(
            text=f"The button is available once all {INCIDENT_MAX_LINES} "
                 f"lines of \"{incident_title(len(incident_cards))}\" "
                 "are filled.", bootstyle="secondary"
        )


def add_incident_card(copy_voyage=True, autofill=True):
    card = IncidentSection(incident_cards_frame, len(incident_cards) + 1,
                           refresh_incident_buttons)
    if autofill:
        card.autofill(incident_header_defaults())
    if copy_voyage and incident_cards:
        card.set("voyage", incident_cards[0].get("voyage"))
        card.touched.add("voyage")
    incident_cards.append(card)
    refresh_incident_buttons()
    return card


def add_additional_incident():
    if not incident_cards or not incident_cards[-1].is_full():
        return
    card = add_incident_card()
    mark_dirty()
    incident_tab.update_idletasks()
    scroll_to_widget(card.rows[0])
    card.rows[0].focus_set()


def remove_last_incident():
    if len(incident_cards) <= 1:
        return
    last = incident_cards[-1]
    if last.filled_count() and not messagebox.askyesno(
        "Remove Incident Report",
        f"Remove \"{incident_title(len(incident_cards))}\" and its "
        f"{last.filled_count()} line(s)?",
        parent=window
    ):
        return
    incident_cards.pop().destroy()
    refresh_incident_buttons()
    mark_dirty()


def set_incident_reports(reports):
    """Show these cards (an empty list = one empty card)."""
    reports = list(reports or [])
    wanted = max(1, len(reports))
    while len(incident_cards) > wanted:
        incident_cards.pop().destroy()
    while len(incident_cards) < wanted:
        add_incident_card(copy_voyage=False)
    for index, card in enumerate(incident_cards):
        card.set_data(reports[index] if index < len(reports) else None)
    refresh_incident_buttons()


def collect_incident_reports():
    return [card.get_data() for card in incident_cards]


def incidents_have_content():
    return any(card.filled_count() for card in incident_cards)


def autofill_incidents():
    values = incident_header_defaults()
    for card in incident_cards:
        card.autofill(values)


def show_incident_tab(show, select=False):
    present = str(incident_tab) in notebook.tabs()
    if show and not present:
        notebook.add(incident_tab, text=INCIDENT_TAB_TEXT)
    elif not show and present:
        notebook.forget(incident_tab)
    if show and select:
        notebook.select(incident_tab)
    if "refresh_nav" in globals():
        refresh_nav()


def set_condition(value, select=False):
    """Switch Good / Bad Order. Good Order removes the incident tab."""
    condition_var.set(value)
    if value == CONDITION_BAD:
        if not incident_cards:
            add_incident_card(copy_voyage=False)
        autofill_incidents()
        show_incident_tab(True, select=select)
    else:
        set_incident_reports([])
        show_incident_tab(False)


def on_condition_clicked():
    value = condition_var.get()
    if value == CONDITION_GOOD and incidents_have_content():
        if not messagebox.askyesno(
            "Good Order",
            "Good Order has no Incident Report.\n\nThe incident lines "
            "you typed will be removed (and the saved incident file is "
            "deleted when you save).\n\nContinue?",
            parent=window
        ):
            condition_var.set(CONDITION_BAD)
            return
    set_condition(value, select=True)
    mark_dirty()


def on_tab_changed(event=None):
    """Refresh the Incident Report header from the report when opened."""
    try:
        if notebook.select() == str(incident_tab):
            autofill_incidents()
        elif notebook.select() == str(summary_tab):
            refresh_weekly()
    except tkinter.TclError:
        pass
    update_form_lock()
    if "refresh_nav" in globals():
        refresh_nav()


def refresh_nav(*_):
    """Show a button for every open page; the current one is highlighted."""
    try:
        current, pages = notebook.select(), notebook.tabs()
    except tkinter.TclError:
        return
    for tab, button in nav_buttons:
        button.pack_forget()
        if str(tab) in pages:
            button.configure(
                bootstyle="info" if current == str(tab) else "secondary-outline"
            )
            button.pack(fill="x", pady=3)


# =====================================================
# EXCEL STORAGE (Control # based)
# =====================================================
# The Excel storage (REPORT_HEADERS, read_report(),
# write_report_to_excel() ...) is in fsr_storage.py.


# =====================================================
# FORM <-> DATA
# =====================================================

def filled(entries):
    """Return the non-empty text of a list of Entry widgets."""
    return [e.get().strip() for e in entries if e.get().strip()]


def collect_report_data():
    """Gather everything typed into the form as one dictionary."""

    declared_goods = []
    for description, quantity, packaging in declared_goods_rows:
        row = {
            "description": description.get().strip(),
            "quantity": quantity.get().strip(),
            "packaging": packaging.get().strip(),
        }
        if any(row.values()):
            declared_goods.append(row)

    item_lists = [
        {"name": f"Item List {index}", "rows": section.values()}
        for index, section in enumerate(item_frames, start=1)
    ]

    condition = condition_var.get()

    return withdrawal_panel.fill_report({
        "control_no": control_entry.get().strip(),
        "cargo_condition": condition,
        "item_form": item_form_var.get(),
        "other_item_forms": collect_other_item_forms(),
        "goods_types": collect_goods_types(),
        "incident_reports": (
            collect_incident_reports() if condition == CONDITION_BAD else []
        ),
        "general_information": {
            "so_number": SO_number_entry.get().strip(),
            "inspection_date": get_inspection_date(),
            "consignee": consignee_combobox.get().strip(),
            "supplier": supplier_combobox.get().strip(),
            "brokerage": brokerage_combobox.get().strip(),
            "hauler": hauler_combobox.get().strip(),
            "location": location_combobox.get().strip(),
            "destination": destination_combobox.get().strip(),
            "country_of_origin": country_combobox.get().strip(),
        },
        "inspection_schedule": {
            key: entry.get().strip()
            for key, entry in schedule_entries.items()
        },
        "transport_details": {
            key: entry.get().strip()
            for key, entry in transport_entries.items()
        },
        "documents_used": {
            key: document_entries[key].get().strip()
            for _, key in DOCUMENT_FIELDS
        },
        "declared_goods": declared_goods,
        "other_important_remarks": filled(other_remarks_entries),
        "item_lists": item_lists,
        "findings_and_remarks": filled(findings_entries),
    })


def set_entry(entry, text):
    if isinstance(entry, ttk.Combobox):
        state = str(entry.cget("state"))
        if state == "readonly":
            entry.set(text)
            return

    entry.delete(0, "end")
    entry.insert(0, text)


def set_control_number(text):
    control_entry.configure(state="normal")
    set_entry(control_entry, text)
    control_entry.configure(state="readonly")


def update_status():
    """Show whether the form is new, saved or has unsaved changes."""
    editing = report_state["editing"]
    dirty = report_state["dirty"]

    if dirty:
        text, badge = "UNSAVED CHANGES", "inverse-warning"
    elif editing:
        text, badge = "SAVED REPORT", "inverse-success"
    else:
        text, badge = "NEW REPORT", "inverse-info"

    status_badge.configure(text=text, bootstyle=badge)
    file_label.configure(text=f"File: {Path(excel_state['path']).name}")
    window.title(
        f"{'* ' if dirty else ''}{title_prefix()}Field Survey Report - "
        f"{control_entry.get()} - {Path(excel_state['path']).name}"
    )


def clear_form():
    """Empty every field and reset the dynamic sections."""

    for entry in [SO_number_entry, *document_entries.values()]:
        entry.delete(0, "end")

    for combo in searchable_combos:
        combo.set("")

    # SO Number and Consignee stay as they were in the last report.
    SO_number_entry.insert(0, settings.get("last_so_number", ""))
    consignee_combobox.set(settings.get("last_consignee", ""))

    for entry in [*schedule_entries.values(), *transport_entries.values()]:
        set_entry(entry, "")
        mark_entry(entry, False)

    set_inspection_date(date.today().strftime(DATE_FORMAT))
    date_sync["last"] = ""
    sync_commenced_date()               # Commenced Date = Inspection Date

    for row in declared_goods_rows:
        for entry in row:
            entry.delete(0, "end")

    other_remarks_frame.set_row_count(5)
    for entry in other_remarks_entries:
        entry.delete(0, "end")

    findings_frame.set_row_count(5)
    for entry in findings_entries:
        entry.delete(0, "end")

    set_item_form(ITEM_FORM_DEFAULT)
    item_form_store.clear()
    set_item_list_count(1)
    item_frames[0].set_row_count(5)
    item_frames[0].clear()

    set_goods_types(None)
    set_condition("")                   # also clears + hides the incident tab
    withdrawal_panel.reset()

    other_remarks_frame.refresh_counter()
    findings_frame.refresh_counter()

    for sf in scroll_frames:
        sf.canvas.yview_moveto(0)
        sf.canvas.xview_moveto(0)
    notebook.select(general_tab)


def populate_form(data):
    """Fill the form with a report read from Excel."""
    clear_form()

    general = data["general_information"]
    set_entry(SO_number_entry, general["so_number"])

    day = parse_any_date(general["inspection_date"])
    if day is not None:
        set_inspection_date(day.strftime(DATE_FORMAT))

    consignee_combobox.set(general["consignee"])
    supplier_combobox.set(general["supplier"])
    brokerage_combobox.set(general["brokerage"])
    hauler_combobox.set(general["hauler"])
    location_combobox.set(general.get("location", ""))
    destination_combobox.set(general.get("destination", ""))
    country_combobox.set(general.get("country_of_origin", ""))

    for key, entry in schedule_entries.items():
        set_entry(entry, data["inspection_schedule"].get(key, ""))
    for key, entry in transport_entries.items():
        set_entry(entry, data["transport_details"].get(key, ""))

    for key, entry in document_entries.items():
        set_entry(entry, data["documents_used"].get(key, ""))

    for entries, row in zip(declared_goods_rows, data["declared_goods"]):
        for entry, key in zip(entries, ("description", "quantity", "packaging")):
            set_entry(entry, row[key])

    for section_frame, entries, remarks in (
        (other_remarks_frame, other_remarks_entries,
         data["other_important_remarks"]),
        (findings_frame, findings_entries,
         data["findings_and_remarks"]),
    ):
        section_frame.set_row_count(max(5, len(remarks)))
        for entry, text in zip(entries, remarks):
            set_entry(entry, text)

    set_item_form(data.get("item_form"))
    set_item_list_count(len(data["item_lists"]))
    for section, item_list in zip(item_frames, data["item_lists"]):
        section.set_values(item_list["rows"])
    for form, item_lists in (data.get("other_item_forms") or {}).items():
        if form != item_form_var.get():
            item_form_store[form] = [
                (item_list["rows"], max(5, len(item_list["rows"])))
                for item_list in item_lists
            ]

    set_goods_types(data.get("goods_types"))
    set_condition(data.get("cargo_condition", CONDITION_GOOD))
    set_incident_reports(data.get("incident_reports") or [])

    other_remarks_frame.refresh_counter()
    findings_frame.refresh_counter()


def busy(func, *args):
    """Run func with a 'busy' mouse cursor (for quick jobs)."""
    window.configure(cursor="watch")
    window.update_idletasks()
    try:
        return func(*args)
    finally:
        window.configure(cursor="")


def center_over_window(dialog, y_offset=100):
    dialog.update_idletasks()
    x = window.winfo_rootx() + max(
        (window.winfo_width() - dialog.winfo_reqwidth()) // 2, 0
    )
    y = window.winfo_rooty() + y_offset
    dialog.geometry(f"+{x}+{y}")


def run_with_progress(parent, message, work, on_done, with_progress=False):
    """
    Run work() in a background thread while a small progress window
    keeps the program responsive. on_done(result, error) runs on the
    GUI thread when the job finishes. with_progress: work(progress) gets
    a function progress(text, done=None, total=None) to call from its
    thread; the window shows the text and a bar.
    """
    dialog = tb.Toplevel(parent)
    dialog.title("Please wait")
    dialog.transient(parent)
    dialog.resizable(False, False)
    dialog.protocol("WM_DELETE_WINDOW", lambda: None)

    tb.Label(dialog, text=message, padding=(24, 20, 24, 8)).pack()
    step_label = tb.Label(dialog, text="", padding=(24, 0, 24, 8),
                          bootstyle="secondary")
    if with_progress:
        step_label.pack()
    bar = tb.Progressbar(dialog, mode="indeterminate", length=320,
                         bootstyle="striped")
    bar.pack(padx=24, pady=(0, 20))
    bar.start(12)

    center_over_window(dialog, 160)
    dialog.wait_visibility()
    dialog.grab_set()

    outcome = {}
    shown = {"text": None, "done": None, "total": None}
    latest = dict(shown)

    def progress(text, done=None, total=None):
        # from the working thread: only remembered here, shown by poll()
        latest.update(text=text, done=done, total=total)

    def target():
        try:
            outcome["value"] = work(progress) if with_progress else work()
        except Exception as error:
            log.exception("Background job failed")
            outcome["error"] = error

    thread = threading.Thread(target=target, daemon=True)
    thread.start()

    def show_progress():
        now = dict(latest)
        if now == shown:
            return
        shown.update(now)
        step_label.configure(text=now["text"] or "")
        if now["total"]:
            if str(bar.cget("mode")) != "determinate":
                bar.stop()
                bar.configure(mode="determinate")
            bar.configure(maximum=now["total"], value=now["done"] or 0)

    def poll():
        if thread.is_alive():
            if with_progress:
                show_progress()
            window.after(100, poll)
            return
        bar.stop()
        dialog.grab_release()
        dialog.destroy()
        on_done(outcome.get("value"), outcome.get("error"))

    poll()


def save_forms_as_pdf(forms, data, parent):
    """Let the user pick a folder, then save the whole report as one PDF."""
    start_folder = pdf_state["folder"] or str(Path(forms[0]).parent)
    if not Path(start_folder).exists():
        start_folder = str(Path(forms[0]).parent)

    folder = filedialog.askdirectory(
        parent=parent,
        title="Select the folder where the PDF will be saved",
        initialdir=start_folder,
        mustexist=True
    )
    if not folder:
        return

    pdf_state["folder"] = folder
    settings["pdf_folder"] = folder
    save_settings()

    so_number = data["general_information"]["so_number"]
    pdf_path = Path(folder) / (
        f"{safe_filename(data['control_no'])}_"
        f"{safe_filename(so_number)}_Field_Survey_Report.pdf"
    )

    if pdf_path.exists() and not messagebox.askyesno(
        "Replace PDF",
        f"This PDF already exists:\n{pdf_path}\n\nReplace it?",
        parent=parent
    ):
        return

    def done(_, error):
        if error is not None:
            messagebox.showerror("PDF Error", str(error), parent=parent)
            return

        if messagebox.askyesno(
            "PDF Saved",
            f"PDF saved to:\n{pdf_path}\n\nOpen it now?",
            parent=parent
        ):
            open_file(pdf_path)

    run_with_progress(
        parent, "Creating the PDF...",
        lambda: make_report_pdf(forms, pdf_path), done
    )


def print_report_forms(forms, data, parent):
    """Print the whole report (the same pages as the PDF)."""
    pdf_path = Path(forms[0]).parent / (
        f"{safe_filename(data['control_no'])}_Report.pdf"
    )

    def work():
        make_report_pdf(forms, pdf_path)
        return send_to_printer(pdf_path)

    def done(result, error):
        if error is not None:
            messagebox.showerror(
                "Print Error",
                f"Unable to print the report:\n{error}",
                parent=parent
            )
        elif result == "opened":
            messagebox.showinfo(
                "Print Report",
                "The report was opened in your PDF viewer.\n"
                "Press Ctrl+P there to choose a printer and print it.",
                parent=parent
            )
        else:
            messagebox.showinfo(
                "Print Report",
                "The report was sent to the default printer.",
                parent=parent
            )

    run_with_progress(parent, "Preparing the report for printing...",
                      work, done)


def create_report_forms(excel_path, data):
    """
    Fill every page of the report and put them in ONE workbook:
    First Page, Cargo Details of every Item List form with lines (the
    remarks follow the last one), Incident Report(s) - one sheet per page -
    saved as "Report Forms/<Control #>_Report.xlsx".
    Returns (forms, notes, summary): [that workbook], things the user
    should know about, and a one-line description.
    """
    folder = Path(excel_path).parent / FORM_FOLDER_NAME
    control = data["control_no"]
    notes, pieces = [], []
    # A report from the phone prints its inspector's name, not this user's.
    print_name["value"] = (
        data_store(excel_path).imported_inspector(control) or USER_FULL_NAME)
    summary = "First Page"

    with tempfile.TemporaryDirectory() as temp_dir:
        first_page, notes = create_report_form(excel_path, data, temp_dir)
        pieces.append(first_page)

        remarks = data["findings_and_remarks"]
        cargo_forms = item_forms_to_print(data)
        if not cargo_forms and remarks:     # remarks only: they need a page
            cargo_forms = [(item_form_name(data.get("item_form")),
                            data["item_lists"])]

        for number, (form, item_lists) in enumerate(cargo_forms, start=1):
            name = "Cargo Details"
            if len(cargo_forms) > 1 and form != ITEM_FORM_DEFAULT:
                name = f"{form} Details"
            page_data = dict(
                data, item_form=form, item_lists=item_lists,
                findings_and_remarks=(
                    remarks if number == len(cargo_forms) else []),
            )
            try:
                cargo, pages = create_cargo_form(excel_path, page_data,
                                                 temp_dir, name)
            except Exception as error:
                log.exception("Cargo Details page failed")
                notes.append(
                    f"The {name} page could not be created, so it is not "
                    f"in the report:\n{error}"
                )
            else:
                pieces.append(cargo)
                summary += f" + {name} ({pages['cargo']} page"
                summary += "s)" if pages["cargo"] != 1 else ")"
                if pages["blank"]:
                    summary += f" + Additional Details ({pages['blank']} page"
                    summary += "s)" if pages["blank"] != 1 else ")"

        # Bad Order: the Incident Report page(s) follow the Cargo Details.
        if data.get("cargo_condition") == CONDITION_BAD:
            try:
                incident, count = create_incident_form(
                    excel_path, data, temp_dir)
            except Exception as error:
                log.exception("Incident Report page failed")
                notes.append(
                    "The Incident Report page could not be created, so it "
                    f"is not in the report:\n{error}"
                )
            else:
                if incident is None:
                    notes.append(
                        "Bad Order is selected but no incident lines were "
                        "typed, so there is no Incident Report page."
                    )
                else:
                    pieces.append(incident)
                    summary += f" + Incident Report ({count} page"
                    summary += "s)" if count != 1 else ")"

        workbook = report_workbook_path(excel_path, control)
        merge_workbooks(pieces, workbook, first_name="First Page")

    # Older versions saved every page as a separate file: tidy them away.
    for suffix in ("First_Page", "Cargo_Details", "Incident_Report"):
        try:
            (folder / f"{safe_filename(control)}_{suffix}.xlsx").unlink()
        except OSError:
            pass

    return [workbook], notes, summary


def show_output_dialog(title, message, excel_path, forms, data,
                       warning=None):
    """Print the report, save it as PDF, or finish."""

    dialog = tb.Toplevel(window)
    dialog.title(title)
    dialog.transient(window)
    dialog.resizable(False, False)

    tb.Label(
        dialog, text=message, justify="left", anchor="w", wraplength=520
    ).pack(fill="x", padx=20, pady=(20, 10))

    if warning:
        tb.Label(
            dialog, text=warning, justify="left", anchor="w",
            wraplength=520, bootstyle="danger"
        ).pack(fill="x", padx=20, pady=(0, 10))

    if forms:
        tb.Label(
            dialog, text="What would you like to do with the report?",
            font=bold_font, anchor="w"
        ).pack(fill="x", padx=20, pady=(5, 5))

    buttons = tb.Frame(dialog)
    buttons.pack(fill="x", padx=20, pady=(5, 20))

    def action_button(text, command, style_name, enabled=True):
        button = tb.Button(
            buttons, text=text, width=16, command=command,
            bootstyle=style_name,
            state="normal" if enabled else "disabled"
        )
        button.pack(side="left", padx=(0, 8))
        return button

    action_button(
        "Print Report",
        lambda: print_report_forms(forms, data, dialog),
        "primary", enabled=bool(forms)
    )
    action_button(
        "Save as PDF...",
        lambda: save_forms_as_pdf(forms, data, dialog),
        "primary-outline", enabled=bool(forms)
    )
    action_button(
        "Open Report Excel",
        lambda: open_file(forms[0]),
        "secondary-outline", enabled=bool(forms) and Path(forms[0]).exists()
    )
    tb.Button(
        buttons, text="Done", width=10, command=dialog.destroy,
        bootstyle="secondary"
    ).pack(side="right")

    center_over_window(dialog)

    dialog.bind("<Escape>", lambda e: dialog.destroy())
    dialog.wait_visibility()
    dialog.grab_set()
    dialog.focus_set()


def print_pdf_current_report():
    """Print / PDF for what is on the form now (no need to save first)."""
    if not validate_format_fields():
        return

    data = collect_report_data()
    path = excel_state["path"]

    try:
        forms, notes, summary = busy(create_report_forms, path, data)
    except PermissionError:
        messagebox.showerror(
            "File In Use",
            "A report form is open in another program.\n"
            "Close it and try again.",
            parent=window
        )
        return
    except Exception as error:
        log.exception("Report form failed")
        messagebox.showerror(
            "Report Form Error", str(error), parent=window
        )
        return

    show_output_dialog(
        "Print / PDF",
        f"Report {data['control_no']} is ready:\n{summary}",
        path, forms, data,
        warning="\n".join(notes) or None
    )


# =====================================================
# REPORT ACTIONS (New / Open / Save / Change file)
# =====================================================

def excel_missing_message():
    messagebox.showerror(
        "openpyxl Not Installed",
        "Saving to Excel needs the openpyxl package.\n\n"
        "Install it with:\n    pip install openpyxl",
        parent=window
    )


def confirm_discard(title, question):
    """True when there is nothing unsaved, or the user agrees to lose it."""
    if not report_state["dirty"]:
        return True
    return messagebox.askyesno(
        title,
        f"{question}\n\nAnything on the form that is not saved will be lost.",
        parent=window
    )


def mysql_guard():
    """The guard of the Excel file in use: every write to MySQL goes
    through it (fsr_mysql_guard)."""
    return data_store().mysql_guard(db_mysql, user=USER_FULL_NAME)


def mysql_in_use():
    return db_mysql is not None and db_mysql.is_enabled()


def next_new_control_number():
    """The next Control # that is free in this PC's workbooks and - as far
    as MySQL was seen - in MySQL too, so two copies of the program do not
    hand out the same number."""
    path = excel_state["path"]
    if not mysql_numbers["values"] or not mysql_in_use():
        return data_store(path).next_control_number()
    try:
        local = data_store(path).control_numbers()
    except Exception:
        log.exception("Could not read the control numbers")
        return data_store(path).next_control_number()
    return fsr_storage_next_number([*local, *mysql_numbers["values"]])


def fsr_storage_next_number(numbers):
    import fsr_storage
    return fsr_storage.next_control_number(numbers)


def refresh_mysql_numbers():
    """Read the Control #s of MySQL (called when the server answers)."""
    if not mysql_in_use() or not hasattr(db_mysql, "control_numbers"):
        mysql_numbers["values"] = []
        return
    try:
        mysql_numbers["values"] = list(db_mysql.control_numbers())
    except Exception:
        mysql_numbers["values"] = []
        return
    # A new, untouched report on the form takes a number free in both.
    if not report_state["editing"] and not report_state["dirty"]:
        wanted = next_new_control_number()
        if wanted != control_entry.get().strip():
            set_control_number(wanted)
            report_state["dirty"] = False
            update_status()


def free_number_for_new_report(control):
    """At save time: a NEW report whose number MySQL holds (from another
    copy, as far as MySQL was last seen) gets the next number free in both
    places, before anything is written. No connection is opened for this -
    the save never waits for MySQL. If another copy took the number since
    MySQL was last seen, the background sender finds out and hands the
    report on to the next free number (hand_on_number)."""
    try:
        taken = mysql_numbers["values"]
        if not any(same_key(number, control) for number in taken):
            return control
        if mysql_guard().owns(control):
            return control
        return fsr_storage_next_number(
            [*data_store().control_numbers(), *taken])
    except Exception:
        return control


# =====================================================
# MYSQL IN THE BACKGROUND (fsr_mysql_sender)
# A save is finished on this PC; its MySQL step waits in the save record
# and is done by a background round over one connection.
# =====================================================

def adopt_reports(path, guard, connection=None, root=None):
    """Reports that MySQL holds with the same value become this copy's own
    (no question, nothing written to MySQL) - only while the ledger is
    still empty. One read of each workbook. Safe in the background."""
    with guard.reading():
        if guard.ledger()["reports"]:
            return []
        reports = fsr_storage_read_all(path)
        reports += data_store(path, root).read_all_withdrawal_reports()
    if not reports:
        return []
    return guard.adopt_identical(reports, connection=connection)


def fsr_storage_read_all(path):
    if not Path(path).exists():
        return []
    return data_store(path).read_all_reports()


def mysql_round(path, master=None, user="", root=None, with_conflicts=False,
                catch_up=False, compose=False, numbers=False, adopt=False,
                save_id=None):
    """ONE background round (runs in the sender's thread - no window
    calls here): every report waiting for MySQL is sent through the guard
    over one connection; then the master lists and, when asked, MySQL's
    Control #s and the first-run adoption."""
    result = {"sent": [], "sent_ids": [], "notes": {}, "conflicts": [],
              "errors": [], "away": None, "numbers": None, "attempted": 0,
              "adopted": []}
    journal = data_store(path).save_record()
    waiting = fsr_save_journal.waiting_for_mysql(journal, with_conflicts)
    result["attempted"] = len(waiting)
    if not waiting and not numbers and not adopt:
        return result
    unreachable = getattr(db_mysql, "is_unreachable", lambda error: False)
    guard = data_store(path, root).mysql_guard(db_mysql, user=user)
    stores = data_store(path, root).save_steps(mysql=db_mysql, guard=guard)
    supported = fsr_mysql_guard.supports(db_mysql)
    conn = db_mysql.connect() if supported else None
    try:
        stores.connection = conn
        if adopt and supported:
            try:
                result["adopted"] = adopt_reports(path, guard, conn, root)
            except Exception:
                log.exception("Could not compare the reports with MySQL")
        if waiting:
            result.update(fsr_save_journal.send_waiting(
                journal, stores, with_conflicts, unreachable))
            if result["away"] is None:
                try:
                    if conn is not None:
                        db_mysql.save_master_lists(master or {}, conn)
                    else:
                        db_mysql.save_master_lists(master or {})
                except Exception as error:
                    if unreachable(error):
                        result["away"] = error
                    else:
                        log.exception("MySQL master lists failed")
        if result["away"] is None and supported and hasattr(
                db_mysql, "control_numbers"):
            try:
                result["numbers"] = list(db_mysql.control_numbers(conn))
            except Exception:
                log.exception("Could not read MySQL's Control #s")
    finally:
        if conn is not None:
            try:
                conn.close()
            # Broad on purpose: closing a lost connection may raise anything
            # the driver likes; the round's result is what matters.
            except Exception:
                log.debug("MySQL connection not closed cleanly",
                          exc_info=True)
    return result


def request_mysql_round(**flags):
    """Ask the sender for a round with this PC's settings."""
    if not mysql_in_use():
        return
    mysql_sender.request(
        path=excel_state["path"], master=copy.deepcopy(master_data),
        user=USER_FULL_NAME, root=DATA_DIR if DEMO_MODE else None, **flags)
    refresh_mysql_waiting()


def use_mysql_numbers(numbers):
    """MySQL's Control #s, as just read: a new, untouched report on the form
    takes a number free in both places."""
    mysql_numbers["values"] = list(numbers)
    if not report_state["editing"] and not report_state["dirty"]:
        wanted = next_new_control_number()
        if wanted != control_entry.get().strip():
            set_control_number(wanted)
            report_state["dirty"] = False
            update_status()


def hand_on_number(record, numbers):
    """A NEW report's number turned out to be used in MySQL by another copy
    (taken after MySQL was last seen): it gets the next number free on this
    PC and in MySQL - everywhere on this PC - and is sent under that. This
    is what Save did before it wrote anything, now done right after. True
    when it was done."""
    path = excel_state["path"]
    old = record["control"]
    root = DATA_DIR if DEMO_MODE else None
    guard = mysql_guard()
    stores = data_store(path, root).save_steps(mysql=db_mysql, guard=guard)
    journal = data_store(path).save_record()
    try:
        new = data_store(path).next_free_number(old, list(numbers or []))

        def change(old_number, new_number):
            with guard.local_write():
                data_store(path, root).renumber(old_number, new_number)

        moved = fsr_save_journal.renumber_record(journal, stores,
                                                 record["id"], new, change)
    except Exception:
        log.exception("Could not give %s the next free number", old)
        return False
    log.warning("%s was already used in MySQL by another copy of the "
                "program; the report saved here is now %s.", old, new)
    if same_key(control_entry.get().strip(), old):
        dirty = report_state["dirty"]
        set_control_number(new)
        report_state["dirty"] = dirty
        update_status()
    try:
        busy(create_report_forms, path, moved["data"])
    except Exception:
        log.exception("Report form of %s not made again", new)
    notify(f"{old} was already used in MySQL by another copy of the "
           f"program. Your report is now {new}, here and in MySQL.",
           bootstyle="warning")
    return True


def mysql_round_done(item):
    """On the window's thread: tell the user what a round did."""
    request = item["request"]
    result = item["result"] or {}
    error = item["error"] or result.get("away")
    compose = request.get("save_id") if request.get("compose") else None
    unreachable = getattr(db_mysql, "is_unreachable", lambda e: False)
    dots = "set_mysql_dots" in globals()

    if result.get("numbers") is not None:
        use_mysql_numbers(result["numbers"])
    for control in result.get("sent", []):
        if control not in mysql_numbers["values"]:
            mysql_numbers["values"].append(control)

    others = [control for record_id, control in zip(
        result.get("sent_ids", []), result.get("sent", []))
        if record_id != compose]
    if compose in result.get("sent_ids", []):
        mysql_feedback[compose] = ("sent", result["notes"].get(compose))
    if others:
        if request.get("catch_up") or compose:
            notify(f"MySQL caught up: {len(others)} report(s) saved earlier "
                   "on this PC are now in MySQL")
        elif len(others) == 1:
            notify(f"Report {others[0]} is now in MySQL")
        else:
            notify(f"{len(others)} reports are now in MySQL")

    if error is not None:
        away = unreachable(error)
        if dots:
            set_mysql_dots("bad", "MySQL was not reached. Is the MySQL80 "
                           "service running?" if away
                           else db_mysql.explain_error(error))
        try:
            left = len(fsr_save_journal.waiting_for_mysql(
                data_store().save_record()))
        except Exception:
            left = 0
        if compose:
            mysql_feedback.setdefault(compose, ("away" if away else "error",
                                                error))
        elif left:
            if away:
                notify(f"MySQL was not reached  -  {left} report(s) saved on "
                       "this PC wait; they are sent at the next save or "
                       "start", bootstyle="warning")
            else:
                messagebox.showwarning(
                    "MySQL - Not Updated",
                    f"{left} report(s) are saved on this PC but NOT in "
                    f"MySQL:\n{db_mysql.explain_error(error)}\n\nThey are "
                    "tried again at the next save or start, or use 'Sync to "
                    "MySQL'.", parent=window)
    elif dots and (result.get("attempted") or result.get("numbers")
                   is not None):
        set_mysql_dots("ok")

    handed_on, new_conflicts = False, []
    for record, conflict, new in result.get("conflicts", []):
        # Handed on to the next free number only on the save's own first
        # send (what Save used to check before writing). A clash found
        # later - saved while MySQL was away - is the user's decision.
        if (record["id"] == request.get("save_id") and record.get("new")
                and conflict.get("kind") == fsr_mysql_guard.NOT_OWNED
                and not record.get("renumbered_from")
                and hand_on_number(record, result.get("numbers"))):
            handed_on = True
        elif record["id"] == compose:
            mysql_feedback[compose] = ("conflict", conflict)
        elif new:
            new_conflicts.append((record, conflict))
    for record_id, _control, failure in result.get("errors", []):
        if record_id == compose:
            mysql_feedback[compose] = ("error", failure)
    if handed_on:
        request_mysql_round(compose=request.get("compose", False),
                            save_id=request.get("save_id"))
    if new_conflicts:
        listing = "\n\n".join(conflict["text"]
                              for _, conflict in new_conflicts[:5])
        messagebox.showwarning(
            "MySQL - Not Updated",
            f"{len(new_conflicts)} report(s) saved on this PC were NOT sent "
            f"to MySQL:\n\n{listing}\n\nNothing in MySQL was changed. Decide "
            "in the MySQL Conflicts window what to do; until then MySQL "
            "keeps its report.", parent=window)
        open_mysql_conflicts(select=new_conflicts[0][0]["id"])
    if result.get("adopted"):
        log.info("%d report(s) are the same in the Excel file and in MySQL "
                 "and are now this copy's own.", len(result["adopted"]))
    refresh_conflict_count()
    refresh_mysql_waiting()
    if result.get("sent") and globals().get("app_shell") is not None:
        app_shell.service.invalidate()


def lists_round(path, root=None, compose=False, save_id=None):
    """Background thread: rebuild PO_Master and Withdrawn_Item once for
    every save waiting for it (no window calls here)."""
    journal = data_store(path).save_record()
    stores = data_store(path, root).save_steps()
    return fsr_save_journal.rebuild_lists(journal, stores)


def lists_round_done(item):
    """On the window's thread: what the rebuild did."""
    request = item["request"]
    result = item["result"] or {}
    error = item["error"] or result.get("error")
    compose = request.get("save_id") if request.get("compose") else None
    if compose and compose in result.get("ids", []):
        lists_feedback[compose] = error
        return
    if error is None:
        lists_state["warned"] = False
        if result.get("rebuilt"):
            status_var.set("PO_Master and Withdrawn_Item are up to date ("
                           + datetime.now().strftime("%H:%M") + ")")
        return
    if lists_state["warned"]:
        return                      # said once until they are up to date
    lists_state["warned"] = True
    if isinstance(error, PermissionError):
        text = ("PO_Master or Withdrawn_Item could not be updated because "
                "it is open in another program (Excel?).\nClose it; both "
                "lists are updated at the next save or the next start.")
    else:
        text = ("PO_Master and Withdrawn_Item could not be updated:\n"
                f"{error}\n\nThey are tried again at the next save or "
                "the next start.")
    messagebox.showwarning("PO_Master - Not Updated", text, parent=window)


def request_lists_round(**flags):
    lists_sender.request(path=excel_state["path"],
                         root=DATA_DIR if DEMO_MODE else None, **flags)


def refresh_mysql_waiting():
    """The note beside the MySQL circles: reports not in MySQL yet."""
    label = globals().get("mysql_waiting_label")
    if label is None:
        return
    try:
        count = len(fsr_save_journal.waiting_for_mysql(
            data_store().save_record()))
    except Exception:
        count = 0
    if not mysql_in_use() or not count:
        text = ""
    elif not mysql_sender.idle():
        text = f"Sending {count} to MySQL..."
    else:
        text = f"{count} waiting for MySQL"
    try:
        label.configure(text=text)
    except tkinter.TclError:
        pass


def poll_mysql_sender():
    """Hand finished rounds to mysql_round_done(); runs every 1/4 s."""
    try:
        mysql_sender.poll()
        lists_sender.poll()
        busy_now = not mysql_sender.idle()
        if busy_now != mysql_wait_state["busy"]:
            mysql_wait_state["busy"] = busy_now
            refresh_mysql_waiting()
    finally:
        try:
            window.after(250, poll_mysql_sender)
        except tkinter.TclError:
            pass


def new_report(confirm=True):
    """Clear the form and give it the next Control #."""
    if confirm and not confirm_discard("New Report", "Start a new report?"):
        return

    clear_form()
    report_state["editing"] = False
    set_control_number(next_new_control_number())
    report_state["dirty"] = False
    update_status()
    SO_number_entry.focus_set()


def load_report_into_form(control_no, source="excel"):
    if not confirm_discard("Open Saved Report", f"Open {control_no}?"):
        return

    # The workbook that holds a report decides where it is read and saved.
    # MySQL has no PO line details, so its copy is not used for these reports.
    po_linked = data_store().owns_withdrawal(control_no)
    try:
        if po_linked:
            data = data_store().read_withdrawal_report(control_no)
        elif source == "mysql":
            try:
                data = db_mysql.load_report(control_no)
            except Exception as error:
                if not mysql_away(error, f"{control_no} is opened from "
                                         "this PC's Excel file"):
                    raise
                try:
                    data = data_store().read_report(control_no)
                except PermissionError:
                    raise
                except Exception:
                    messagebox.showwarning(
                        "Open Saved Report",
                        f"MySQL was not reached, and {control_no} is not "
                        "in this PC's Excel file.\n\nOpen it again when "
                        "MySQL is running.", parent=window)
                    return
        else:
            data = data_store().read_report(control_no)
    except PermissionError:
        messagebox.showerror(
            "File In Use",
            "Cannot read the Excel file. Close it in Excel and try again.",
            parent=window
        )
        return
    except Exception as error:
        log.exception("Open report failed")
        messagebox.showerror(
            "Open Error",
            f"Unable to open the report:\n{error}",
            parent=window
        )
        return

    item_forms_error = None
    try:
        data["other_item_forms"] = data_store().load_item_forms(data["control_no"])
    except ValueError as error:
        log.exception("Item form file could not be read")
        item_forms_error = str(error)

    populate_form(data)
    withdrawal_panel.load(po_linked)

    if item_forms_error:
        messagebox.showwarning(
            "Item List Forms",
            "The lines of the other Item List forms could not be read, so "
            f"they were not loaded:\n{item_forms_error}\n\nSaving this report "
            "will replace that file.",
            parent=window
        )

    extra = len(data["other_important_remarks"]) - OTHER_REMARKS_MAX
    if extra > 0:
        messagebox.showwarning(
            "Other Important Remarks",
            f"This report has {len(data['other_important_remarks'])} Other "
            f"Important Remarks, but the form allows only {OTHER_REMARKS_MAX}.\n\n"
            f"The last {extra} were not loaded and will be removed if you "
            "save this report.",
            parent=window
        )

    if data.get("incident_error"):
        messagebox.showwarning(
            "Incident Report",
            "The saved incident report file could not be read, so no "
            "incident lines were loaded:\n"
            f"{data['incident_error']}\n\nSaving this report will replace "
            "that file.",
            parent=window
        )

    set_control_number(data["control_no"])
    report_state["editing"] = True
    report_state["dirty"] = False
    update_status()
    notify(f"Opened {data['control_no']}", "info")


def read_withdrawal_listing():
    """(list rows, search index) of the Withdrawal workbook. Trouble with it
    is reported and does not hide the reports of the main workbook."""
    try:
        store = data_store()    # ValueError in Demo Mode, as before
        return (busy(store.list_withdrawal_reports),
                busy(store.withdrawal_search_index))
    except Exception as error:
        log.exception("Reading the Withdrawal workbook failed")
        messagebox.showwarning(
            "Withdrawal Workbook",
            f"The PO-linked Withdrawal reports could not be listed:\n{error}",
            parent=window)
        return [], {}


def open_saved_report_dialog(initial_search=""):
    """List the saved reports; double-click one to edit it."""

    use_mysql = db_mysql is not None and db_mysql.is_enabled()

    if Workbook is None and not use_mysql:
        excel_missing_message()
        return

    path = excel_state["path"]
    source_var = tkinter.StringVar(value="mysql" if use_mysql else "excel")
    withdrawal_rows, withdrawal_index = read_withdrawal_listing()
    withdrawal_labels = {row[0] for row in withdrawal_rows}

    def fetch_reports(show_errors=True):
        """The list for the chosen source ([] and a message on trouble)."""
        try:
            if source_var.get() == "mysql":
                return busy(db_mysql.list_reports)
            return sorted([*busy(data_store(path).list_reports), *withdrawal_rows],
                          reverse=True)
        except PermissionError:
            problem = ("Cannot read the Excel file. Close it in Excel and "
                       "try again.")
        except Exception as error:
            if source_var.get() == "mysql" and mysql_away(
                    error, "the list shows the reports in this PC's Excel "
                           "file"):
                source_var.set("excel")
                return fetch_reports(show_errors)
            log.exception("Reading saved reports failed")
            problem = (db_mysql.explain_error(error)
                       if source_var.get() == "mysql" else
                       f"Unable to read the Excel file:\n{error}")
        if show_errors:
            messagebox.showerror("Open Error", problem, parent=window)
        return None

    reports = fetch_reports()
    if reports is None:
        return

    search_index = {}

    def load_index():
        """What each report contains (SO, BL/AWB, PO, DR, Gatepass,
        Description) so the search can look inside the reports."""
        try:
            if source_var.get() == "mysql":
                found = busy(db_mysql.search_index)
            else:
                found = {**busy(data_store(path).search_index), **withdrawal_index}
        except Exception:
            log.exception("Building the search list failed")
            found = {}
        search_index.clear()
        search_index.update(found)

    load_index()

    if not reports and not use_mysql:
        messagebox.showinfo(
            "No Saved Reports",
            f"There are no saved reports yet in:\n{path}",
            parent=window
        )
        return

    dialog = tb.Toplevel(window)
    dialog.title("Open Saved Report")
    dialog.transient(window)

    width, height = 1280, 480
    x = window.winfo_rootx() + max((window.winfo_width() - width) // 2, 0)
    y = window.winfo_rooty() + 60
    dialog.geometry(f"{width}x{height}+{x}+{y}")

    top = tb.Frame(dialog)
    top.pack(fill="x", padx=15, pady=(15, 5))
    tb.Label(top, text="Search:").pack(side="left")
    search_var = tkinter.StringVar()
    search_entry = tb.Entry(top, textvariable=search_var, width=34)
    search_entry.pack(side="left", padx=(10, 8))
    tb.Label(top, text="in").pack(side="left")
    SEARCH_FIELDS = [
        ("All", None), ("SO Number", "so"), ("BL/AWB", "bl"), ("PO", "po"),
        ("DR", "dr"), ("Gatepass", "gatepass"),
        ("Description", "description"),
    ]
    field_var = tkinter.StringVar(value="All")
    field_combo = tb.Combobox(
        top, textvariable=field_var, state="readonly", width=14,
        values=[name for name, _ in SEARCH_FIELDS]
    )
    field_combo.pack(side="left", padx=8)
    field_combo.no_dirty = True

    if use_mysql:
        source_row = tb.Frame(dialog)
        source_row.pack(fill="x", padx=15, pady=(0, 5))
        tb.Label(source_row, text="Open from:").pack(side="left")
        for _text, _value in (("MySQL database", "mysql"),
                              ("Excel file", "excel")):
            tb.Radiobutton(
                source_row, text=_text, value=_value, variable=source_var,
                command=lambda: switch_source()
            ).pack(side="left", padx=10)

    columns = ("control", "so", "date", "consignee", "bl", "po", "dr",
               "gatepass", "description", "saved")
    headings = ("Control #", "SO Number", "Inspection Date", "Consignee",
                "BL/AWB", "PO", "DR", "Gatepass", "Description",
                "Last Saved")
    widths = (115, 120, 105, 170, 110, 110, 90, 90, 220, 130)
    if withdrawal_labels:           # room for the "[Withdrawal]" label
        widths = (200, *widths[1:])

    tree_frame = tb.Frame(dialog)
    tree_frame.pack(fill="both", expand=True, padx=15, pady=5)

    tree = ttk.Treeview(
        tree_frame, columns=columns, show="headings", selectmode="browse"
    )
    for column, heading, col_width in zip(columns, headings, widths):
        tree.heading(column, text=heading)
        tree.column(column, width=col_width, anchor="w")

    tree_scroll = ttk.Scrollbar(
        tree_frame, orient="vertical", command=tree.yview
    )
    tree_hscroll = ttk.Scrollbar(
        tree_frame, orient="horizontal", command=tree.xview
    )
    tree.configure(yscrollcommand=tree_scroll.set,
                   xscrollcommand=tree_hscroll.set)
    tree_hscroll.pack(side="bottom", fill="x")
    tree.pack(side="left", fill="both", expand=True)
    tree_scroll.pack(side="right", fill="y")

    def switch_source():
        found = fetch_reports()
        reports[:] = found or []
        load_index()
        refresh()

    def refresh(*_):
        query = search_var.get().strip().casefold()
        tree.delete(*tree.get_children())

        key = dict(SEARCH_FIELDS)[field_var.get()]
        for row in reports:
            parts = search_index.get(row[0], {})
            label = (f"{row[0]} [Withdrawal]" if row[0] in withdrawal_labels
                     else row[0])
            if key is None:
                text = label + " " + " ".join(row) + " " + " ".join(
                    " ".join(values) for values in parts.values())
            else:
                text = " ".join(parts.get(key, []))
            if query in text.casefold():
                def joined(name):
                    return ", ".join(dict.fromkeys(parts.get(name, [])))  # noqa: B023 - used in this same pass
                tree.insert("", "end", iid=row[0], values=(
                    label, row[1], row[2], row[3], joined("bl"),
                    joined("po"), joined("dr"), joined("gatepass"),
                    joined("description"), row[4]))

        children = tree.get_children()
        if children:
            tree.selection_set(children[0])
            tree.focus(children[0])

    def load_selected(event=None):
        selection = tree.selection()
        if not selection:
            return

        control_no = selection[0]
        chosen_source = source_var.get()
        dialog.destroy()
        load_report_into_form(control_no, chosen_source)

    buttons = tb.Frame(dialog)
    buttons.pack(fill="x", padx=15, pady=(5, 15))
    tb.Button(
        buttons, text="Open Report", width=14, command=load_selected,
        bootstyle="primary"
    ).pack(side="right")
    tb.Button(
        buttons, text="Cancel", width=10, command=dialog.destroy,
        bootstyle="secondary-outline"
    ).pack(side="right", padx=10)

    search_var.trace_add("write", refresh)
    field_combo.bind("<<ComboboxSelected>>", refresh)

    def on_double_click(event):
        # Ignore double-clicks on the column headers.
        if tree.identify_region(event.x, event.y) == "cell":
            load_selected()

    tree.bind("<Double-1>", on_double_click)
    dialog.bind("<Return>", load_selected)
    dialog.bind("<Escape>", lambda e: dialog.destroy())

    if initial_search:
        search_var.set(initial_search)
    refresh()
    search_entry.focus_set()
    dialog.wait_visibility()
    dialog.grab_set()


def choose_excel_path():
    current = Path(excel_state["path"])
    path = filedialog.asksaveasfilename(
        parent=window,
        title="Select the Excel file (an existing file will be used as is)",
        defaultextension=".xlsx",
        initialdir=str(current.parent),
        initialfile=current.name,
        filetypes=[("Excel Workbook", "*.xlsx")],
        confirmoverwrite=False      # we add to it, we never overwrite it
    )
    return Path(path) if path else None


def change_excel_file():
    """Use another workbook. Control #s belong to the file, so the
    form restarts as a new report with that file's next number."""
    path = choose_excel_path()
    if path is None:
        return
    if path.name.casefold() in (fsr_paths.WITHDRAWAL_WORKBOOK_NAME.casefold(),
                                fsr_paths.PO_MASTER_NAME.casefold(),
                                fsr_paths.WITHDRAWN_ITEM_NAME.casefold()):
        messagebox.showwarning(
            "Change Excel File", f"{path.name} has its own purpose and cannot "
            "be used as the main Excel file.", parent=window)
        return
    if DEMO_MODE and DATA_DIR.resolve() not in path.resolve().parents:
        messagebox.showwarning(
            "Demo Mode", "In Demo Mode the Excel file must stay inside the "
            f"demo folder:\n{DATA_DIR}\n\nClose the program and start it "
            "normally to work with the real data.", parent=window)
        return

    if not confirm_discard(
        "Change Excel File", "Changing the Excel file starts a new report.\n"
        "Continue?"
    ):
        return

    excel_state["path"] = path
    settings["excel_path"] = str(path)
    save_settings()
    new_report(confirm=False)


def open_file(path):
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        log.exception("Could not open %s", path)


def save_report():
    """Add the report to the Excel file, or update it if it is a
    saved report that was opened for editing. Returns True when saved."""

    if Workbook is None:
        excel_missing_message()
        return False

    if not condition_var.get():
        messagebox.showwarning(
            "Cargo Condition",
            "Please select the Cargo Condition (Good Order or Bad Order) "
            "before saving.",
            parent=window
        )
        good_button.focus_set()
        return False

    if not SO_number_entry.get().strip():
        notebook.select(general_tab)
        messagebox.showwarning(
            "Missing SO Number",
            "Please enter the SO Number before saving.",
            parent=window
        )
        SO_number_entry.focus_set()
        return False

    if not validate_format_fields():
        return False

    if condition_var.get() == CONDITION_BAD and not incidents_have_content():
        notebook.select(incident_tab)
        if not messagebox.askyesno(
            "Bad Order - No Incident Lines",
            "Bad Order is selected but the Incident Report has no lines "
            "yet.\n\nSave anyway?",
            parent=window
        ):
            return False

    # Offer to add any typed name that is not in the master lists yet.
    for combo in searchable_combos:
        combo.commit()

    if not withdrawal_panel.context_changed():
        return False

    path = excel_state["path"]
    data = collect_report_data()
    target = path
    backup_note = None
    linked = withdrawal_panel.linked()
    mysql_on = mysql_in_use()
    guard = mysql_guard() if mysql_on else None
    stores = data_store(path).save_steps(
        mysql=db_mysql if mysql_on else None, guard=guard)
    journal = record = None
    earlier_open = []
    if mysql_on and not report_state["editing"]:
        free = free_number_for_new_report(data["control_no"])
        if free != data["control_no"]:
            data["control_no"] = free
            set_control_number(free)

    try:
        if linked:
            target = withdrawal_book()
        # Before the first save of each day the workbook is copied, as it
        # is now, into the Backups folder beside it. A backup that cannot
        # be made never stops the save; the user is told below.
        try:
            fsr_backup.backup_before_save(
                target, fsr_backup.keep_setting(settings))
        except OSError as error:
            log.exception("Daily backup failed")
            backup_note = (
                "Today's backup copy of the Excel file could NOT be made:\n"
                f"{error}\n\nThe report itself was saved. Check the "
                f"{fsr_backup.FOLDER_NAME} folder beside the Excel file.")

        # The save goes on record before its first write, so a save that
        # stops halfway (power cut, file open in Excel, MySQL away) is
        # finished at the next save or the next start (fsr_save_journal).
        try:
            journal = data_store(path).save_record()
            # An earlier save of this same report that did not finish is
            # replaced by this one; what it still owed is done by this save
            # and said in the note below.
            earlier_open = fsr_save_journal.open_local_steps(
                journal, data["control_no"])
            record = fsr_save_journal.open_save(
                journal, stores, data, report_state["editing"], linked,
                mysql_on)
        except (OSError, ValueError, TypeError):
            log.exception("The save record could not be written")
            journal = None
            record = fsr_save_journal.new_record(
                data, report_state["editing"], linked,
                fsr_save_journal.steps_for(data, linked, mysql_on))

        # Excel first, then the incident file, the other Item List forms
        # and PO_Master / Withdrawn_Item. Only a failure of the Excel write
        # stops the save. MySQL follows in the background (its step stays
        # open in the record) - unless there is no record to hold it.
        outcome = busy(fsr_save_journal.run, journal, record, stores,
                       journal is None, journal is None)
        result = outcome["result"]

    except PermissionError:
        fsr_save_journal.discard(journal, record)
        messagebox.showerror(
            "File In Use",
            f"Cannot write to:\n{target}\n\n"
            "Close the file in Excel and click Save again.",
            parent=window
        )
        return False

    except Exception as error:
        log.exception("Save failed")
        fsr_save_journal.discard(journal, record)
        messagebox.showerror(
            "Save Error",
            f"Unable to save the report:\n{error}",
            parent=window
        )
        return False

    failed = outcome["failed"]
    data = record["data"]       # as written: Control #, Receiving Refs ...
    later = ("\n\nIt will also be finished automatically at the next save "
             "or the next start." if journal is not None else "")

    # The report now exists in the file, so further saves update it.
    set_control_number(result["control"])
    report_state["editing"] = True
    report_state["dirty"] = False
    withdrawal_panel.saved(data)
    update_status()

    # remember SO Number + Consignee for the next report / next start
    settings["last_so_number"] = SO_number_entry.get().strip()
    settings["last_consignee"] = consignee_combobox.get().strip()
    save_settings()

    action = "updated" if result["updated"] else "saved"
    data["control_no"] = result["control"]

    # Incident reports go to their own JSON file (not into the Excel file).
    incident_note = None
    if "incidents" in failed:
        incident_note = (
            "The incident report file could not be saved:\n"
            f"{failed['incidents']}\n\nClick Save again to retry." + later
        )

    if "item_forms" in failed:
        incident_note = "\n\n".join(t for t in (incident_note, (
            "The lines of the other Item List forms could not be saved:\n"
            f"{failed['item_forms']}\n\nClick Save again to retry."
            + later)) if t)

    # PO_Master and Withdrawn_Item follow the saved reports, in the
    # background (at once in the automated tests, which then say it here).
    if journal is not None and "item_lists" in record["steps"]:
        lists_feedback.pop(record["id"], None)
        request_lists_round(save_id=record["id"], compose=lists_sender.inline)
        if record["id"] in lists_feedback:
            lists_error = lists_feedback.pop(record["id"])
            if lists_error is not None:
                failed["item_lists"] = lists_error
        elif "item_lists" in earlier_open:
            earlier_open.remove("item_lists")   # said by the rebuild
    elif journal is not None:
        request_lists_round()       # earlier saves may still wait for them
    if "item_lists" in failed:
        if isinstance(failed["item_lists"], PermissionError):
            incident_note = "\n\n".join(t for t in (incident_note, (
                "PO_Master or Withdrawn_Item could not be updated because it "
                "is open in another program.\nClose it and click Save again."
                + later)) if t)
        else:
            incident_note = "\n\n".join(t for t in (incident_note, (
                "PO_Master and Withdrawn_Item could not be updated:\n"
                f"{failed['item_lists']}" + later)) if t)

    completed_now = [step for step in earlier_open if step not in failed]
    if completed_now:
        incident_note = "\n\n".join(t for t in ((
            "Unfinished Save: an earlier save of this report had not "
            "finished. It was completed now: "
            f"{fsr_save_journal.words(completed_now)}."), incident_note)
            if t)

    # Also store the report in MySQL (when db_config.json is set up): in
    # the background, so the window does not wait for the server.
    db_note = None
    mysql_waits = False
    mysql_conflict = None
    sending = False
    if mysql_on and journal is not None:
        mysql_feedback.pop(record["id"], None)
        request_mysql_round(save_id=record["id"],
                            compose=mysql_sender.inline)
        told = mysql_feedback.pop(record["id"], None)
        sending = not mysql_sender.inline
        kind, detail = told or (None, None)
        if kind == "sent":
            db_note = "\n".join(detail or []) or None
        elif kind == "conflict":
            mysql_waits = True
            mysql_conflict = detail
            db_note = (
                "The report is saved in the Excel file, but MySQL was NOT "
                f"updated:\n{detail['text']}\n\nNothing in MySQL was "
                "changed. Decide in the MySQL Conflicts window what to do; "
                "until then MySQL keeps its report.")
        elif kind == "away":
            mysql_waits = True
        elif kind == "error":
            mysql_waits = True
            db_note = (
                "The report was saved to Excel, but NOT to MySQL:\n"
                f"{db_mysql.explain_error(detail)}\n\nClick Save again "
                "to retry, or use 'Sync to MySQL'." + later)
    elif mysql_on:
        # No save record (it could not be written): MySQL was done at once.
        error = failed.get("mysql")
        if error is None:
            try:
                busy(db_mysql.save_master_lists, master_data)
            except Exception as lists_error:
                log.exception("MySQL master lists failed")
                error = lists_error
        conflict = isinstance(error, fsr_mysql_guard.MySQLConflict)
        if error is None:
            db_note = "\n".join(outcome.get("mysql_notes") or []) or None
            if "set_mysql_dots" in globals():
                set_mysql_dots("ok")
            if result["control"] not in mysql_numbers["values"]:
                mysql_numbers["values"].append(result["control"])
        elif conflict:
            # MySQL answered, but holds ANOTHER report under this number.
            # Nothing was written there. The report is safe in the Excel
            # file; the decision waits in MySQL Conflicts.
            mysql_waits = True
            mysql_conflict = error.conflict
            db_note = (
                "The report is saved in the Excel file, but MySQL was NOT "
                f"updated:\n{error}\n\nNothing in MySQL was changed. "
                "Decide in the MySQL Conflicts window what to do; until "
                "then MySQL keeps its report.")
        else:
            mysql_waits = "mysql" in failed
            if "set_mysql_dots" in globals():
                set_mysql_dots("bad", db_mysql.explain_error(error))
            # A server that cannot be reached is normal on an offline PC:
            # no message box, the notice below says that MySQL comes later.
            if not (mysql_waits and journal is not None
                    and getattr(db_mysql, "is_unreachable",
                                lambda e: False)(error)):
                db_note = (
                    "The report was saved to Excel, but NOT to MySQL:\n"
                    f"{db_mysql.explain_error(error)}\n\nClick Save again "
                    "to retry, or use 'Sync to MySQL'." + (
                        later if mysql_waits else ""))

    # Also record the report on the official form (First Page + Cargo Details).
    warning, summary = None, ""
    try:
        forms, notes, summary = busy(create_report_forms, path, data)
        warning = "\n".join(notes) or None
    except PermissionError:
        warning = (
            "The report form could not be updated because it is open in "
            "another program.\nClose it, then use the Print / PDF... button."
        )
    except Exception as error:
        log.exception("Report form failed")
        warning = f"The report form could not be created:\n{error}"

    if mysql_conflict:
        notify(
            f"Report {result['control']} {action} on this PC  -  NOT sent "
            "to MySQL (it holds a different report under this number)",
            bootstyle="warning")
    elif sending:
        notify(
            f"Report {result['control']} {action} on this PC  -  "
            f"{result['goods']} goods, {result['items']} item lines, "
            f"{result['remarks']} remarks. Sending it to MySQL...")
    elif mysql_waits:
        notify(
            f"Report {result['control']} {action} on this PC  -  MySQL was "
            "not reached; it will be sent at the next save or start",
            bootstyle="warning")
    else:
        notify(
            f"Report {result['control']} {action}  -  "
            f"{result['goods']} goods, {result['items']} item lines, "
            f"{result['remarks']} remarks"
        )

    warning = "\n\n".join(
        t for t in (backup_note, incident_note, db_note, warning) if t
    ) or None
    if warning:
        messagebox.showwarning("Report Saved - Note", warning, parent=window)

    show_saved_links(data)
    if globals().get("app_shell") is not None:
        app_shell.service.invalidate()      # dashboards use the new data
    # Earlier saves that did not finish are completed now (this PC's
    # files; MySQL is in the round above).
    finish_unfinished_saves(skip={record["id"]})
    if mysql_conflict:
        open_mysql_conflicts(select=record["id"])
    refresh_conflict_count()
    refresh_mysql_waiting()
    return True


def finish_unfinished_saves(mysql_ok=False, skip=(), numbers=False,
                            adopt=False):
    """Complete every save on record that stopped halfway and tell the user
    in plain words what was done. Runs at start, after a save, and when
    MySQL becomes reachable. Safe to run any number of times. This PC's
    files are done here; with mysql_ok the reports waiting for MySQL are
    handed to the background sender."""
    path = excel_state["path"]
    if mysql_ok:
        def ask_mysql():
            request_mysql_round(catch_up=True, with_conflicts=True,
                                numbers=numbers, adopt=adopt)
    else:
        def ask_mysql():
            pass
    try:
        journal = data_store(path).save_record()
        if not [r for r in journal.pending() if r.get("id") not in skip]:
            ask_mysql()
            return []
        use_guard = mysql_in_use()
        guard = mysql_guard() if use_guard else None
        stores = data_store(path).save_steps(
            mysql=db_mysql if use_guard else None, guard=guard)
        report = busy(fsr_save_journal.repair, journal, stores, False,
                      skip, False)
        request_lists_round()       # PO_Master / Withdrawn_Item, if waiting
    except fsr_save_journal.JournalError as error:
        log.exception("The record of unfinished saves cannot be read")
        if not unfinished_state["unreadable_shown"]:
            unfinished_state["unreadable_shown"] = True
            messagebox.showwarning(
                "Unfinished Save",
                f"{error}\n\nThe file was left as it is. Saving works as "
                "usual, but a save that stops halfway cannot be finished "
                "automatically until this file is moved away.",
                parent=window)
        return []
    except Exception:
        log.exception("Finishing unfinished saves failed")
        return []

    lines, attention = fsr_save_journal.describe(report)
    if lines:
        log.info("Unfinished saves: %s", " | ".join(lines))
    if attention:
        still_open = any(
            step != "mysql" for entry in report for step in entry["failed"])
        (messagebox.showwarning if still_open else messagebox.showinfo)(
            "Unfinished Save", "\n\n".join(lines), parent=window)
    if report and globals().get("app_shell") is not None:
        app_shell.service.invalidate()
    ask_mysql()
    refresh_conflict_count()
    return report


def waiting_conflicts():
    try:
        return fsr_save_journal.conflicts(
            data_store().save_record())
    except Exception:
        return []


def refresh_conflict_count():
    """Show how many reports wait for a decision (account menu)."""
    if "rebuild_account_menu" in globals():
        try:
            rebuild_account_menu()
        except tkinter.TclError:
            pass


def adopt_existing_reports():
    """First run with existing data: reports that MySQL holds with the same
    value become this copy's own - no question, nothing written to MySQL.
    Only done while this copy's ledger is still empty."""
    if not mysql_in_use() or not fsr_mysql_guard.supports(db_mysql):
        return []
    try:
        # adopt_identical() stores the ledger itself; nothing was written to
        # the workbook, so the ledger must NOT be marked current here.
        adopted = busy(adopt_reports, excel_state["path"], mysql_guard(),
                       None, DATA_DIR if DEMO_MODE else None)
    except Exception:
        log.exception("Could not compare the reports with MySQL")
        return []
    if adopted:
        log.info("%d report(s) are the same in the Excel file and in MySQL "
                 "and are now this copy's own.", len(adopted))
    return adopted


def conflict_text(record):
    conflict = record["conflict"]
    mine, theirs = conflict["mine"], conflict["theirs"]

    def card(title, side):
        return (f"{title}\n"
                f"   SO Number:        {side['so_number']}\n"
                f"   Inspection Date:  {side['inspection_date']}\n"
                f"   Consignee:        {side['consignee']}\n"
                f"   Supplier:         {side['supplier']}\n"
                f"   Cargo Condition:  {side['condition']}\n"
                f"   Item lines:       {side['item_lines']}")

    lines = [conflict["text"], "",
             card("IN THIS PC'S EXCEL FILE (mine)", mine), "",
             card("IN MYSQL (kept unless you replace it)", theirs), "",
             "What differs:"]
    lines += ["   " + line for line in conflict["differences"]] or [
        "   (nothing in the fields that are compared)"]
    return "\n".join(lines)


def open_mysql_conflicts(select=None):
    """The reports that were NOT sent to MySQL because it holds a different
    report under their number. Closing the window, or the default button,
    writes nothing to MySQL."""
    old = conflict_state["dialog"]
    if old is not None:
        try:
            old.destroy()
        except tkinter.TclError:
            pass
    dialog = tb.Toplevel(window)
    conflict_state["dialog"] = dialog
    dialog.title("MySQL Conflicts")
    dialog.transient(window)
    body = tb.Frame(dialog, padding=16)
    body.pack(fill="both", expand=True)
    tb.Label(
        body, wraplength=760, justify="left", bootstyle="secondary",
        text="These reports are saved in this PC's Excel file but were NOT "
             "sent to MySQL, because MySQL holds a different report under "
             "the same Control #. MySQL keeps its report until you decide "
             "otherwise. Closing this window changes nothing."
    ).pack(anchor="w")

    middle = tb.Frame(body)
    middle.pack(fill="both", expand=True, pady=(10, 8))
    listing = tkinter.Listbox(middle, width=26, height=14,
                              exportselection=False)
    listing.pack(side="left", fill="y")
    details = tkinter.Text(middle, width=74, height=22, wrap="word",
                           font=("Consolas", 9))
    details.pack(side="left", fill="both", expand=True, padx=(10, 0))
    state = {"records": []}

    def chosen():
        picked = listing.curselection()
        return state["records"][picked[0]] if picked else None

    def show(event=None):
        record = chosen()
        details.configure(state="normal")
        details.delete("1.0", "end")
        details.insert("1.0", conflict_text(record) if record else
                       "No report is waiting for a decision.")
        details.configure(state="disabled")
        renumber_button.configure(state="normal" if record and record[
            "conflict"]["kind"] == fsr_mysql_guard.NOT_OWNED else "disabled")
        for button in (keep_button, replace_button):
            button.configure(state="normal" if record else "disabled")

    def reload(pick=None):
        state["records"] = waiting_conflicts()
        listing.delete(0, "end")
        for record in state["records"]:
            listing.insert("end", record["control"])
        index = next((i for i, r in enumerate(state["records"])
                      if r["id"] == pick), 0)
        if state["records"]:
            listing.selection_set(index)
        show()
        refresh_conflict_count()

    def stores_and_journal():
        guard = mysql_guard()
        stores = data_store().save_steps(mysql=db_mysql, guard=guard)
        return data_store().save_record(), stores, guard

    def problem(outcome):
        error = outcome["failed"].get("mysql")
        if error is None:
            return False
        if mysql_away(error, "nothing was changed; decide again when it "
                             "is back"):
            return True
        messagebox.showwarning(
            "MySQL Conflicts",
            "MySQL was NOT changed:\n" + (
                str(error) if isinstance(
                    error, (fsr_mysql_guard.MySQLConflict,
                            fsr_mysql_guard.MySQLBusy))
                else db_mysql.explain_error(error)), parent=dialog)
        return True

    def keep():
        record = chosen()
        if record is None:
            return
        fsr_save_journal.resolve_keep(
            data_store().save_record(), record["id"])
        log.info("MySQL conflict for %s closed: MySQL's report kept.",
                 record["control"])
        notify(f"{record['control']}: MySQL keeps its report. Nothing was "
               "written.")
        reload()

    def replace():
        record = chosen()
        if record is None:
            return
        if not messagebox.askyesno(
                "Replace the report in MySQL?",
                f"REPLACE the report {record['control']} that is in MySQL "
                "with the one from this PC's Excel file?\n\n"
                "The report that is in MySQL now is kept first as a file in "
                "the 'MySQL Replaced' folder, so it can be put back.",
                default="no", icon="warning", parent=dialog):
            return
        journal, stores, guard = stores_and_journal()
        try:
            outcome = busy(fsr_save_journal.resolve_replace, journal, stores,
                           record["id"])
        except Exception as error:
            log.exception("Replacing %s in MySQL failed", record["control"])
            if not mysql_away(error, "nothing was changed; decide again "
                                     "when it is back"):
                messagebox.showerror("MySQL Conflicts", f"MySQL was NOT "
                                     f"changed:\n{error}", parent=dialog)
            reload(record["id"])
            return
        if not problem(outcome):
            notify(f"{record['control']}: replaced in MySQL. The replaced "
                   f"version is kept in {guard.replaced_dir.name}.")
        reload(record["id"])

    def renumber():
        record = chosen()
        if record is None:
            return
        path = excel_state["path"]
        old = record["control"]
        try:
            taken = list(db_mysql.control_numbers())
            new = data_store(path).next_free_number(old, taken)
        except Exception as error:
            if not mysql_away(error, "nothing was changed; decide again "
                                     "when it is back"):
                messagebox.showerror(
                    "MySQL Conflicts", "The next free number could not be "
                    f"worked out:\n{db_mysql.explain_error(error)}",
                    parent=dialog)
            return
        if not messagebox.askyesno(
                "Save mine under the next free number?",
                f"Give YOUR report the number {new} instead of {old}?\n\n"
                "It is renumbered in the Excel file, its incident and item "
                "form files, PO_Master and Withdrawn_Item, and then sent to "
                "MySQL under the new number. The report MySQL holds as "
                f"{old} is not touched.\n\nForms already printed keep the "
                "old number; print the report again.",
                default="no", parent=dialog):
            return
        journal, stores, guard = stores_and_journal()

        def change(old_number, new_number):
            with guard.local_write():
                data_store(path).renumber(old_number, new_number)

        try:
            outcome = busy(fsr_save_journal.resolve_renumber, journal,
                           stores, record["id"], new, change)
        except PermissionError:
            messagebox.showerror(
                "File In Use", "A workbook is open in Excel. Close it and "
                "try again. Nothing was renumbered in MySQL.", parent=dialog)
            reload(record["id"])
            return
        except Exception as error:
            log.exception("Renumbering %s failed", old)
            messagebox.showerror("MySQL Conflicts", f"The report could not "
                                 f"be renumbered:\n{error}", parent=dialog)
            reload(record["id"])
            return
        if same_key(control_entry.get(), old):     # it is open on the form
            set_control_number(new)
            report_state["dirty"] = False
            update_status()
        if globals().get("app_shell") is not None:
            app_shell.service.invalidate()
        if not problem(outcome):
            notify(f"{old} is now {new} on this PC and in MySQL.")
        reload()

    def put_back():
        guard = mysql_guard()
        chosen_file = filedialog.askopenfilename(
            parent=dialog, title="Choose the replaced report to put back",
            initialdir=str(guard.replaced_dir)
            if guard.replaced_dir.exists() else None,
            filetypes=[("Replaced report", "*.json")])
        if not chosen_file:
            return
        if not messagebox.askyesno(
                "Put back a replaced report?",
                "Write this kept report into MySQL again?\n\nWhat MySQL "
                "holds under its number now is kept first, in the same "
                "folder.", default="no", parent=dialog):
            return
        try:
            control = busy(guard.put_back, chosen_file)
        except Exception as error:
            log.exception("Putting back %s failed", chosen_file)
            messagebox.showerror("MySQL Conflicts", f"MySQL was NOT "
                                 f"changed:\n{error}", parent=dialog)
            return
        notify(f"{control}: the kept version is in MySQL again.")

    buttons = tb.Frame(body)
    buttons.pack(fill="x")
    keep_button = tb.Button(
        buttons, text="Keep MySQL's (write nothing)", bootstyle="info",
        command=keep)
    keep_button.pack(side="left")
    replace_button = tb.Button(
        buttons, text="Replace MySQL's with mine...",
        bootstyle="danger-outline", command=replace)
    replace_button.pack(side="left", padx=8)
    renumber_button = tb.Button(
        buttons, text="Save mine under the next free number...",
        bootstyle="secondary-outline", command=renumber)
    renumber_button.pack(side="left")
    tb.Button(buttons, text="Close", bootstyle="secondary",
              command=dialog.destroy).pack(side="right")
    tb.Button(buttons, text="Put back a replaced report...",
              bootstyle="link", command=put_back).pack(side="right", padx=8)

    listing.bind("<<ListboxSelect>>", show)
    dialog.bind("<Return>", lambda e: keep())       # the safe choice
    dialog.bind("<Escape>", lambda e: dialog.destroy())
    reload(select)
    keep_button.focus_set()
    return dialog


def show_saved_links(data):
    """Put the Receiving Refs given at save time into the form (the
    saved rows are the filled rows of each Item List, in order)."""
    was_dirty = report_state["dirty"]
    for section, saved in zip(item_frames, data["item_lists"]):
        filled_rows = [w for w in section.rows if section.line_values(w)]
        for widgets, row in zip(filled_rows, saved["rows"]):
            ref = str(row.get("Receiving Ref") or "")
            if ref and not widgets.hidden.get("Receiving Ref"):
                widgets.hidden["Receiving Ref"] = ref
    report_state["dirty"] = was_dirty


def export_master_data():
    """Write one Master Data JSON file with everything, to send to the owner."""
    if Workbook is None:
        excel_missing_message()
        return

    device = socket.gethostname()
    chosen = filedialog.asksaveasfilename(
        parent=window,
        title="Save the Master Data file for the owner",
        defaultextension=".json",
        initialfile=(f"FSR_Master_Data_{safe_filename(device)}_"
                     f"{date.today():%Y-%m-%d}.json"),
        filetypes=[("Master data file", "*.json")]
    )
    if not chosen:
        return

    try:
        count = busy(fsr_master_export.write_export, excel_state["path"],
                     chosen, device, USER_FULL_NAME, master_data)
    except Exception as error:
        log.exception("Export Master Data failed")
        messagebox.showerror("Export Master Data",
                             f"The file was not written:\n{error}", parent=window)
        return
    messagebox.showinfo(
        "Export Master Data",
        f"{count} report(s) saved to:\n{chosen}\n\nSend this one file to the "
        "owner. Sending it again later is fine: reports the owner already "
        "has are not duplicated.",
        parent=window
    )


def import_master_data_file():
    """Bring in a Master Data file sent from a site PC or the Android app."""
    if Workbook is None:
        excel_missing_message()
        return

    chosen = filedialog.askopenfilename(
        parent=window,
        title="Select the Master Data file (from a site PC or a phone)",
        filetypes=[("Master data file", "*.json"), ("All files", "*.*")]
    )
    if not chosen:
        return

    path = excel_state["path"]
    try:
        data = fsr_import.read_master_file(chosen)
    except fsr_import.MasterDataError as error:
        messagebox.showerror("Import Master Data", str(error), parent=window)
        return

    who = data.get("inspector") or "an unnamed inspector"
    if not messagebox.askyesno(
        "Import Master Data",
        f"{len(data['reports'])} report(s) from {who}.\n\n"
        f"Bring them into:\n{path}\n\n"
        "A copy of the Excel file is made first. Your existing reports are "
        "not overwritten.",
        parent=window
    ):
        return

    # One workbook write for the whole file, on record first (all or
    # nothing); a progress window while it runs. MySQL follows in the
    # background, every report through the overwrite guard.
    mysql_now = mysql_in_use()
    guard = mysql_guard() if mysql_now else None
    stores = data_store(path).save_steps(
        mysql=db_mysql if mysql_now else None, guard=guard)
    journal = data_store(path).save_record()
    import_state["running"] = True

    def work(progress):
        return data_store(path).import_master_data(
            data, journal=journal, stores=stores, mysql=mysql_now,
            progress=progress)

    def done(summary, error):
        import_state["running"] = False
        if error is not None:
            import_stopped(path, error)
            return
        import_finished(path, data, summary, mysql_now)

    run_with_progress(window, "Importing the Master Data file...", work,
                      done, with_progress=True)


def import_stopped(path, error):
    """The import raised. The workbook is written in one go, so it holds
    either all of the file's reports or none; the save record finishes or
    drops the rest (and says which)."""
    if isinstance(error, fsr_import.MasterDataError):
        messagebox.showerror("Import Master Data", str(error), parent=window)
    elif isinstance(error, PermissionError):
        messagebox.showerror(
            "File In Use",
            f"Cannot write to:\n{path}\n\nNothing was imported. Close the "
            "file in Excel and import again.", parent=window)
    else:
        messagebox.showerror(
            "Import Master Data",
            f"The import stopped:\n{error}\n\nIt is safe to import the "
            "file again: reports already brought in are not duplicated.",
            parent=window)
    finish_unfinished_saves()


def import_finished(path, data, summary, mysql_now):
    new_names = fsr_import.new_master_names(data, master_data)
    total_names = sum(len(names) for names in new_names.values())
    if total_names:
        listing = "\n".join(
            name for names in new_names.values() for name in names[:20])
        if messagebox.askyesno(
            "Import Master Data",
            f"Add {total_names} new name(s) from the file to your master "
            f"lists?\n\n{listing}",
            parent=window
        ):
            fsr_import.add_master_names(new_names, master_data)
            save_master_lists()

    lines = [
        f"Added: {len(summary['added'])}",
        f"Updated: {len(summary['updated'])}",
        f"Already up to date: {len(summary['unchanged'])}",
    ]
    if summary["renumbered"]:
        lines.append("\nGiven a new number, because the phone's number is "
                     "already used here:")
        lines += [f"  {old}  ->  {new}" for old, new in summary["renumbered"]]
    if summary["conflicts"]:
        lines.append("\nNOT updated, because they were also edited on this "
                     "PC: " + ", ".join(summary["conflicts"]))
    if summary["deleted_here"]:
        lines.append("\nNOT brought back, because they were deleted on this "
                     "PC: " + ", ".join(summary["deleted_here"]))
    if summary.get("item_lists_failed") is not None:
        lines.append("\nPO_Master and Withdrawn_Item could not be updated "
                     "(is one of them open in Excel?). They are updated at "
                     "the next save or start.")
    if mysql_now and summary["saved_reports"]:
        lines.append("\nThey are being sent to MySQL in the background; a "
                     "report MySQL holds differently is not overwritten (see "
                     "Account > MySQL Conflicts).")
    if summary["backup"]:
        lines.append(f"\nCopy of the Excel file before the import:\n"
                     f"{summary['backup']}")
    open_control = control_entry.get().strip()
    if report_state["editing"] and any(
            same_key(open_control, control)
            for control in summary["updated"]):
        lines.append(f"\nReport {open_control} is open on the form with its "
                     "old values. Open it again before saving.")
    messagebox.showinfo("Import Master Data", "\n".join(lines), parent=window)
    refresh_conflict_count()
    if mysql_now and summary["saved_reports"]:
        request_mysql_round()

    if globals().get("app_shell") is not None:
        app_shell.service.invalidate()      # dashboards use the new data


def sync_all_to_mysql():
    """Send the reports of the Excel file to MySQL - after showing what
    would change. New reports and this copy's own unchanged ones are sent;
    a report MySQL holds differently is only replaced when it is ticked.
    Nothing is ever deleted."""
    if not mysql_in_use():
        messagebox.showinfo(
            "MySQL",
            "MySQL is not set up.\n\nOpen the account menu (top right) > "
            "MySQL Settings and fill in the connection.",
            parent=window
        )
        return

    path = excel_state["path"]
    if not data_store(path).list_reports() and not data_store(path).withdrawal_numbers():
        messagebox.showinfo(
            "Sync to MySQL",
            f"There are no saved reports in:\n{path}\n\nNothing was sent "
            "and nothing in MySQL was changed.", parent=window)
        return

    guard = mysql_guard()

    def read_and_plan():
        reports = []
        for entry in data_store(path).list_reports():
            reports.append(data_store(path).read_report(entry[0]))
        linked = data_store().read_all_withdrawal_reports()
        return reports + linked, [r["control_no"] for r in linked], \
            guard.plan(reports + linked)

    try:
        reports, linked, plan = busy(read_and_plan)
    except Exception as error:
        log.exception("MySQL sync preview failed")
        if not mysql_away(error, "nothing was sent; use Sync to MySQL "
                                 "again when it is back"):
            messagebox.showerror(
                "MySQL Error",
                f"Nothing was sent:\n{db_mysql.explain_error(error)}",
                parent=window)
        return

    def send(replace):
        try:
            result = busy(fsr_save_journal.send_to_mysql,
                          data_store(path).save_record(), guard, reports,
                          replace, linked)
            db_mysql.save_master_lists(master_data)
        except Exception as error:
            log.exception("MySQL sync failed")
            if not mysql_away(error, "the sync stopped; use Sync to MySQL "
                                     "again when it is back"):
                messagebox.showerror(
                    "MySQL Error",
                    f"Sync stopped:\n{db_mysql.explain_error(error)}",
                    parent=window)
            return
        lines = [f"Sent to MySQL: {len(result['written'])}",
                 f"Already the same in MySQL: {len(result['identical'])}"]
        if result["conflicts"]:
            lines.append(
                f"NOT sent (MySQL holds a different report): "
                f"{len(result['conflicts'])} - see Account > MySQL "
                "Conflicts.")
        if result["errors"]:
            lines.append("\nProblems:\n" + "\n".join(
                f"{control}: {text}"
                for control, text in result["errors"][:10]))
        (messagebox.showwarning if result["errors"] or result["conflicts"]
         else messagebox.showinfo)("Sync to MySQL", "\n".join(lines),
                                   parent=window)
        refresh_conflict_count()

    counts = (f"New in MySQL: {len(plan['new'])}\n"
              f"Yours, to be updated: {len(plan['update'])}\n"
              f"Already the same: {len(plan['identical'])}\n"
              f"Different in MySQL: {len(plan['conflicts'])}")
    if not plan["conflicts"]:
        if not plan["new"] and not plan["update"]:
            messagebox.showinfo(
                "Sync to MySQL", counts + "\n\nMySQL already holds every "
                "report of this Excel file. Nothing to send.", parent=window)
            return
        if messagebox.askyesno(
                "Sync to MySQL", counts + "\n\nSend the new and updated "
                "reports to MySQL? Nothing is deleted.", parent=window):
            send(())
        return

    # Some reports are different in MySQL: show them, unticked.
    dialog = tb.Toplevel(window)
    dialog.title("Sync to MySQL")
    dialog.transient(window)
    body = tb.Frame(dialog, padding=18)
    body.pack(fill="both", expand=True)
    tb.Label(body, text=counts, justify="left").pack(anchor="w")
    tb.Label(
        body, wraplength=560, justify="left", bootstyle="danger",
        text="\nThese reports are DIFFERENT in MySQL. They are NOT sent "
             "unless you tick them. A ticked report replaces the one in "
             "MySQL (which is kept first in the 'MySQL Replaced' folder)."
    ).pack(anchor="w")
    ticks = {}
    box = tb.Frame(body)
    box.pack(fill="x", pady=(6, 10))
    for report, conflict in plan["conflicts"]:
        var = tkinter.BooleanVar(value=False)
        ticks[report["control_no"]] = var
        what = "; ".join(conflict["differences"][:2]) or "other details"
        tb.Checkbutton(
            box, variable=var,
            text=f"{report['control_no']}  -  {what}"[:110]
        ).pack(anchor="w")

    def go():
        replace = [control for control, var in ticks.items() if var.get()]
        if replace and not messagebox.askyesno(
                "Replace reports in MySQL?",
                f"REPLACE {len(replace)} report(s) in MySQL with the ones "
                "from this PC's Excel file?\n\n" + ", ".join(replace),
                default="no", icon="warning", parent=dialog):
            return
        dialog.destroy()
        send(replace)

    row = tb.Frame(body)
    row.pack(fill="x")
    send_button = tb.Button(row, text="Send (ticked ones are replaced)",
                            bootstyle="info", command=go)
    send_button.pack(side="right")
    tb.Button(row, text="Cancel", bootstyle="secondary-outline",
              command=dialog.destroy).pack(side="right", padx=8)
    dialog.bind("<Escape>", lambda e: dialog.destroy())
    return dialog


def restore_excel_from_mysql():
    """Rebuild the Excel data file from MySQL: every report that is in
    MySQL but missing from the Excel file is added (nothing is overwritten)."""
    if db_mysql is None or not db_mysql.is_enabled():
        messagebox.showinfo("MySQL", "MySQL is not set up.", parent=window)
        return
    if Workbook is None:
        excel_missing_message()
        return

    path = Path(excel_state["path"])
    if not messagebox.askyesno(
        "Restore Excel from MySQL",
        f"Add the reports that are in MySQL but missing from:\n{path}\n\n"
        "Reports already in the Excel file are not changed.",
        parent=window
    ):
        return

    def work():
        # A PO-linked report has its home in the Withdrawal workbook.
        have = {str(row[0]).strip().casefold()
                for row in data_store(path).list_reports()}
        have.update(str(number).strip().casefold()
                    for number in data_store(path).withdrawal_numbers())
        added, errors = 0, []
        for entry in db_mysql.list_reports():
            control = entry[0]
            if str(control).strip().casefold() in have:
                continue
            try:
                data = db_mysql.load_report(control)
                data_store(path).write_report(data, True)
                if data["cargo_condition"] == CONDITION_BAD:
                    data_store(path).save_incidents(
                        control, data["general_information"]["so_number"],
                        data["incident_reports"])
                added += 1
                restored.append(control)
            except PermissionError:
                raise
            except Exception as error:
                log.exception("Restore failed for %s", control)
                errors.append(f"{control}: {error}")
        return added, errors

    restored = []
    try:
        restore_guard = mysql_guard()
        with restore_guard.local_write():
            added, errors = busy(work)
        # What was just brought in is the same here and in MySQL: it is
        # this copy's own from now on, so editing it needs no question.
        try:
            busy(restore_guard.adopt_identical,
                 [data_store(path).read_report(control) for control in restored])
        except Exception:
            log.exception("Could not adopt the restored reports")
    except PermissionError:
        messagebox.showerror(
            "File In Use",
            "Cannot write to the Excel file. Close it in Excel and try again.",
            parent=window)
        return
    except Exception as error:
        log.exception("Restore from MySQL failed")
        if not mysql_away(error, "nothing was restored; the Excel file is "
                                 "unchanged"):
            messagebox.showerror(
                "Restore Error", db_mysql.explain_error(error),
                parent=window)
        return

    message = f"{added} report(s) restored from MySQL into the Excel file."
    if errors:
        message += "\n\nProblems:\n" + "\n".join(errors[:10])
        messagebox.showwarning("Restore Excel from MySQL", message,
                               parent=window)
    else:
        messagebox.showinfo("Restore Excel from MySQL", message, parent=window)


def test_mysql_connection():
    check = getattr(db_mysql, "check_connection", None)
    if check is None:
        ok, message, away = (*busy(db_mysql.test_connection), False)
    else:
        ok, message, away = busy(check)
    if away:
        if "set_mysql_dots" in globals():
            set_mysql_dots("bad", message)
        notify("MySQL was not reached  -  is the MySQL80 service running?",
               bootstyle="warning")
        return
    (messagebox.showinfo if ok else messagebox.showerror)(
        "MySQL connection", message, parent=window)


def on_close():
    if report_state["dirty"]:
        answer = messagebox.askyesnocancel(
            "Unsaved Changes",
            "This report has unsaved changes.\n\nSave before closing?",
            parent=window
        )
        if answer is None:
            return
        if answer and not save_report():
            return

    close_when_sent(close_program)


def close_program():
    save_settings()
    window.destroy()


CLOSE_WAIT_SECONDS = 8


def close_when_sent(close, limit=CLOSE_WAIT_SECONDS):
    """Close at once - or, while reports are still being sent to MySQL,
    show a small window that waits up to `limit` seconds for the send and
    offers "Close now". The program keeps running its main loop meanwhile
    (no "Not Responding"). Whatever is not sent stays in the save record
    and goes at the next start. Returns the waiting window, or None."""
    if mysql_sender.idle():
        close()
        return None

    started = time.monotonic()
    state = {"done": False}
    dialog = tb.Toplevel(window)
    dialog.title("Closing")
    dialog.transient(window)
    dialog.resizable(False, False)
    message = tb.Label(dialog, padding=(24, 20, 24, 6), justify="left")
    message.pack(anchor="w")
    tb.Label(dialog, text="The program closes as soon as this is done.",
             padding=(24, 0, 24, 10), bootstyle="secondary").pack(anchor="w")
    bar = tb.Progressbar(dialog, mode="indeterminate", length=340,
                         bootstyle="striped")
    bar.pack(padx=24, pady=(0, 12))
    bar.start(12)

    def finish(by_user=False):
        if state["done"]:
            return
        state["done"] = True
        waiting = not mysql_sender.idle()
        if waiting:
            log.warning("Closed while reports were still being sent to "
                        "MySQL (%s); they are sent at the next start.",
                        "Close now" if by_user else "after waiting")
        try:
            bar.stop()
            dialog.destroy()
        except tkinter.TclError:
            pass
        close()

    tb.Button(dialog, text="Close now; it will be sent at the next start",
              bootstyle="secondary-outline",
              command=lambda: finish(by_user=True)).pack(
        padx=24, pady=(0, 20), fill="x")
    dialog.protocol("WM_DELETE_WINDOW", lambda: finish(by_user=True))

    def show():
        try:
            count = len(fsr_save_journal.waiting_for_mysql(
                data_store().save_record()))
        except Exception:
            count = 0
        message.configure(text=(
            f"Sending {count} report(s) to MySQL..." if count
            else "Finishing the MySQL send..."))

    def poll():
        if state["done"]:
            return
        mysql_sender.poll()
        if mysql_sender.idle() or time.monotonic() - started >= limit:
            finish()
            return
        show()
        window.after(150, poll)

    show()
    center_over_window(dialog, 160)
    window.after(150, poll)
    return dialog


# =====================================================
# KEYBOARD SHORTCUTS + START
# =====================================================

def shortcut(func):
    def handler(event=None):
        func()
        return "break"
    return handler


def show_inspection_then(func):
    """Ctrl+N / Ctrl+O also bring the Inspection Reports module forward."""
    def run():
        if globals().get("app_shell") is not None:
            app_shell.show("inspection")
        func()
    return run

def report_callback_exception(exc_type, exc_value, exc_traceback):
    """Any unexpected error: write it to the log and tell the user where."""
    log.error("Unexpected error", exc_info=(exc_type, exc_value,
                                            exc_traceback))
    try:
        messagebox.showerror(
            "Unexpected Error",
            f"{exc_type.__name__}: {exc_value}\n\nDetails were saved to:\n"
            f"{LOG_FILE}", parent=window)
    # Broad on purpose: this IS the last-resort error handler; the error
    # was logged above, a failing box must not raise a second one.
    except Exception:
        log.debug("Error box not shown", exc_info=True)


# =====================================================
# NAVIGATION + WAREHOUSE MODULES (warehouse_ui/)
# The inspection form above becomes the "Inspection Reports" module.
# =====================================================

def analytics_source():
    wanted = settings.get("analytics_source", "excel")
    if wanted == "mysql" and db_mysql is not None and db_mysql.is_enabled():
        return "mysql"
    return "excel"


def set_analytics_source(source):
    settings["analytics_source"] = source
    save_settings()


def open_report_from_module(control_no):
    app_shell.show("inspection")
    load_report_into_form(control_no, analytics_source())


def set_module_title(text, inspection=False):
    module_title.configure(text=text)
    if inspection:
        status_badge.pack(side="left", padx=16, after=module_title)
    else:
        status_badge.pack_forget()


def reports_folder():
    folder = Path(excel_state["path"]).parent / "Warehouse Reports"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = Path(excel_state["path"]).parent
    return folder


def after_sample_change(path):
    """Demo Mode: the sample data was written / removed."""
    if Path(path) == Path(excel_state["path"]) and not report_state["dirty"]:
        new_report(confirm=False)


def tell_owner_about_requests():
    waiting = user_store.pending_count()
    if IS_OWNER and waiting:
        messagebox.showinfo(
            "Sign Up Requests",
            f"{waiting} sign up request(s) are waiting for your approval.\n\n"
            "Open the account menu (top right) > Manage Users.",
            parent=window)

# =====================================================
# BUILDING THE WINDOW (Phase 4: not when the module is imported)
# =====================================================

def build_window():
    """Everything the program sets up and shows: the data folders,
    the settings, the sign-in, the window and its widgets - in the
    order it always ran. Every name it makes is a module name, as
    before. Importing this module builds nothing (the functions
    and classes can be used and tested without a window)."""
    global BASE_DIR, CONFIG_DIR, COUNTRY_LIST_KEY, DATA_DIR, DATA_ROOT
    global DEFAULT_EXCEL_NAME, DEMO_MODE, DESTINATION_LIST_KEY
    global DOCUMENT_COLUMNS, DOT_BAD, DOT_OK, DOT_WAIT, EXCEL_ROOT
    global FIELD_CLASSES, FIELD_COLUMNS, FROZEN, IGNORED_KEYS
    global INCIDENT_TAB_TEXT, IS_OWNER, IS_OWNER_EDITION, ITEM_FORM_COLUMNS
    global ITEM_FORM_HEADERS, ITEM_FORM_HINTS, ITEM_HEADER_TIPS, ITEM_WIDTHS
    global JSON_DIR, JSON_ROOT, LOCATION_LIST_KEY, LOGO_ICO, LOGO_PNG
    global LOG_FILE, LOW_LINES_WARNING, MASTER_LIST_FILE, MAX_ROWS
    global MONTH_LIST, MYSQL_ALLOWED, NAV_KEYS, NAV_WIDTH, NIGHT_COLORS
    global NIGHT_THEME, OTHER_REMARKS_MAX, PANEL_WIDTH, PRIVATE_JSON_DIR
    global ROLE_LABEL, SAVED_LINE_HEADERS, SETTINGS_FILE, SO_number_entry
    global SimpleNamespace, TEST_COPY, THEME_DARK, THEME_LIGHT, UI_VERSION
    global UNIT_FORM_HEADERS, UNIT_FORM_LABELS, UNIT_FORM_WIDTHS, USERS_FILE
    global USER_FULL_NAME, WEEKLY_COLUMNS, WEEKLY_CURRENCY, WEEKLY_ITEM_KEYS
    global WEEKLY_NUMBER_COLUMNS, WEEKLY_QTY, WEEKLY_UOM, _button, _col
    global _combo, _default_files, _documents, _event, _folder, _form, _func
    global _handler, _heading, _home, _hsb, _index, _key, _label, _source
    global _tab, _target, _text, _today, _value, _vsb, _week, _width
    global account_menu, account_menu_button, add_more_button, app_shell
    global bad_button, body, bold_font, brokerage_combobox
    global change_file_button, check_mysql_status, condition_row
    global condition_var, conflict_state, consignee_combobox, control_entry
    global country_combobox, ctypes, current_user, date_sync
    global declared_goods_frame, declared_goods_rows, default_font
    global description_entry, destination_combobox, document_entries
    global documents_body, documents_tab, documents_used_frame, dot_items
    global dots_canvas, entry, error, excel_state, export_master_button
    global export_weekly_button, file_label, findings_entries
    global findings_frame, findings_tab, form_row, general_body
    global general_information_frame, general_tab, good_button
    global goods_type_vars, goods_types_frame, hauler_combobox
    global import_master_button, import_state, incident_actions
    global incident_body, incident_cards, incident_cards_frame
    global incident_hint, incident_info, incident_tab, index
    global inspection_date_entry, item_form_store, item_form_var
    global item_frames, item_lists_frame, items_body, items_hint, items_tab
    global items_toolbar, key, label_text, legacy_master_list
    global lists_feedback, lists_sender, lists_state, location_combobox
    global lock_cover, log, logo, master_data, module_title, month_combo
    global month_var, mysql_box, mysql_feedback, mysql_label, mysql_numbers
    global mysql_on, mysql_sender, mysql_state, mysql_wait_state
    global mysql_waiting_label, nav, nav_buttons, nav_holder
    global new_frame_button, notebook, other_remarks_entries
    global other_remarks_frame, others_check, others_entry, others_var
    global packaging_entry, panel, panel_font, pdf_state, pick_row
    global print_pdf_button, quantity_entry, rail, rail_new, rail_open
    global range_label, remove_frame_button, remove_last_button
    global report_state, row, save_report_button, saved_theme
    global schedule_entries, schedule_frame, scroll_frames
    global searchable_combos, set_mysql_dots, settings, sidebar, small_font
    global source_var_weekly, start_theme, status_badge, status_label
    global status_var, style, summary_note, summary_tab, summary_tree
    global supplier_combobox, theme_button, title_font, topbar
    global transport_entries, transport_frame, tree_holder, ui_context
    global ui_theme, unfinished_state, user_box, user_store, warehouse_ui
    global week_buttons, week_row, week_var, weekly_state, window
    global withdrawal_panel, year_combo, year_var

    # Where things live. Managed workbooks and JSON data use parallel folders.
    FROZEN = bool(getattr(sys, "frozen", False))
    if FROZEN:
        BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        _documents = Path.home() / "Documents"
        DATA_ROOT = (_documents if _documents.exists() else Path.home()) / \
            "Field Survey Report"
        PRIVATE_JSON_DIR = Path(os.environ.get("APPDATA") or Path.home()) / \
            "FieldSurveyReport"
    else:
        BASE_DIR = Path(__file__).resolve().parent
        DATA_ROOT = BASE_DIR / "data"

    # Demo Mode keeps sample workbooks and JSON in separate subfolders; MySQL is
    # disabled. FSR_HOME provides the same layout for automated tests.
    DEMO_MODE = os.environ.get("FSR_DEMO", "").strip() == "1"
    _home = os.environ.get("FSR_HOME", "").strip()
    if _home:
        DATA_ROOT = Path(_home)

    JSON_ROOT = DATA_ROOT / "json"
    JSON_DIR = JSON_ROOT
    EXCEL_ROOT = DATA_ROOT / "excel"
    if DEMO_MODE and not _home:
        JSON_DIR = JSON_ROOT / "demo_data"
        DATA_DIR = EXCEL_ROOT / "demo_data"
    else:
        DATA_DIR = EXCEL_ROOT
    if not FROZEN or _home:
        PRIVATE_JSON_DIR = DATA_ROOT / "json" / "private"
    CONFIG_DIR = PRIVATE_JSON_DIR

    fsr_paths.configure_data_dirs(DATA_ROOT, JSON_ROOT, EXCEL_ROOT)

    for _folder in (DATA_DIR, JSON_DIR, PRIVATE_JSON_DIR):
        try:
            _folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise OSError(f"Could not create application data folder {_folder}: "
                          f"{error}") from error

    MASTER_LIST_FILE = JSON_DIR / "master_list.json"
    SETTINGS_FILE = ((JSON_DIR / "settings.json") if DEMO_MODE and not _home
                     else PRIVATE_JSON_DIR / "settings.json")
    USERS_FILE = PRIVATE_JSON_DIR / "users.json"
    LOG_FILE = PRIVATE_JSON_DIR / "field_survey_report.log"

    if not DEMO_MODE:
        if not MASTER_LIST_FILE.exists():
            legacy_master_list = DATA_ROOT / "master_list.json"
            if legacy_master_list.exists():
                MASTER_LIST_FILE.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy_master_list, MASTER_LIST_FILE)
        _default_files = [
            (MASTER_LIST_FILE, BASE_DIR / "data" / "json" / "master_list.json"),
        ]
        if fsr_edition.IS_OWNER_EDITION:
            _default_files.append(
                (PRIVATE_JSON_DIR / "db_config.json",
                 BASE_DIR / "data" / "json" / "private" / "installer_defaults"
                 / "db_config.json"))
        for _target, _source in _default_files:
            if not _target.exists() and _source.exists() and _target != _source:
                _target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(_source, _target)

    # The User edition keeps everything in this PC's Excel/JSON files and sends
    # Master Data files to the owner; only the Owner edition uses MySQL.
    IS_OWNER_EDITION = fsr_edition.IS_OWNER_EDITION
    MYSQL_ALLOWED = IS_OWNER_EDITION and not DEMO_MODE

    if db_mysql is not None:
        db_mysql.CONFIG_FILE = PRIVATE_JSON_DIR / "db_config.json"
        if not MYSQL_ALLOWED:
            db_mysql.is_enabled = lambda: False       # Demo Mode / User edition
        else:
            # A password still written in db_config.json goes to the Windows
            # Credential Manager (the file keeps it if that is not possible).
            # Whatever goes wrong here must never stop the program from
            # starting: the password then simply stays where it is.
            try:
                db_mysql.move_password_to_store()
            except Exception:
                logging.getLogger("fsr").exception(
                    "The MySQL password could not be moved to the Credential "
                    "Manager")

    # Names of the lists inside master_list.json.
    LOCATION_LIST_KEY = "location_list"
    DESTINATION_LIST_KEY = "destination_list"
    COUNTRY_LIST_KEY = "country_of_origin_list"

    THEME_LIGHT = "flatly"
    THEME_DARK = "superhero"          # becomes "fsr_night" when it can be built
    NIGHT_THEME = "fsr_night"         # the dark navy dashboard look
    UI_VERSION = 3                    # bump to show the new look once

    # =====================================================
    # LOGGING + SETTINGS
    # =====================================================

    log = logging.getLogger("fsr")
    log.setLevel(logging.INFO)
    try:
        _handler = RotatingFileHandler(
            LOG_FILE, maxBytes=500_000, backupCount=3, encoding="utf-8"
        )
        _handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        log.addHandler(_handler)
    except OSError:
        log.addHandler(logging.NullHandler())      # read-only folder: no log file


    settings = load_settings()


    # =====================================================
    # MAIN WINDOW
    # =====================================================

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # sharp text on HiDPI
        except (AttributeError, OSError):   # older Windows: no shcore / refused
            pass

    try:
        window = tb.Window(themename="superhero")
    except Exception:
        window = tb.Window(themename=THEME_LIGHT)

    style = tb.Style()
    window.title("Field Survey Report")

    NIGHT_COLORS = {
        "primary": "#5bc0eb", "secondary": "#3a4a6b", "success": "#2fbf9b",
        "info": "#7fd3f0", "warning": "#f5c04a", "danger": "#e8554e",
        "light": "#c5d0e6", "dark": "#0d1730", "bg": "#0f1a38",
        "fg": "#e8eefc", "selectbg": "#2a3f6f", "selectfg": "#ffffff",
        "border": "#3b5b8f", "inputfg": "#e8eefc", "inputbg": "#17254a",
        "active": "#1d2d57",
    }


    if make_night_theme():
        THEME_DARK = NIGHT_THEME

    # The light look of the warehouse update (navy navigation, white panels);
    # warehouse_ui/ holds the navigation and the warehouse modules.
    try:
        import warehouse_ui
        from warehouse_ui import theme as ui_theme
        if ui_theme.register_day_theme(style):
            THEME_LIGHT = ui_theme.DAY_THEME
    except Exception:
        warehouse_ui = ui_theme = None
        log.exception("The warehouse modules could not be loaded")

    try:
        saved_theme = settings.get("theme")
        start_theme = (saved_theme if settings.get("ui_version") == UI_VERSION
                       and saved_theme in (THEME_LIGHT, THEME_DARK)
                       else THEME_LIGHT)
        style.theme_use(start_theme)
        settings["theme"] = start_theme
    except Exception:
        log.exception("Could not apply the start theme")
    settings["ui_version"] = UI_VERSION

    # Window / taskbar icon = logo.png (+ logo.ico on Windows).
    # The app still starts if the logo files are missing. The icon is set
    # again a moment after start-up, because ttkbootstrap puts its own
    # feather icon on the window while it is being built.
    LOGO_PNG = BASE_DIR / "logo.png"
    LOGO_ICO = BASE_DIR / "logo.ico"
    logo = None


    apply_window_icon()
    window.after(200, apply_window_icon)
    window.after(1200, apply_window_icon)


    window.withdraw()
    if app_auth is None:
        messagebox.showerror(
            "Field Survey Report",
            f"The sign in module was not found.\n\nPut app_auth.py here:\n"
            f"{BASE_DIR}")
        window.destroy()
        sys.exit(1)

    try:
        # Only the Owner edition is installed with the owner's account.
        user_store = app_auth.UserStore(
            USERS_FILE, use_seed=fsr_edition.IS_OWNER_EDITION,
            site_pc=not fsr_edition.IS_OWNER_EDITION)
    except app_auth.UserDataError as error:
        messagebox.showerror(
            "Field Survey Report",
            f"{error}\n\nThe account file was not overwritten.")
        window.destroy()
        sys.exit(1)
    except OSError as error:
        messagebox.showerror(
            "Field Survey Report",
            f"The user file could not be opened:\n{USERS_FILE}\n\n{error}")
        window.destroy()
        sys.exit(1)

    if user_store.backup_path is not None:
        log.info("The account file was brought up to date. The earlier file is "
                 "kept as %s; %d retired account(s) removed.",
                 user_store.backup_path, len(user_store.removed_accounts))
    if user_store.problem is not None:
        log.warning("The account file is not trusted (%s): sign in is limited "
                    "to an Administrator until it is reviewed.",
                    user_store.problem["kind"])

    current_user = app_auth.run_login(
        window, user_store, last_initials=settings.get("last_login_initials", ""),
        on_icon=icon_for_dialog)
    if current_user is None:
        window.destroy()
        sys.exit(0)

    settings["last_login_initials"] = current_user.get("initials", "")
    save_settings()
    USER_FULL_NAME = app_auth.full_name(current_user)      # printed on the forms
    set_control_initials(current_user.get("initials"))     # in every new Control #
    print_name["value"] = USER_FULL_NAME   # preparer of this printout (fsr_forms)
    IS_OWNER = app_auth.is_admin(current_user)   # Owner or site Administrator
    ROLE_LABEL = app_auth.role_text(current_user)
    # A copy that runs from the source folder is a TEST COPY: the title bar
    # always says so, and it does not connect to the real database unless
    # db_config.json explicitly allows it (db_mysql.refuses_real_database).
    TEST_COPY = not FROZEN


    window.title(f"{title_prefix()}Field Survey Report "
                 f"({fsr_edition.LABEL} edition) - {USER_FULL_NAME}")


    center_window(window, 1440, 820)
    window.minsize(1180, 640)

    default_font = tkfont.nametofont("TkDefaultFont")
    bold_font = default_font.copy()
    bold_font.configure(weight="bold")
    title_font = default_font.copy()
    title_font.configure(weight="bold", size=default_font.cget("size") + 8)


    window.report_callback_exception = log_unhandled

    # =====================================================
    # STATE
    # =====================================================

    DEFAULT_EXCEL_NAME = ("Field_Survey_Reports_DEMO.xlsx" if DEMO_MODE
                          else "Field_Survey_Reports.xlsx")


    # Excel file in use + whether the form shows a saved report / has changes.
    excel_state = {"path": initial_excel_path()}
    report_state = {"editing": False, "dirty": False}
    pdf_state = {"folder": settings.get("pdf_folder")}

    # Filled in later (declared here so callbacks can refer to them).
    item_frames = []
    findings_frame = None

    # =====================================================
    # SCROLLABLE TAB
    # =====================================================

    scroll_frames = []


    window.bind_all("<MouseWheel>", on_mousewheel)
    window.bind_all("<Button-4>", on_mousewheel)
    window.bind_all("<Button-5>", on_mousewheel)


    window.bind_all("<FocusIn>", on_focus_in)

    # =====================================================
    # KEYBOARD NAVIGATION
    #   Up / Down        in a text box: go to the box above / below
    #   Ctrl + Up / Down in a drop-down: go to the box above / below
    #   Left / Right     move inside the text (and between tabs on a tab)
    #   Page Up / Down   scroll the page;  Ctrl + Home / End: top / bottom
    #   Ctrl + PgUp / PgDn  (Ctrl + Tab)  previous / next tab
    # =====================================================

    FIELD_CLASSES = ("TEntry", "TCombobox")


    window.bind_class("TEntry", "<Up>",
                      lambda e: move_to_neighbour(e, -1), add="+")
    window.bind_class("TEntry", "<Down>",
                      lambda e: move_to_neighbour(e, 1), add="+")
    window.bind_class("TCombobox", "<Control-Up>",
                      lambda e: move_to_neighbour(e, -1), add="+")
    window.bind_class("TCombobox", "<Control-Down>",
                      lambda e: move_to_neighbour(e, 1), add="+")
    window.bind_all("<Prior>", lambda e: scroll_page(e, -1), add="+")
    window.bind_all("<Next>", lambda e: scroll_page(e, 1), add="+")
    window.bind_all("<Control-Home>", lambda e: scroll_page(e, "top"), add="+")
    window.bind_all("<Control-End>", lambda e: scroll_page(e, "bottom"), add="+")


    # =====================================================
    # DIRTY FLAG (unsaved changes)
    # =====================================================

    IGNORED_KEYS = {
        "Tab", "ISO_Left_Tab", "Shift_L", "Shift_R", "Control_L", "Control_R",
        "Alt_L", "Alt_R", "Escape", "Up", "Down", "Left", "Right", "Home",
        "End", "Prior", "Next", "Caps_Lock", "Return", "Num_Lock",
    }


    window.bind_all("<KeyRelease>", on_any_key, add="+")
    window.bind_all("<<ComboboxSelected>>", on_combo_selected, add="+")


    master_data = load_master_lists()

    # =====================================================
    # SEARCHABLE COMBOBOX
    # =====================================================

    NAV_KEYS = (
        "Return", "Escape", "Tab", "ISO_Left_Tab",
        "Up", "Down", "Left", "Right", "Home", "End",
        "Shift_L", "Shift_R", "Control_L", "Control_R",
    )

    searchable_combos = []


    # =====================================================
    # LINE LIMIT DISPLAY
    # =====================================================

    LOW_LINES_WARNING = 3      # turn orange when this few lines are left


    FIELD_COLUMNS = 4       # every frame of the General tab shares this grid


    # =====================================================
    # STATUS / NOTIFICATIONS
    # =====================================================

    status_var = tkinter.StringVar()


    # =====================================================
    # LAYOUT  (dashboard style)
    #   top bar | icon rail | sections menu | page | commands panel
    # =====================================================

    NAV_WIDTH = 210
    PANEL_WIDTH = 300
    small_font = default_font.copy()
    small_font.configure(weight="bold", size=max(default_font.cget("size") - 1, 8))
    panel_font = default_font.copy()
    panel_font.configure(weight="bold", size=default_font.cget("size") + 4)


    # ---------- navigation sidebar (filled by warehouse_ui at start-up) ----------
    if ui_theme is not None:
        ui_theme.apply_styles(style)
    sidebar = ttk.Frame(window, style="Sidebar.TFrame", width=272)
    sidebar.pack(side="left", fill="y")
    sidebar.pack_propagate(False)

    # ---------- top bar ----------
    topbar = tb.Frame(window, padding=(16, 10))
    topbar.pack(side="top", fill="x")

    module_title = tb.Label(topbar, text="Inspection Reports", font=title_font)
    module_title.pack(side="left", padx=(4, 12))
    if DEMO_MODE:
        tb.Label(topbar, text="DEMO MODE - TEST DATA ONLY", font=bold_font,
                 bootstyle="inverse-warning", padding=(10, 3)).pack(
            side="left", padx=(0, 4))
    status_badge = tb.Label(
        topbar, text="NEW REPORT", bootstyle="inverse-info",
        padding=(10, 3), font=bold_font
    )
    status_badge.pack(side="left", padx=16)

    # the MySQL status (three circles + label) is placed here further down
    mysql_box = tb.Frame(topbar)
    mysql_box.pack(side="right")

    # signed-in user + account menu (left of the MySQL circles)
    user_box = tb.Frame(topbar)
    user_box.pack(side="right", padx=(0, 22))
    account_menu_button = tb.Menubutton(
        user_box, text=f"{USER_FULL_NAME}  ({ROLE_LABEL})  \u25be",
        bootstyle="secondary-outline"
    )
    account_menu_button.pack()
    account_menu = tkinter.Menu(account_menu_button, tearoff=False)
    account_menu_button["menu"] = account_menu


    rebuild_account_menu()
    account_menu.configure(postcommand=rebuild_account_menu)

    ttk.Separator(window, orient="horizontal").pack(side="top", fill="x")

    # ---------- body: 4 columns ----------
    body = tb.Frame(window)
    body.pack(side="top", fill="both", expand=True)
    body.columnconfigure(2, weight=1)
    body.rowconfigure(0, weight=1)

    # icon rail (new / open / light-dark)
    rail = tb.Frame(body, padding=(10, 14))
    rail.grid(row=0, column=0, sticky="ns")
    rail_new = tb.Button(rail, text="+", width=3, bootstyle="info-outline",
                         command=lambda: new_report())
    rail_new.pack(pady=(0, 8))
    rail_open = tb.Button(rail, text="☰", width=3, bootstyle="info-outline",
                          command=lambda: open_saved_report_dialog())
    rail_open.pack(pady=8)
    theme_button = tb.Button(rail, text="◐", width=3,
                             bootstyle="info-outline",
                             command=lambda: toggle_theme())
    theme_button.pack(pady=8)
    add_tip(rail_new, "New report (Ctrl+N)")
    add_tip(rail_open, "Open saved report (Ctrl+O)")
    add_tip(theme_button, "Light / dark mode")

    # sections menu (filled in once all pages exist)
    nav = tb.Frame(body, padding=(8, 14), width=NAV_WIDTH)
    nav.grid(row=0, column=1, sticky="ns")
    nav.pack_propagate(False)
    section_title(nav, "Sections", first=True)
    nav_holder = tb.Frame(nav)
    nav_holder.pack(fill="x")


    if hide_notebook_tabs():
        notebook = ttk.Notebook(body, style="Hidden.TNotebook")
    else:
        notebook = tb.Notebook(body, bootstyle="primary")
    notebook.grid(row=0, column=2, sticky="nsew", padx=(6, 6), pady=(8, 8))

    general_tab = ScrollFrame(notebook)
    documents_tab = ScrollFrame(notebook)
    items_tab = ScrollFrame(notebook, horizontal=True)
    findings_tab = ScrollFrame(notebook)

    notebook.add(general_tab, text="  General  ")
    notebook.add(documents_tab, text="  Documents & Goods  ")
    notebook.add(items_tab, text="  Item Lists  ")
    notebook.add(findings_tab, text="  Additional Details  ")
    notebook.enable_traversal()       # Ctrl+Tab / Ctrl+PgUp / Ctrl+PgDn

    # ---------- commands panel ----------
    panel = tb.Frame(body, padding=(16, 14), width=PANEL_WIDTH)
    panel.grid(row=0, column=3, sticky="ns")
    panel.pack_propagate(False)

    status_label = tb.Label(panel, textvariable=status_var, bootstyle="secondary",
                            wraplength=PANEL_WIDTH - 40, justify="left")
    status_label.pack(side="bottom", anchor="w", pady=(8, 0))

    tb.Label(panel, text="General commands", font=panel_font).pack(anchor="w")
    ttk.Separator(panel, orient="horizontal").pack(fill="x", pady=(8, 12))

    section_title(panel, "Report", first=True)
    tb.Label(panel, text="Control #").pack(anchor="w")
    # Control # is generated automatically and cannot be typed over.
    control_entry = tb.Entry(panel, state="readonly", font=bold_font)
    control_entry.pack(fill="x", pady=(2, 0))

    section_title(panel, "Cargo condition")
    condition_var = tkinter.StringVar(value="")      # nothing chosen yet
    condition_row = tb.Frame(panel)
    condition_row.pack(fill="x")
    condition_row.columnconfigure(0, weight=1, uniform="cond")
    condition_row.columnconfigure(1, weight=1, uniform="cond")
    good_button = tb.Button(condition_row, text=CONDITION_GOOD,
                            command=lambda: choose_condition(CONDITION_GOOD))
    good_button.grid(row=0, column=0, sticky="we", padx=(0, 3))
    bad_button = tb.Button(condition_row, text=CONDITION_BAD,
                           command=lambda: choose_condition(CONDITION_BAD))
    bad_button.grid(row=0, column=1, sticky="we", padx=(3, 0))


    condition_var.trace_add("write", refresh_condition_buttons)
    refresh_condition_buttons()

    # ---- the form stays locked until Good Order / Bad Order is chosen ----
    # A cover sits over the pages (the Weekly Summary page is not covered).
    lock_cover = tb.Frame(body, padding=30)
    tb.Label(
        lock_cover, text="Select the Cargo Condition to start",
        font=title_font, bootstyle="info", anchor="center"
    ).pack(pady=(80, 8))
    tb.Label(
        lock_cover,
        text="Choose  Good Order  or  Bad Order  in the panel on the right "
             "before you start writing the report.",
        bootstyle="secondary", anchor="center", justify="center"
    ).pack()


    condition_var.trace_add("write", update_form_lock)
    window.bind_all("<FocusIn>", keep_focus_out_of_locked_form, add="+")
    update_form_lock()

    section_title(panel, "Actions")
    save_report_button = tb.Button(
        panel, text="SAVE (Ctrl+S)", bootstyle="success",
        command=lambda: save_report()
    )
    save_report_button.pack(fill="x", pady=3)
    print_pdf_button = tb.Button(
        panel, text="Print / PDF...  (Ctrl+P)", bootstyle="info-outline",
        command=lambda: print_pdf_current_report()
    )
    print_pdf_button.pack(fill="x", pady=3)

    section_title(panel, "Storage")
    file_label = tb.Label(panel, text="", bootstyle="secondary",
                          wraplength=PANEL_WIDTH - 40, justify="left")
    file_label.pack(anchor="w", pady=(0, 4))
    change_file_button = tb.Button(
        panel, text="Change Excel File...", bootstyle="secondary-outline",
        command=lambda: change_excel_file()
    )
    change_file_button.pack(fill="x", pady=3)
    import_master_button = tb.Button(
        panel, text="Import Master Data...", bootstyle="secondary-outline",
        command=lambda: import_master_data_file()
    )
    if IS_OWNER_EDITION:        # the owner compiles the files of every site
        import_master_button.pack(fill="x", pady=3)
    export_master_button = tb.Button(
        panel, text="Export Master Data...", bootstyle="secondary-outline",
        command=lambda: export_master_data()
    )
    export_master_button.pack(fill="x", pady=3)

    # MySQL: three circles. All three colours = MySQL works,
    # three red circles = it does not. Click them to check again.
    mysql_on = db_mysql is not None and db_mysql.is_enabled()
    DOT_OK = ("#f6c945", "#3dbb93", "#ee5a4f")       # yellow, green, red
    DOT_BAD = ("#e0392d",) * 3
    DOT_WAIT = ("#6b7894",) * 3
    mysql_state = {"text": "Checking MySQL..."}

    if IS_OWNER_EDITION:    # the User edition never uses MySQL
        section_title(panel, "MySQL")
        mysql_label = tb.Label(mysql_box, text="Checking...",
                               font=bold_font, bootstyle="secondary")
        mysql_label.pack(side="right", padx=(8, 0))
        dots_canvas = tkinter.Canvas(
            mysql_box, width=104, height=32, highlightthickness=0, bd=0,
            background=style.colors.bg, cursor="hand2"
        )
        dots_canvas.pack(side="right")
        mysql_waiting_label = tb.Label(mysql_box, text="", bootstyle="warning")
        mysql_waiting_label.pack(side="right", padx=(0, 8))
        dot_items = [
            dots_canvas.create_oval(4 + i * 34, 4, 4 + i * 34 + 26, 30,
                                    fill=DOT_WAIT[i], outline="")
            for i in range(3)
        ]

        def set_mysql_dots(state, message=""):
            colors = {"ok": DOT_OK, "bad": DOT_BAD}.get(state, DOT_WAIT)
            for item, color in zip(dot_items, colors):
                dots_canvas.itemconfigure(item, fill=color)
            mysql_label.configure(
                text={"ok": "Server active", "bad": "Server inactive"}.get(
                    state, "Checking..."),
                bootstyle={"ok": "success", "bad": "danger"}.get(
                    state, "secondary"))
            mysql_state["text"] = message or {
                "ok": "MySQL is working", "bad": "MySQL is not working",
            }.get(state, "Checking MySQL...")

        def check_mysql_status(show_error=False):
            """Test the connection in the background (the window never freezes)."""
            set_mysql_dots("wait")
            result = {}

            def worker():
                try:
                    if db_mysql is None or not db_mysql.is_enabled():
                        result["value"] = (
                            False, "MySQL is turned off. Open the account menu "
                                   "(top right) > MySQL Settings to set it up.")
                    else:
                        check = getattr(db_mysql, "check_connection", None)
                        if check is not None:
                            ok, message, away = check()
                            result["value"] = (ok, message)
                            result["away"] = away
                        else:
                            result["value"] = db_mysql.test_connection()
                except Exception as error:
                    result["value"] = (False, str(error))

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()

            def poll():
                if thread.is_alive():
                    window.after(150, poll)
                    return
                ok, message = result.get("value", (False, "No answer"))
                set_mysql_dots("ok" if ok else "bad", message)
                if ok and "finish_unfinished_saves" in globals():
                    # MySQL catches up, MySQL's numbers are read and (first
                    # run) equal reports are adopted - all in the background.
                    finish_unfinished_saves(mysql_ok=True, numbers=True,
                                            adopt=True)
                if show_error and not ok:
                    if db_mysql is None or not db_mysql.is_enabled():
                        open_mysql_settings()
                    elif result.get("away"):
                        notify("MySQL was not reached  -  reports are saved on "
                               "this PC and sent when it is back",
                               bootstyle="warning")
                    else:
                        messagebox.showerror("MySQL", message, parent=window)

            window.after(150, poll)

        dots_canvas.bind("<Button-1>", lambda e: check_mysql_status(True))
        add_tip(dots_canvas, "Three colours: the MySQL server is active. "
                             "Three red: inactive.\nClick to check again "
                             "(or to set MySQL up).")

        tb.Button(
            panel, text="Sync to MySQL", bootstyle="secondary-outline",
            command=lambda: sync_all_to_mysql()
        ).pack(fill="x", pady=3)
        tb.Button(
            panel, text="Restore Excel from MySQL", bootstyle="secondary-outline",
            command=lambda: restore_excel_from_mysql()
        ).pack(fill="x", pady=3)


    general_body = general_tab.body

    general_information_frame = tb.Labelframe(
        general_body, text="General Information", padding=12
    )
    general_information_frame.grid(row=1, column=0, pady=6, sticky="we")
    for _col in range(4):
        general_information_frame.columnconfigure(_col, weight=1, uniform="gi")

    SO_number_entry = tb.Entry(general_information_frame)
    add_field(general_information_frame, "SO Number", SO_number_entry, 0, 0)

    inspection_date_entry = tb.DateEntry(
        general_information_frame, dateformat=DATE_FORMAT, firstweekday=0,
        bootstyle="primary"
    )
    add_field(general_information_frame, "Inspection Date",
              inspection_date_entry, 0, 1)


    # Choosing / typing an Inspection Date copies it to the Commenced Date
    # (unless the user already typed a different Commenced Date).
    date_sync = {"last": ""}


    inspection_date_entry.bind("<<DateEntrySelected>>", sync_commenced_date,
                               add="+")
    inspection_date_entry.entry.bind("<FocusOut>", sync_commenced_date, add="+")
    inspection_date_entry.entry.bind("<Return>", sync_commenced_date, add="+")


    consignee_combobox = create_searchable_combobox(
        general_information_frame, "consignee_list")
    add_field(general_information_frame, "Consignee", consignee_combobox, 1, 0)

    supplier_combobox = create_searchable_combobox(
        general_information_frame, "supplier_list")
    add_field(general_information_frame, "Supplier", supplier_combobox, 1, 1)

    brokerage_combobox = create_searchable_combobox(
        general_information_frame, "broker_list")
    add_field(general_information_frame, "Brokerage", brokerage_combobox, 1, 2)

    hauler_combobox = create_searchable_combobox(
        general_information_frame, "hauler_list")
    add_field(general_information_frame, "Hauler", hauler_combobox, 1, 3)

    location_combobox = create_searchable_combobox(
        general_information_frame, LOCATION_LIST_KEY)
    add_field(general_information_frame, "Location", location_combobox, 2, 0)

    destination_combobox = create_searchable_combobox(
        general_information_frame, DESTINATION_LIST_KEY)
    add_field(general_information_frame, "Destination", destination_combobox, 2, 1)

    country_combobox = create_searchable_combobox(
        general_information_frame, COUNTRY_LIST_KEY)
    add_field(general_information_frame, "Country of Origin",
              country_combobox, 2, 2)

    # Inspection Schedule Summary
    schedule_frame = tb.Labelframe(
        general_body, text="Inspection Schedule Summary", padding=12
    )
    schedule_frame.grid(row=2, column=0, pady=6, sticky="we")
    # Activity | Commenced Date | Commenced Time   (row 1)
    #            Completion Date | Completion Time (row 2)
    schedule_entries = build_field_row(
        schedule_frame, SCHEDULE_FIELDS,
        layout=[(0, 0), (0, 1), (0, 2), (1, 1), (1, 2)]
    )

    # Shipment / Transport Details
    transport_frame = tb.Labelframe(
        general_body, text="Shipment/Transport Details", padding=12
    )
    transport_frame.grid(row=3, column=0, pady=6, sticky="we")
    transport_entries = build_field_row(transport_frame, TRANSPORT_FIELDS)

    # =====================================================
    # TAB 2 - DOCUMENTS USED, DECLARED GOODS, OTHER REMARKS
    # =====================================================

    documents_body = documents_tab.body

    documents_used_frame = tb.Labelframe(
        documents_body, text="Documents Used", padding=12
    )
    documents_used_frame.grid(row=0, column=0, pady=6, sticky="we")

    # DOCUMENT_FIELDS (label text, JSON key) is in fsr_storage.py.

    DOCUMENT_COLUMNS = 4
    document_entries = {}

    for _col in range(DOCUMENT_COLUMNS):
        documents_used_frame.columnconfigure(_col, weight=1, uniform="doc")

    for index, (label_text, key) in enumerate(DOCUMENT_FIELDS):
        entry = tb.Entry(documents_used_frame)
        add_field(documents_used_frame, label_text, entry,
                  index // DOCUMENT_COLUMNS, index % DOCUMENT_COLUMNS)
        document_entries[key] = entry

    declared_goods_frame = tb.Labelframe(
        documents_body, text="Declared Goods (up to 5 lines print on the form)",
        padding=12
    )
    declared_goods_frame.grid(row=1, column=0, pady=1)
    declared_goods_frame.columnconfigure(0, weight=1)

    for _col, _text in enumerate(("Description", "Quantity", "Packaging")):
        tb.Label(declared_goods_frame, text=_text).grid(
            row=0, column=_col, padx=1, pady=(0, 2)
        )

    declared_goods_rows = []   # each item: (description, quantity, packaging)

    for row in range(1, 6):
        description_entry = tb.Entry(declared_goods_frame, width=40)
        description_entry.grid(row=row, column=0, padx=1, pady=3)

        quantity_entry = tb.Entry(declared_goods_frame, width=12)
        quantity_entry.grid(row=row, column=1, padx=1, pady=3)

        packaging_entry = tb.Entry(declared_goods_frame, width=18)
        packaging_entry.grid(row=row, column=2, padx=1, pady=3)

        declared_goods_rows.append(
            (description_entry, quantity_entry, packaging_entry)
        )

    # Types of Goods: the six check boxes of the First Page form.
    goods_types_frame = tb.Labelframe(
        documents_body, text="Types of Goods (ticks the check boxes on the First Page)",
        padding=12
    )
    goods_types_frame.grid(row=2, column=0, pady=6)

    goods_type_vars = {key: tkinter.BooleanVar() for _, key in GOODS_TYPES}
    others_var = tkinter.BooleanVar()

    for _col, (_label, _key) in enumerate(GOODS_TYPES):
        tb.Checkbutton(
            goods_types_frame, text=_label, variable=goods_type_vars[_key],
            command=mark_dirty
        ).grid(row=0, column=_col, padx=(8, 18), pady=2, sticky="w")


    others_check = tb.Checkbutton(
        goods_types_frame, text="Others:", variable=others_var,
        command=on_others_toggled
    )
    others_check.grid(row=0, column=len(GOODS_TYPES), padx=(8, 4), pady=2,
                      sticky="w")
    others_entry = tb.Entry(goods_types_frame, width=28, state="disabled")
    others_entry.grid(row=0, column=len(GOODS_TYPES) + 1, padx=(0, 8), pady=2)
    goods_types_frame.columnconfigure(len(GOODS_TYPES) + 1, weight=1)


    OTHER_REMARKS_MAX = 12      # the First Page form has 12 remark lines

    other_remarks_frame, other_remarks_entries = create_remarks_section(
        documents_body,
        title="Other Important Remarks",
        entry_width=60,
        initial_rows=5,
        max_rows=OTHER_REMARKS_MAX
    )
    other_remarks_frame.grid(row=3, column=0, pady=6)

    # =====================================================
    # TAB 3 - ITEM LISTS
    # =====================================================

    MAX_ROWS = 30

    # ITEM_HEADERS (the printed Item List columns) is in fsr_storage.py.
    # The Default form shows them with UOM after Quantity, Weight Unit after
    # Weights and Currency before the prices. Weight Unit is a form box only:
    # it is saved together with the number in Weights ("1,250 KG").
    # Cargo ID / Receiving Ref are not shown: values saved earlier
    # (and the Receiving Ref given at save time) are kept with the line.
    ITEM_FORM_HEADERS = [
        "Description of Goods", "PO Number", "Packaging", "Quantity", "UOM",
        "Dimensions", "Weights", "Weight Unit", "Currency", "Unit Price",
        "Total Price", "Findings",
    ]
    ITEM_WIDTHS = [32, 12, 14, 9, 9, 12, 9, 7, 7, 11, 12, 28]
    # Containerized / Loading forms (Containerized_Loading_Form.xlsx): the
    # Container No. / Truck Plate No. first, no PO Number and no prices.
    # Each form keeps its own lines (see set_item_form).
    UNIT_FORM_HEADERS = [
        UNIT_NO_HEADER, "Description of Goods", "Packaging", "Quantity", "UOM",
        "Dimensions", "Weights", "Weight Unit", "Findings",
    ]
    UNIT_FORM_WIDTHS = [18, 32, 14, 9, 9, 12, 9, 7, 28]
    UNIT_FORM_LABELS = {"Description of Goods": "Description",
                        "Dimensions": "Dimension", "Weights": "Weight"}
    ITEM_FORM_COLUMNS = {
        ITEM_FORM_DEFAULT: (ITEM_FORM_HEADERS, ITEM_WIDTHS),
        ITEM_FORM_CONTAINERIZED: (UNIT_FORM_HEADERS, UNIT_FORM_WIDTHS),
        ITEM_FORM_LOADING: (UNIT_FORM_HEADERS, UNIT_FORM_WIDTHS),
    }
    # A line is saved when one of these has text (Cargo ID / Receiving Ref
    # alone do not make a line).
    SAVED_LINE_HEADERS = [h for h in ITEM_LINE_HEADERS
                          if h not in ITEM_LINK_HEADERS]
    ITEM_HEADER_TIPS = {
        "Quantity": "The number only, e.g. 12. The unit goes in UOM.",
        "Weights": "The number only, e.g. 1,250. The unit goes in Weight Unit.",
        "Currency": "Currency of the Unit Price and Total Price.",
    }

    item_form_var = tkinter.StringVar(value=ITEM_FORM_DEFAULT)

    items_body = items_tab.body

    items_toolbar = tb.Frame(items_body)
    items_toolbar.grid(row=0, column=0, sticky="w", pady=(0, 6))

    item_lists_frame = tb.Frame(items_body)
    item_lists_frame.grid(row=1, column=0)
    item_lists_frame.columnconfigure(0, weight=1)


    # Lines typed on the forms not shown: form -> [(lines, row count)] per
    # Item List. Each form keeps its own lines; every form with lines is
    # printed. The selected form is the one that counts as stock.
    item_form_store = {}


    ITEM_FORM_HINTS = {
        ITEM_FORM_DEFAULT:
            "Total Price = Quantity x Unit Price unless you type it yourself.  "
            "Shift + mouse wheel scrolls sideways.",
        ITEM_FORM_CONTAINERIZED:
            "One line per cargo with its Container No.  Prints on the "
            "Containerized form.",
        ITEM_FORM_LOADING:
            "One line per cargo with its Truck Plate No.  Prints on the "
            "Loading form.",
    }

    form_row = tb.Frame(items_toolbar)
    form_row.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
    tb.Label(form_row, text="Item List Form:", font=bold_font).pack(
        side="left", padx=(0, 6))
    for _form in ITEM_FORMS:
        tb.Radiobutton(
            form_row, text=_form, value=_form, variable=item_form_var,
            bootstyle="info-outline-toolbutton", width=14,
            command=choose_item_form
        ).pack(side="left", padx=(0, 4))
    add_tip(form_row,
            "Default - the original columns.\n"
            "Containerized - Container No. first (Containerized form).\n"
            "Loading - Truck Plate No. first (Loading form).\n"
            "Each form keeps its own lines, and every form with lines is\n"
            "printed. The form selected when you save counts as stock.")

    new_frame_button = tb.Button(
        items_toolbar, text="Create New Item List", bootstyle="primary",
        command=add_item_frame
    )
    new_frame_button.grid(row=1, column=0, padx=(0, 8))

    remove_frame_button = tb.Button(
        items_toolbar, text="Remove Last Item List",
        bootstyle="secondary-outline", command=remove_item_frame
    )
    remove_frame_button.grid(row=1, column=1)

    items_hint = tb.Label(
        items_toolbar, text=ITEM_FORM_HINTS[ITEM_FORM_DEFAULT],
        bootstyle="secondary"
    )
    items_hint.grid(row=1, column=2, padx=16)


    withdrawal_panel = WithdrawalPanel(items_body, SimpleNamespace(
        window=window, activity_entry=schedule_entries["activity"],
        form_var=item_form_var,
        main_path=lambda: Path(excel_state["path"]),
        control_no=lambda: control_entry.get().strip(),
        sections=lambda: item_frames,
        stored_in_main=lambda: report_state["editing"],
        header_po_entry=lambda: document_entries["po_number"],
        mark_dirty=mark_dirty,
    ), row=2)
    for _event in ("<<ComboboxSelected>>", "<FocusOut>"):
        schedule_entries["activity"].bind(
            _event, lambda e: withdrawal_panel.context_changed(), add="+")

    # =====================================================
    # TAB 4 - ADDITIONAL DETAILS (free text; saved as the report's remark lines)
    # Created ONCE (shared by all Item Lists).
    # =====================================================

    findings_frame, findings_entries = create_remarks_section(
        findings_tab.body,
        title="Additional Details",
        entry_width=100,
        initial_rows=5,
        max_rows=60,
        capacity_func=lambda: remark_capacity(total_item_rows())
    )
    findings_frame.grid(row=0, column=0, pady=6)

    # =====================================================
    # WEEKLY SUMMARY REPORT
    # Month + year + week -> one line per item of every report inspected in
    # that week, with the report's supplier / documents / vehicle / cargo
    # condition. "Export" saves it as an Excel file.
    # =====================================================

    # A weekly row has 28 fields: the columns below, except that Quantity is
    # split into Quantity + UOM and each price comes after a Currency field.
    # The table / Excel show them together ("6 pcs", "jpy 460,000.00").
    WEEKLY_COLUMNS = [               # (heading, width in pixels)
        ("SO Number", 120), ("Date", 95), ("Activity", 85),
        ("Shipment type", 95), ("Supplier", 160), ("Broker", 140),
        ("Hauler", 140), ("Destination", 105), ("Origin", 100),
        ("Invoice", 100), ("Purchase Order", 115), ("Job Order", 95),
        ("Gatepass", 95), ("BL / AWB", 105), ("DR", 85),
        ("Vehicle Type", 115), ("Plate #", 95),
        ("Description", 230), ("PO", 95), ("Packaging", 95), ("Quantity", 85),
        ("Dimension", 105), ("Weight", 85),
        ("Unit Price", 115), ("Total Price", 125), ("Cargo Condition", 115),
    ]
    WEEKLY_NUMBER_COLUMNS = {"Unit Price", "Total Price"}
    WEEKLY_QTY, WEEKLY_UOM, WEEKLY_CURRENCY = 20, 21, 24   # field positions
    WEEKLY_ITEM_KEYS = ("Description of Goods", "PO Number", "Packaging",
                        "Quantity", "UOM", "Dimensions", "Weights", "Currency",
                        "Unit Price", "Total Price")
    MONTH_LIST = [calendar.month_name[n] for n in range(1, 13)]
    weekly_state = {"rows": [], "span": None}


    # ---------- the page ----------
    summary_tab = tb.Frame(notebook, padding=(14, 12))
    notebook.add(summary_tab, text="  Weekly Summary  ")
    summary_tab.columnconfigure(0, weight=1)
    summary_tab.rowconfigure(3, weight=1)

    _today = date.today()
    month_var = tkinter.StringVar(value=calendar.month_name[_today.month])
    year_var = tkinter.StringVar(value=str(_today.year))
    week_var = tkinter.IntVar(value=min((_today.day - 1) // 7 + 1, 5))
    source_var_weekly = tkinter.StringVar(
        value="mysql" if db_mysql is not None and db_mysql.is_enabled()
        else "excel")

    pick_row = tb.Frame(summary_tab)
    pick_row.grid(row=0, column=0, sticky="we")
    tb.Label(pick_row, text="Month", font=bold_font).pack(side="left", padx=(0, 8))
    month_combo = tb.Combobox(pick_row, textvariable=month_var, values=MONTH_LIST,
                              state="readonly", width=14)
    month_combo.pack(side="left")
    year_combo = tb.Combobox(
        pick_row, textvariable=year_var, state="readonly", width=7,
        values=[str(y) for y in range(_today.year - 6, _today.year + 2)])
    year_combo.pack(side="left", padx=8)
    for _combo in (month_combo, year_combo):
        _combo.no_dirty = True          # picking a month is not a report edit
        scroll_instead_of_change(_combo)

    export_weekly_button = tb.Button(
        pick_row, text="Export", bootstyle="info", width=14,
        command=lambda: export_weekly_summary()
    )
    export_weekly_button.pack(side="right")

    if db_mysql is not None and db_mysql.is_enabled():
        for _text, _value in (("MySQL database", "mysql"), ("Excel file", "excel")):
            tb.Radiobutton(
                pick_row, text=_text, value=_value, variable=source_var_weekly,
                command=lambda: refresh_weekly()
            ).pack(side="right", padx=(0, 12))
        tb.Label(pick_row, text="Data from:").pack(side="right", padx=(0, 6))

    week_row = tb.Frame(summary_tab)
    week_row.grid(row=1, column=0, sticky="we", pady=(10, 2))
    week_buttons = {}
    for _week in (1, 2, 3, 4, 5, 0):
        _button = tb.Button(
            week_row, text="Week %d" % _week if _week else "Whole month",
            bootstyle="secondary-outline", width=12,
            command=lambda w=_week: choose_week(w)
        )
        _button.pack(side="left", padx=(0, 6))
        week_buttons[_week] = _button
    range_label = tb.Label(summary_tab, text="", bootstyle="secondary")
    range_label.grid(row=2, column=0, sticky="w", pady=(2, 8))

    tree_holder = tb.Frame(summary_tab)
    tree_holder.grid(row=3, column=0, sticky="nsew")
    tree_holder.columnconfigure(0, weight=1)
    tree_holder.rowconfigure(0, weight=1)
    summary_tree = ttk.Treeview(
        tree_holder, columns=[f"c{i}" for i in range(len(WEEKLY_COLUMNS))],
        show="headings", selectmode="browse"
    )
    for _index, (_heading, _width) in enumerate(WEEKLY_COLUMNS):
        summary_tree.heading(f"c{_index}", text=_heading)
        summary_tree.column(
            f"c{_index}", width=_width, minwidth=60, stretch=False,
            anchor="e" if _heading in WEEKLY_NUMBER_COLUMNS else "w")
    _vsb = ttk.Scrollbar(tree_holder, orient="vertical",
                         command=summary_tree.yview)
    _hsb = ttk.Scrollbar(tree_holder, orient="horizontal",
                         command=summary_tree.xview)
    summary_tree.configure(yscrollcommand=_vsb.set, xscrollcommand=_hsb.set)
    summary_tree.grid(row=0, column=0, sticky="nsew")
    _vsb.grid(row=0, column=1, sticky="ns")
    _hsb.grid(row=1, column=0, sticky="we")

    summary_note = tb.Label(summary_tab, text="", bootstyle="secondary")
    summary_note.grid(row=4, column=0, sticky="w", pady=(8, 0))


    # =====================================================
    # TAB 5 - INCIDENT REPORT (only shown for Bad Order)
    # One card per Incident Report form (15 lines each). When a card is
    # full, "+ Add Additional Incident Report" adds the next one.
    # Saved to a JSON file - NOT to the Excel file.
    # =====================================================

    INCIDENT_TAB_TEXT = "  Incident Report  "

    incident_tab = ScrollFrame(notebook)      # added to the notebook on demand
    incident_body = incident_tab.body
    incident_cards = []

    incident_info = tb.Label(
        incident_body,
        text="Type what happened, one statement per line (about 110 characters "
             "fit on a printed line). The header is filled from the report; "
             "you can change it.",
        bootstyle="secondary", justify="left"
    )
    incident_info.grid(row=0, column=0, sticky="w", pady=(0, 6))

    incident_cards_frame = tb.Frame(incident_body)
    incident_cards_frame.grid(row=1, column=0, sticky="we")
    incident_cards_frame.columnconfigure(0, weight=1)

    incident_actions = tb.Frame(incident_body)
    incident_actions.grid(row=2, column=0, sticky="w", pady=(8, 0))


    add_more_button = tb.Button(
        incident_actions, text="+ Add Additional Incident Report",
        bootstyle="primary", command=add_additional_incident
    )
    add_more_button.grid(row=0, column=0, padx=(0, 8))
    remove_last_button = tb.Button(
        incident_actions, text="Remove Last Incident Report",
        bootstyle="secondary-outline", command=remove_last_incident
    )
    remove_last_button.grid(row=0, column=1)
    incident_hint = tb.Label(incident_actions, text="", bootstyle="secondary")
    incident_hint.grid(row=0, column=2, padx=14, sticky="w")


    notebook.bind("<<NotebookTabChanged>>", on_tab_changed, add="+")


    # ---- the sections menu (left column) ----
    nav_buttons = []
    for _text, _tab in (
        ("General", general_tab), ("Documents & Goods", documents_tab),
        ("Item Lists", items_tab), ("Additional Details", findings_tab),
        (INCIDENT_TAB_TEXT.strip(), incident_tab),
        ("Weekly Summary", summary_tab),
    ):
        nav_buttons.append((_tab, tb.Button(
            nav_holder, text=_text, bootstyle="secondary-outline",
            padding=(12, 8), command=lambda t=_tab: notebook.select(t)
        )))


    refresh_nav()
    add_incident_card(copy_voyage=False, autofill=False)   # filled when shown


    # Control #s MySQL holds, as last seen (filled when the server answers).
    mysql_numbers = {"values": []}


    # record id -> (what happened, detail), for a save that asked to be told
    # at once (only when the sender runs inline, as in the automated tests)
    mysql_feedback = {}
    mysql_wait_state = {"busy": False}


    mysql_sender = fsr_mysql_sender.Sender(
        mysql_round, mysql_round_done,
        inline=os.environ.get("FSR_MYSQL_INLINE", "").strip() == "1")


    # ---------- PO_Master and Withdrawn_Item, also in the background ----------

    lists_feedback = {}         # record id -> exception or None (inline only)
    lists_state = {"warned": False}


    lists_sender = fsr_mysql_sender.Sender(
        lists_round, lists_round_done,
        inline=os.environ.get("FSR_MYSQL_INLINE", "").strip() == "1")


    unfinished_state = {"unreadable_shown": False}


    # =====================================================
    # MYSQL CONFLICTS  (a copy never overwrites what it does not own)
    # =====================================================

    conflict_state = {"dialog": None}


    import_state = {"running": False}


    for _key, _func in (("s", save_report),
                        ("n", show_inspection_then(new_report)),
                        ("o", show_inspection_then(open_saved_report_dialog)),
                        ("p", print_pdf_current_report)):
        window.bind(f"<Control-{_key}>", shortcut(_func))
        window.bind(f"<Control-{_key.upper()}>", shortcut(_func))

    window.protocol("WM_DELETE_WINDOW", on_close)

    update_item_list_buttons()

    # Start with a new report and its automatic Control #.
    new_report(confirm=False)

    # Saves that stopped halfway last time are finished now (this PC's files;
    # MySQL follows when the check below finds the server).
    window.after(300, finish_unfinished_saves)

    if "check_mysql_status" in globals():
        window.after(600, check_mysql_status)
    window.after(250, poll_mysql_sender)


    window.report_callback_exception = report_callback_exception


    app_shell = None
    if warehouse_ui is not None:
        from types import SimpleNamespace
        ui_context = SimpleNamespace(
            window=window, sidebar=sidebar, inspection_frame=body, log=log,
            log_file=LOG_FILE, user_name=USER_FULL_NAME, is_owner=IS_OWNER,
            role_label=ROLE_LABEL,
            owner_edition=IS_OWNER_EDITION, edition_label=fsr_edition.LABEL,
            demo_mode=DEMO_MODE, data_dir=DATA_DIR, db_mysql=db_mysql,
            master_data=master_data, save_master_lists=save_master_lists,
            excel_path=lambda: Path(excel_state["path"]),
            data_source=analytics_source, set_data_source=set_analytics_source,
            source_text=lambda: ("MySQL database" if analytics_source() == "mysql"
                                 else f"Excel - {Path(excel_state['path']).name}"),
            mysql_enabled=lambda: db_mysql is not None and db_mysql.is_enabled(),
            notify=notify, open_file=open_file,
            run_with_progress=run_with_progress, reports_folder=reports_folder,
            open_report=open_report_from_module, set_title=set_module_title,
            change_excel_file=change_excel_file, toggle_theme=toggle_theme,
            open_mysql_settings=open_mysql_settings,
            after_sample_change=after_sample_change,
        )
        try:
            app_shell = warehouse_ui.install(ui_context)
            app_shell.show("dashboard")
        except Exception:
            log.exception("The navigation could not be built")
            app_shell = None
            sidebar.pack_forget()

    window.deiconify()
    window.lift()


    window.after(600, tell_owner_about_requests)


def main():
    build_window()
    window.mainloop()


if __name__ == "__main__":
    main()

