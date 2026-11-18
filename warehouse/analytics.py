"""KPIs, summaries, trends and the management summary.

Rules kept everywhere:
  * reports (transactions), cargo lines, quantities and weights are
    separate figures - never added together;
  * quantities are totalled per unit of measure, never across units;
  * weights are totalled only for lines whose weight has a known unit;
  * a % change is shown only when the previous value is above zero;
  * nothing is estimated: a figure the records cannot support is shown as
    unavailable, with the reason.
"""

from collections import Counter, OrderedDict
from dataclasses import dataclass, field

from .inventory import (STATUS_FULL, STATUS_IN_STOCK, STATUS_OVER,
                        STATUS_PARTIAL, STATUS_RECON, TOLERANCE)
from .periods import (Period, auto_granularity, bucket_key, bucket_label,
                      buckets_between, day_period, month_period,
                      previous_period, week_period)
from .transactions import BAD_ORDER, GOOD_ORDER, RECEIVING, WITHDRAWAL, \
    norm_key


# ---------- formatting ----------

def fmt_number(value, decimals=2):
    if value is None:
        return "-"
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    return f"{value:,.{decimals}f}"


def fmt_units(by_unit, limit=None):
    """{'PCS': 120, 'SET': 3} -> '120 PCS · 3 SET' (never one total)."""
    if not by_unit:
        return "-"
    parts = [f"{fmt_number(qty)} {unit or '(no unit)'}"
             for unit, qty in sorted(by_unit.items(),
                                     key=lambda kv: (-kv[1], kv[0]))]
    if limit and len(parts) > limit:
        parts = parts[:limit] + [f"+{len(parts) - limit} more units"]
    return " · ".join(parts)


def fmt_kg(value):
    return "-" if value is None else f"{fmt_number(value)} kg"


def change_text(current, previous):
    """Comparison text, or '' when there is nothing to compare with."""
    if previous is None or current is None:
        return ""
    if previous == 0:
        if current == 0:
            return "No change (previous period: 0)"
        return "Previous period: 0 - % change not meaningful"
    pct = (current - previous) / previous * 100
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.1f}% vs previous ({fmt_number(previous)})"


def pct(part, whole):
    return None if not whole else part / whole * 100


# ---------- filters ----------

@dataclass
class Filters:
    period: Period | None = None
    warehouse: str = ""
    supplier: str = ""
    consignee: str = ""
    condition: str = ""             # Good Order / Bad Order
    activity: str = ""              # Receiving / Withdrawal
    cargo_type: str = ""            # a Types of Goods entry
    search: str = ""                # SO / Control # / Cargo ID / description

    def describe(self):
        parts = []
        for label, value in (("Warehouse", self.warehouse),
                             ("Supplier", self.supplier),
                             ("Consignee", self.consignee),
                             ("Condition", self.condition),
                             ("Transaction Type", self.activity),
                             ("Cargo Type", self.cargo_type),
                             ("Search", self.search)):
            if value:
                parts.append(f"{label}: {value}")
        return parts or ["None"]


def _match_text(value, wanted):
    return not wanted or norm_key(value) == norm_key(wanted)


def tx_matches(tx, filters, ignore_period=False):
    f = filters
    if not ignore_period and f.period is not None and \
            not (f.period.start is None or f.period.contains(tx.date)):
        return False
    if f.activity and tx.activity != f.activity:
        return False
    if not _match_text(tx.warehouse, f.warehouse):
        return False
    if not _match_text(tx.supplier, f.supplier):
        return False
    if not _match_text(tx.consignee, f.consignee):
        return False
    if f.condition and tx.condition != f.condition:
        return False
    if f.cargo_type and norm_key(f.cargo_type) not in norm_key(tx.goods_types):
        return False
    if f.search:
        text = " ".join([tx.control_no, tx.so_number, tx.po_number,
                         tx.dr_number, tx.gatepass_number, tx.bl_awb_number,
                         tx.supplier, tx.consignee]
                        + [f"{l.cargo_id} {l.receiving_ref} {l.description} "
                           f"{l.po_number}" for l in tx.lines]).casefold()
        if f.search.strip().casefold() not in text:
            return False
    return True


def filter_transactions(transactions, filters, ignore_period=False):
    return [tx for tx in transactions
            if tx_matches(tx, filters, ignore_period)]


def lines_of(transactions):
    return [line for tx in transactions for line in tx.lines]


def search_lines(lines, text):
    text = (text or "").strip().casefold()
    if not text:
        return list(lines)
    return [l for l in lines if text in " ".join(
        [l.control_no, l.so_number, l.cargo_id, l.receiving_ref,
         l.description, l.po_number, l.supplier, l.consignee]).casefold()]


def distinct_values(transactions, attr):
    values = {getattr(tx, attr) for tx in transactions if getattr(tx, attr)}
    return sorted(values, key=str.casefold)


def cargo_types(transactions):
    found = set()
    for tx in transactions:
        for part in tx.goods_types.split(";"):
            part = part.strip()
            if part:
                found.add("Others" if part.startswith("Others") else part)
    return sorted(found, key=str.casefold)


# ---------- quantities / weights ----------

def qty_by_unit(lines):
    totals = {}
    for line in lines:
        if line.quantity is not None:
            totals[line.unit] = totals.get(line.unit, 0) + line.quantity
    return totals


@dataclass
class WeightTotal:
    kg: float | None
    lines_with_weight: int
    lines_without: int

    def text(self):
        if self.lines_with_weight == 0:
            return "Unavailable (no weights with a unit)"
        text = fmt_kg(self.kg)
        if self.lines_without:
            text += f" ({self.lines_without} line(s) without usable weight)"
        return text


def weight_total(lines):
    known = [l.weight_kg for l in lines if l.weight_kg is not None]
    return WeightTotal(sum(known) if known else None, len(known),
                       len(lines) - len(known))


def unique_cargo(lines):
    """Distinct identifiable cargo items (Cargo ID, else Receiving Ref)."""
    keys = set()
    for line in lines:
        if line.cargo_id:
            keys.add((line.warehouse_key, "id:" + line.cargo_key))
        elif line.activity == RECEIVING and line.receiving_ref:
            keys.add((line.warehouse_key, "ref:" + line.ref_key))
    return len(keys)


# ---------- KPI cards ----------

@dataclass
class KPI:
    name: str
    value: object                   # number, or None when unavailable
    display: str
    unit: str = ""                  # what the number counts
    period: str = ""
    comparison: str = ""
    note: str = ""
    tone: str = "primary"           # primary / success / warning / danger


def count_kpi(name, current, previous, unit, period_label, tone="primary",
              note=""):
    return KPI(name, current, fmt_number(current), unit, period_label,
               change_text(current, previous), note, tone)


def inspection_kpis(transactions, filters):
    """The six inspection KPIs of the selected period (+ comparison)."""
    period = filters.period
    current = filter_transactions(transactions, filters)
    prev_period = previous_period(period) if period else None
    previous = None
    if prev_period is not None:
        previous = filter_transactions(
            transactions, Filters(**{**filters.__dict__,
                                     "period": prev_period}))
    label = period.describe() if period else "All Records"

    def counts(txs):
        if txs is None:
            return None
        bad = sum(1 for t in txs if t.condition == BAD_ORDER)
        return {"total": len(txs), "good": len(txs) - bad, "bad": bad,
                "rec": sum(1 for t in txs if t.activity == RECEIVING),
                "wdr": sum(1 for t in txs if t.activity == WITHDRAWAL)}

    c, p = counts(current), counts(previous)
    pv = (lambda key: p[key] if p else None)
    bad_pct = pct(c["bad"], c["total"])
    prev_pct = pct(p["bad"], p["total"]) if p else None
    bad_pct_kpi = KPI(
        "Bad Order Percentage", bad_pct,
        "-" if bad_pct is None else f"{bad_pct:.1f}%",
        "of inspection reports", label,
        "" if prev_pct is None or bad_pct is None else
        f"Previous period: {prev_pct:.1f}%",
        "No reports in this period" if bad_pct is None else "",
        "danger" if bad_pct else "primary")
    return [
        count_kpi("Total Inspection Reports", c["total"], pv("total"),
                  "reports", label),
        count_kpi("Good Order Reports", c["good"], pv("good"), "reports",
                  label, "success"),
        count_kpi("Bad Order Reports", c["bad"], pv("bad"), "reports",
                  label, "danger" if c["bad"] else "primary"),
        bad_pct_kpi,
        count_kpi("Receiving Transactions", c["rec"], pv("rec"),
                  "transactions (reports)", label),
        count_kpi("Withdrawal Transactions", c["wdr"], pv("wdr"),
                  "transactions (reports)", label),
    ]


def warehouse_kpis(transactions, inventory, filters):
    """Period figures (what happened in the period) and current balances
    (the ledger as of today) - labelled differently on purpose."""
    period = filters.period
    label = period.describe() if period else "All Records"
    balance_label = f"Current balance as of {inventory.as_of:%d-%b-%Y}"
    rec = filter_transactions(transactions, Filters(
        **{**filters.__dict__, "activity": RECEIVING}))
    wdr = filter_transactions(transactions, Filters(
        **{**filters.__dict__, "activity": WITHDRAWAL}))
    rec_lines, wdr_lines = lines_of(rec), lines_of(wdr)
    missing_rec = sum(1 for l in rec_lines if l.quantity is None)
    rec_qty = qty_by_unit(rec_lines)
    rec_total = sum(rec_qty.values()) if rec_qty else None
    declared = [t.packages for t in wdr if t.packages is not None]
    wdr_packages = sum(declared) if declared else None

    items = [i for i in inventory.items
             if _match_text(i.warehouse, filters.warehouse)]
    remaining = {}
    for item in items:
        if item.remaining_qty is not None and item.remaining_qty > TOLERANCE:
            remaining[item.unit] = remaining.get(item.unit, 0) \
                + item.remaining_qty
    recon = sum(1 for i in items if i.status == STATUS_RECON)
    over = sum(1 for i in items if i.status == STATUS_OVER)
    in_stock = sum(1 for i in items if i.remaining_qty is not None
                   and i.remaining_qty > TOLERANCE)
    unmatched = [u for u in inventory.unmatched if u.is_open
                 and _match_text(u.line.warehouse, filters.warehouse)]
    open_issues = [i for i in inventory.open_issues()
                   if i.severity == "error"
                   and (not filters.warehouse
                        or _match_text((i.line or i.item).warehouse,
                                       filters.warehouse))]

    def status_count(status):
        return sum(1 for i in items if i.status == status)

    remaining_note = []
    if recon:
        remaining_note.append(f"{recon} item(s) need reconciliation and "
                              "are not included")
    if over:
        remaining_note.append(f"{over} item(s) are over-withdrawn")
    return [
        KPI("Total Receiving Transactions", len(rec), fmt_number(len(rec)),
            f"transactions · {len(rec_lines)} cargo lines", label),
        KPI("Total Withdrawal Transactions", len(wdr), fmt_number(len(wdr)),
            f"transactions · {len(wdr_lines)} cargo lines", label),
        KPI("Total Quantity Received", rec_total, fmt_number(rec_total),
            "all units combined", label,
            note=(f"{missing_rec} line(s) without a quantity"
                  if missing_rec else "")),
        KPI("Total Packages Withdrawn", wdr_packages,
            fmt_number(wdr_packages), "from Declared Goods", label),
        KPI("Estimated Remaining Quantity", remaining or None,
            fmt_units(remaining, 3), "by unit · recorded, not verified",
            balance_label, note="; ".join(remaining_note)),
        KPI("Distinct Cargo Items in Stock", in_stock, fmt_number(in_stock),
            "items with a positive balance", balance_label),
        KPI("Partially Withdrawn Cargo Items", status_count(STATUS_PARTIAL),
            fmt_number(status_count(STATUS_PARTIAL)), "items", balance_label),
        KPI("Fully Withdrawn Cargo Items", status_count(STATUS_FULL),
            fmt_number(status_count(STATUS_FULL)), "items", balance_label),
        KPI("Cargo with No Recorded Withdrawal",
            status_count(STATUS_IN_STOCK),
            fmt_number(status_count(STATUS_IN_STOCK)), "items",
            balance_label, note="Physical presence is not verified"),
        KPI("Unmatched Withdrawal Transactions", len(unmatched),
            fmt_number(len(unmatched)), "withdrawal lines", balance_label,
            tone="warning" if unmatched else "success"),
        KPI("Inventory Reconciliation Issues", len(open_issues),
            fmt_number(len(open_issues)), "open issues", balance_label,
            tone="danger" if open_issues else "success"),
    ]


# ---------- summaries ----------

@dataclass
class Summary:
    activity: str
    period: Period
    transactions: list
    lines: list
    qty: dict
    weight: WeightTotal
    unique_items: int
    by_day: OrderedDict
    by_week: OrderedDict
    by_warehouse: list              # (warehouse, transactions, lines)
    by_supplier: list
    by_consignee: list
    by_destination: list
    by_condition: dict
    by_cargo_type: list
    previous: "Summary | None" = None

    @property
    def tx_count(self):
        return len(self.transactions)

    @property
    def line_count(self):
        return len(self.lines)

    @property
    def packages(self):
        """Declared Goods packages; None when no transaction declares any."""
        counts = [t.packages for t in self.transactions
                  if t.packages is not None]
        return sum(counts) if counts else None


def _grouped(transactions, attr):
    tx_count, line_count = Counter(), Counter()
    for tx in transactions:
        key = getattr(tx, attr) or "(not recorded)"
        tx_count[key] += 1
        line_count[key] += tx.line_count
    return [(k, tx_count[k], line_count[k])
            for k in sorted(tx_count, key=lambda k: (-tx_count[k], k))]


def summarize(transactions, activity, period, filters=None,
              with_previous=True):
    """Receiving or Withdrawal activity of one period."""
    filters = filters or Filters()
    chosen = filter_transactions(transactions, Filters(
        **{**filters.__dict__, "period": period, "activity": activity}))
    lines = lines_of(chosen)
    by_day = OrderedDict((d, 0) for d in buckets_between(
        period.start, period.end, "day")) if period.start else OrderedDict()
    by_week = OrderedDict((d, 0) for d in buckets_between(
        period.start, period.end, "week")) if period.start else OrderedDict()
    for tx in chosen:
        if tx.date is None:
            continue
        by_day[tx.date] = by_day.get(tx.date, 0) + 1
        week = bucket_key(tx.date, "week")
        by_week[week] = by_week.get(week, 0) + 1
    cargo_type = Counter()
    for tx in chosen:
        for part in (tx.goods_types.split(";") if tx.goods_types
                     else ["(not recorded)"]):
            part = part.strip()
            cargo_type["Others" if part.startswith("Others") else part] += 1
    summary = Summary(
        activity=activity, period=period, transactions=chosen, lines=lines,
        qty=qty_by_unit(lines), weight=weight_total(lines),
        unique_items=unique_cargo(lines), by_day=by_day, by_week=by_week,
        by_warehouse=_grouped(chosen, "warehouse"),
        by_supplier=_grouped(chosen, "supplier"),
        by_consignee=_grouped(chosen, "consignee"),
        by_destination=_grouped(chosen, "destination"),
        by_condition={GOOD_ORDER: sum(1 for t in chosen
                                      if t.condition == GOOD_ORDER),
                      BAD_ORDER: sum(1 for t in chosen
                                     if t.condition == BAD_ORDER)},
        by_cargo_type=cargo_type.most_common(),
    )
    if with_previous:
        prev = previous_period(period)
        if prev is not None:
            summary.previous = summarize(transactions, activity, prev,
                                         filters, with_previous=False)
    return summary


def daily_summary(transactions, activity, day, filters=None):
    return summarize(transactions, activity, day_period(day), filters)


def weekly_summary(transactions, activity, day, filters=None):
    return summarize(transactions, activity, week_period(day), filters)


def monthly_summary(transactions, activity, day, filters=None):
    return summarize(transactions, activity, month_period(day), filters)


def comparison_rows(summary):
    """(measure, this period, previous period, change) for the summaries."""
    prev = summary.previous
    rows = [("Transactions", summary.tx_count,
             prev.tx_count if prev else None)]
    if summary.activity == WITHDRAWAL:
        rows.append(("Packages", summary.packages,
                     prev.packages if prev else None))
    else:
        rows.append(("Quantity", sum(summary.qty.values()),
                     sum(prev.qty.values()) if prev else None))
    return [(name, fmt_number(cur) if cur is not None else "-",
             fmt_number(p) if p is not None else "-",
             change_text(cur, p) if cur is not None else "")
            for name, cur, p in rows]


# ---------- trends ----------

def data_span(transactions):
    days = [t.date for t in transactions if t.date]
    return (min(days), max(days)) if days else (None, None)


def trend(transactions, period, granularity=None, activity=None,
          condition=None, filters=None):
    """[(bucket label, transactions)] over the period - empty buckets as 0."""
    filters = filters or Filters()
    chosen = filter_transactions(transactions, Filters(
        **{**filters.__dict__, "period": period,
           "activity": activity or filters.activity,
           "condition": condition or filters.condition}))
    start, end = period.start, period.end
    if start is None:
        start, end = data_span(chosen)
    granularity = granularity or auto_granularity(
        Period(start, end, "custom", "") if start else period)
    counts = OrderedDict((k, 0) for k in buckets_between(start, end,
                                                         granularity))
    for tx in chosen:
        if tx.date is None:
            continue
        key = bucket_key(tx.date, granularity)
        counts[key] = counts.get(key, 0) + 1
    return [(bucket_label(k, granularity), v) for k, v in counts.items()], \
        granularity


def quantity_trend(transactions, period, activity, unit, granularity,
                   filters=None):
    filters = filters or Filters()
    chosen = filter_transactions(transactions, Filters(
        **{**filters.__dict__, "period": period, "activity": activity}))
    start, end = period.start, period.end
    if start is None:
        start, end = data_span(chosen)
    counts = OrderedDict((k, 0.0) for k in buckets_between(start, end,
                                                           granularity))
    for line in lines_of(chosen):
        if line.date and line.quantity is not None and line.unit == unit:
            key = bucket_key(line.date, granularity)
            counts[key] = counts.get(key, 0) + line.quantity
    return [(bucket_label(k, granularity), v) for k, v in counts.items()]


# ---------- Bad Order ----------

def bad_order_kpis(transactions, filters, case_statuses):
    """Bad Order figures of the filtered reports. Unresolved cases are
    counted only from recorded case statuses."""
    from .store import UNRESOLVED_CASE_STATUSES
    base = filter_transactions(transactions, Filters(
        **{**filters.__dict__, "condition": ""}))
    bad = [t for t in base if t.condition == BAD_ORDER]
    label = filters.period.describe() if filters.period else "All Records"
    recorded = [t for t in bad if t.control_no in case_statuses]
    unresolved = [t for t in recorded
                  if case_statuses[t.control_no]["status"]
                  in UNRESOLVED_CASE_STATUSES]
    share = pct(len(bad), len(base))
    return [
        KPI("Total Bad Order Reports", len(bad), fmt_number(len(bad)),
            "reports", label, tone="danger" if bad else "success"),
        KPI("Bad Order Receiving Transactions",
            sum(1 for t in bad if t.activity == RECEIVING),
            fmt_number(sum(1 for t in bad if t.activity == RECEIVING)),
            "transactions", label),
        KPI("Bad Order Withdrawal Transactions",
            sum(1 for t in bad if t.activity == WITHDRAWAL),
            fmt_number(sum(1 for t in bad if t.activity == WITHDRAWAL)),
            "transactions", label),
        KPI("Bad Order Percentage", share,
            "-" if share is None else f"{share:.1f}%",
            f"of {len(base)} inspection reports", label),
        KPI("Affected Cargo Lines", sum(t.line_count for t in bad),
            fmt_number(sum(t.line_count for t in bad)),
            "cargo lines on Bad Order reports", label),
        KPI("Unresolved Bad Order Cases",
            len(unresolved) if recorded else None,
            fmt_number(len(unresolved)) if recorded else "Not tracked",
            f"of {len(recorded)} case(s) with a recorded status", label,
            note=("" if recorded else
                  "No case status recorded yet - set one in the table"),
            tone="warning" if unresolved else "primary"),
    ]


def good_vs_bad(transactions, filters):
    base = filter_transactions(transactions, Filters(
        **{**filters.__dict__, "condition": ""}))
    return {GOOD_ORDER: sum(1 for t in base if t.condition == GOOD_ORDER),
            BAD_ORDER: sum(1 for t in base if t.condition == BAD_ORDER)}


def activity_kpis(transactions, previous=None, period_label=""):
    """The three cards of the Receiving / Withdrawal pages, as on the phone's
    Dashboard: Total Transactions (reports), Total Packages (the Declared
    Goods quantities added up) and Items Inspected (the Item List quantities
    added up, every unit together). previous: the period before (None: no
    comparison)."""
    def figures(txs):
        if txs is None:
            return None
        declared = [t.packages for t in txs if t.packages is not None]
        qty = qty_by_unit(lines_of(txs))
        return (len(txs), sum(declared) if declared else None,
                sum(qty.values()) if qty else None)

    now, before = figures(transactions), figures(previous)
    cards = (("Total Transactions", "transactions (reports)"),
             ("Total Packages", "from the Declared Goods quantities"),
             ("Items Inspected", "Item List quantities, all units"))
    return [KPI(name, now[i], fmt_number(now[i]), unit, period_label,
                change_text(now[i], before[i] if before else None))
            for i, (name, unit) in enumerate(cards)]


def bad_order_by_month(transactions):
    """[(first day of the month or None, [transactions])], the latest month
    first; a transaction without a date goes last ('No date')."""
    months = {}
    for tx in transactions:
        key = tx.date.replace(day=1) if tx.date else None
        months.setdefault(key, []).append(tx)
    dated = sorted((k for k in months if k is not None), reverse=True)
    result = [(k, sorted(months[k], key=lambda t: (t.date, t.control_no),
                         reverse=True)) for k in dated]
    if None in months:
        result.append((None, months[None]))
    return result


def bad_order_breakdowns(transactions, filters):
    bad = filter_transactions(transactions, Filters(
        **{**filters.__dict__, "condition": BAD_ORDER}))
    by_warehouse = Counter(t.warehouse for t in bad)
    by_type = Counter()
    for tx in bad:
        for part in (tx.goods_types.split(";") if tx.goods_types
                     else ["(not recorded)"]):
            part = part.strip()
            by_type["Others" if part.startswith("Others") else part] += 1
    by_activity = Counter(t.activity or "(not recorded)" for t in bad)
    return {"warehouse": by_warehouse.most_common(),
            "cargo_type": by_type.most_common(),
            "activity": by_activity.most_common()}


# ---------- management summary ----------

@dataclass
class ManagementSummary:
    period: Period
    statements: list = field(default_factory=list)  # (topic, text)
    receiving: Summary | None = None
    withdrawal: Summary | None = None


def management_summary(transactions, inventory, filters, case_statuses):
    period = filters.period
    rec = summarize(transactions, RECEIVING, period, filters)
    wdr = summarize(transactions, WITHDRAWAL, period, filters)
    result = ManagementSummary(period, receiving=rec, withdrawal=wdr)
    say = result.statements.append

    for name, summary in (("Receiving Activity", rec),
                          ("Withdrawal Activity", wdr)):
        text = (f"{summary.tx_count} transaction(s) with "
                f"{summary.line_count} cargo line(s)")
        if summary.qty:
            text += f"; quantity {fmt_units(summary.qty)}"
        if summary.weight.lines_with_weight:
            text += f"; weight {summary.weight.text()}"
        if summary.previous is not None:
            change = change_text(summary.tx_count,
                                 summary.previous.tx_count)
            if change:
                text += f". Transactions: {change}"
        say((name, text + "."))

    bad = bad_order_kpis(transactions, filters, case_statuses)
    total_bad, share = bad[0].value, bad[3]
    if share.value is None:
        say(("Bad Order Summary", "No inspection reports in this period."))
    else:
        text = (f"{total_bad} Bad Order report(s) - {share.display} of the "
                "inspection reports")
        if bad[5].value is not None:
            text += f"; {bad[5].display} unresolved case(s) recorded"
        say(("Bad Order Summary", text + "."))

    counts = inventory.status_counts()
    remaining = inventory.remaining_items()
    by_unit = {}
    for item in remaining:
        by_unit[item.unit] = by_unit.get(item.unit, 0) + item.remaining_qty
    say(("Remaining Warehouse Cargo",
         f"{len(remaining)} item(s) with a positive recorded balance "
         f"({fmt_units(by_unit)}) as of {inventory.as_of:%d-%b-%Y}: "
         f"{counts[STATUS_IN_STOCK]} with no recorded withdrawal, "
         f"{counts[STATUS_PARTIAL]} partially withdrawn. "
         f"{counts[STATUS_FULL]} fully withdrawn. Balances are from the "
         "records and are not physically verified."))
    buckets = inventory.aging_buckets()
    oldest = list(buckets)[-1]
    say(("Inventory Aging",
         "; ".join(f"{label}: {n} batch(es)"
                   for label, (n, _) in buckets.items())
         + (f". {buckets[oldest][0]} batch(es) are older than "
            f"{inventory.thresholds[-1]} days." if buckets[oldest][0]
            else ".")))
    unmatched = [u for u in inventory.unmatched if u.is_open]
    say(("Unmatched Transactions",
         f"{len(unmatched)} withdrawal line(s) could not be linked to a "
         "received item." if unmatched else
         "Every withdrawal line is linked to a received item."))
    issues = [i for i in inventory.open_issues() if i.severity == "error"]
    say(("Reconciliation Issues",
         f"{len(issues)} open issue(s); {counts[STATUS_RECON]} item(s) have "
         f"no established balance and {counts[STATUS_OVER]} are "
         "over-withdrawn." if issues else "No open reconciliation issues."))
    return result
