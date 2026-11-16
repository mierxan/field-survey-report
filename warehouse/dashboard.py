"""The Dashboard sheet of the Weekly / Monthly Receiving and Withdrawal
Excel reports: KPI cards and charts, from the same summary the Receiving
and Withdrawal screens show (analytics.summarize). This module only
decides WHAT the dashboard shows; exports.write_dashboard lays it out.

The phone app makes the same dashboard for its own Weekly Summary
(DashboardSheet.kt there).
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime

from . import analytics as an
from .periods import bucket_key, bucket_label
from .transactions import BAD_ORDER, GOOD_ORDER, RECEIVING

TOP_PARTIES = 8             # the rest are added up as "Others"
NOT_RECORDED = "(not recorded)"

# card / chart colours (also used by the phone app)
BLUE = "2563EB"
TEAL = "0D9488"
AMBER = "D97706"
GREEN = "16A34A"
RED = "DC2626"
PURPLE = "7C3AED"
SLATE = "475569"


@dataclass
class Card:
    label: str
    value: str
    note: str = ""
    change: str = ""            # "+6.2% vs previous (16)"; "" = none
    trend: int = 0              # 1 up, -1 down, 0 same / unknown
    color: str = BLUE


@dataclass
class Chart:
    kind: str                   # column, bar (horizontal), doughnut
    title: str
    labels: list
    values: list
    color: str = BLUE
    colors: list = field(default_factory=list)   # doughnut: per slice
    axis_title: str = ""

    @property
    def empty(self):
        return not any(v for v in self.values)


@dataclass
class Dashboard:
    title: str                  # "Weekly Receiving Dashboard"
    period: str                 # "Week 45, 2026 (02-Nov-2026 to ...)"
    site: str                   # the location(s) of the reports
    activity: str
    cards: list
    charts: list
    comparison: list            # (measure, this period, previous, change)
    previous_label: str = ""
    generated: datetime = field(default_factory=datetime.now)


def _change(current, previous):
    """('+6.2% vs previous (16)', trend) or ('', 0)."""
    if current is None or previous is None:
        return "", 0
    text = an.change_text(current, previous)
    trend = (current > previous) - (current < previous)
    return text, trend


def site_text(summary):
    names = [name for name, *_ in summary.by_warehouse
             if name and name != NOT_RECORDED]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return f"{len(names)} sites: " + ", ".join(names[:4]) + (
        ", ..." if len(names) > 4 else "")


def _top(groups, limit=TOP_PARTIES):
    groups = [(name or NOT_RECORDED, count) for name, count, *_ in groups]
    if len(groups) <= limit:
        return groups
    rest = groups[limit - 1:]
    return groups[:limit - 1] + [(f"Others ({len(rest)})",
                                  sum(count for _, count in rest))]


def _per_bucket(summary, granularity, measure):
    """{bucket start: amount} of every bucket of the period (zeros kept)."""
    source = summary.by_day if granularity == "day" else summary.by_week
    totals = OrderedDict((key, 0) for key in source)
    if measure == "transactions":
        for key, count in source.items():
            totals[key] = count
        return totals
    if measure == "quantity":
        for line in summary.lines:
            if line.date is not None and line.quantity is not None:
                key = bucket_key(line.date, granularity)
                totals[key] = totals.get(key, 0) + line.quantity
    else:                                       # lines
        for line in summary.lines:
            if line.date is not None:
                key = bucket_key(line.date, granularity)
                totals[key] = totals.get(key, 0) + 1
    return totals


def _number(value):
    if value is None:
        return 0
    return int(value) if float(value).is_integer() else round(value, 2)


def cards_of(summary):
    prev = summary.previous
    receiving = summary.activity == RECEIVING
    good = summary.by_condition.get(GOOD_ORDER, 0)
    bad = summary.by_condition.get(BAD_ORDER, 0)
    change, trend = _change(summary.tx_count,
                            prev.tx_count if prev else None)
    cards = [Card("Transactions", an.fmt_number(summary.tx_count),
                  "inspection reports", change, trend, BLUE)]
    if receiving:
        total = sum(summary.qty.values()) if summary.qty else None
        before = sum(prev.qty.values()) if prev and prev.qty else (
            0 if prev else None)
        change, trend = _change(total or 0, before) if total is not None \
            else ("", 0)
        cards.append(Card("Total Quantity Received",
                          an.fmt_number(total) if total is not None else "-",
                          "all units combined", change, trend, TEAL))
    else:
        change, trend = _change(summary.line_count,
                                prev.line_count if prev else None)
        cards.append(Card("Cargo Lines Withdrawn",
                          an.fmt_number(summary.line_count),
                          "Item List lines", change, trend, TEAL))
    packages = summary.packages
    change, trend = _change(packages, prev.packages if prev else None)
    cards.append(Card("Total Packages",
                      an.fmt_number(packages) if packages is not None
                      else "-", "from Declared Goods", change, trend, AMBER))
    share = an.pct(good, good + bad)
    cards.append(Card(
        "Good / Bad Order", f"{good} Good · {bad} Bad",
        f"{share:.0f}% Good Order" if share is not None
        else "no condition recorded", "", 0, RED if bad else GREEN))
    return cards


def build(summary, kind):
    """The dashboard of a weekly ("weekly") or monthly ("monthly")
    summary (analytics.Summary)."""
    receiving = summary.activity == RECEIVING
    name = "Weekly" if kind == "weekly" else "Monthly"
    charts = []
    if kind == "weekly":
        per_day = _per_bucket(summary, "day", "transactions")
        charts.append(Chart(
            "column", "Transactions per Day",
            [bucket_label(d, "day") for d in per_day], list(per_day.values()),
            BLUE, axis_title="Transactions"))
    else:
        per_week = _per_bucket(summary, "week", "transactions")
        charts.append(Chart(
            "column", "Transactions per Week",
            [bucket_label(d, "week") for d in per_week],
            list(per_week.values()), BLUE, axis_title="Transactions"))
    good = summary.by_condition.get(GOOD_ORDER, 0)
    bad = summary.by_condition.get(BAD_ORDER, 0)
    charts.append(Chart("doughnut", "Good Order / Bad Order",
                        ["Good Order", "Bad Order"], [good, bad],
                        colors=[GREEN, RED]))
    # the second card's measure, per day / week
    measure = "quantity" if receiving else "lines"
    measure_title = ("Quantity Received" if receiving
                     else "Cargo Lines Withdrawn")
    granularity = "day" if kind == "weekly" else "week"
    amounts = _per_bucket(summary, granularity, measure)
    charts.append(Chart(
        "column",
        f"{measure_title} per {'Day' if kind == 'weekly' else 'Week'}",
        [bucket_label(d, granularity) for d in amounts], [_number(v) for v in amounts.values()],
        TEAL, axis_title="Quantity" if receiving else "Cargo lines"))
    party = "Supplier" if receiving else "Consignee"
    parties = _top(summary.by_supplier if receiving
                   else summary.by_consignee)
    charts.append(Chart(
        "bar", f"Top {party}s (transactions)",
        [p for p, _ in parties], [c for _, c in parties], PURPLE))
    if kind == "monthly":
        per_day = _per_bucket(summary, "day", "transactions")
        charts.append(Chart(
            "column", "Transactions per Day",
            [bucket_label(d, "day") for d in per_day], list(per_day.values()),
            BLUE, axis_title="Transactions"))
    sites = _top(summary.by_warehouse)
    charts.append(Chart("bar", "Transactions per Site / Warehouse",
                        [s for s, _ in sites], [c for _, c in sites],
                        SLATE))
    prev = summary.previous
    return Dashboard(
        title=f"{name} {summary.activity} Dashboard",
        period=summary.period.describe(), site=site_text(summary),
        activity=summary.activity, cards=cards_of(summary), charts=charts,
        comparison=an.comparison_rows(summary),
        previous_label=prev.period.describe() if prev else "")
