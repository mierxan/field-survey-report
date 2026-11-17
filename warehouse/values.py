"""Cargo value in Philippine pesos (PHP) for the Owner's Dashboard: the top
suppliers by the total value of what they delivered (Receiving reports only).

A line's value is its Total Price, or Unit Price x Quantity when the Total
Price is empty, in the line's Currency. Other currencies are converted with
the rates the owner enters (1 USD = n PHP ...), kept with the warehouse
settings. Nothing is guessed: a line in a currency without a rate, or with
a price but no currency, is left out and counted in the note under the chart.
"""
import re
from dataclasses import dataclass, field

from . import analytics as an
from .transactions import RECEIVING

HOME = "PHP"
NOT_RECORDED = "(not recorded)"
TOP = 10

# "usd 1,250.50", "PHP 16,000.-", "₱ 500", "1,000 jpy"
_AMOUNT = r"(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:\.?-+)?"
_MONEY = re.compile(
    rf"^\s*(?:([A-Za-z]{{3}}|₱)\.?\s*)?{_AMOUNT}\s*([A-Za-z]{{3}})?\s*$")
_SYMBOLS = {"₱": "PHP"}


def currency_code(text):
    """'usd ' -> 'USD'; '₱' -> 'PHP'; '' -> ''."""
    text = str(text or "").strip()
    return _SYMBOLS.get(text, text.upper())


def parse_money(text):
    """'1,250.50' -> (1250.5, ''); 'jpy 4,000.-' -> (4000.0, 'JPY');
    anything else -> (None, '')."""
    match = _MONEY.match(str(text or ""))
    if not match:
        return None, ""
    code = currency_code(match.group(1) or match.group(3) or "")
    return float(match.group(2).replace(",", "")), code


def line_value(line):
    """(amount, currency) of one cargo line; amount None when it has no
    price. The Currency column wins over a code typed with the price."""
    total, code = parse_money(line.total_price)
    if total is None:
        unit, code = parse_money(line.unit_price)
        if unit is None or line.quantity is None:
            return None, ""
        total = unit * line.quantity
    return total, currency_code(line.currency) or code


def to_php(amount, currency, rates):
    """The amount in PHP, or None when there is no rate for the currency."""
    if currency == HOME:
        return amount
    rate = rates.get(currency)
    return amount * rate if rate else None


@dataclass
class SupplierValues:
    """rows: [(supplier, value in PHP, Receiving reports)], biggest first.
    The counts are of cargo lines left out of the totals."""
    rows: list = field(default_factory=list)
    priced_lines: int = 0
    no_rate: dict = field(default_factory=dict)      # currency -> lines
    no_currency: int = 0
    unpriced: int = 0

    def note(self):
        parts = [f"{self.priced_lines:,} priced cargo line(s) counted."]
        if self.no_rate:
            parts.append("Left out, no rate to PHP: " + ", ".join(
                f"{code} ({count} line{'s' if count > 1 else ''})"
                for code, count in sorted(self.no_rate.items()))
                + " - set it with Exchange Rates to PHP.")
        if self.no_currency:
            parts.append(f"Left out, a price but no currency: "
                         f"{self.no_currency} line(s).")
        if self.unpriced:
            parts.append(f"No price: {self.unpriced} line(s).")
        return "  ".join(parts)


def top_suppliers_by_value(transactions, filters, rates, limit=TOP):
    """The `limit` suppliers with the highest total value in PHP, from the
    Receiving reports that match `filters` (period, warehouse ...)."""
    rates = {currency_code(k): float(v) for k, v in (rates or {}).items()
             if v}
    result = SupplierValues()
    totals, reports = {}, {}
    for tx in an.filter_transactions(transactions, filters):
        if tx.activity != RECEIVING:
            continue
        name = tx.supplier or NOT_RECORDED
        for line in tx.lines:
            amount, currency = line_value(line)
            if amount is None:
                result.unpriced += 1
                continue
            if not currency:
                result.no_currency += 1
                continue
            php = to_php(amount, currency, rates)
            if php is None:
                result.no_rate[currency] = result.no_rate.get(currency, 0) + 1
                continue
            result.priced_lines += 1
            totals[name] = totals.get(name, 0.0) + php
            reports.setdefault(name, set()).add(tx.control_no)
    ranked = sorted(totals.items(),
                    key=lambda kv: (-kv[1], kv[0].casefold()))[:limit]
    result.rows = [(name, value, len(reports[name])) for name, value in ranked]
    return result


def currencies_in(transactions):
    """The currencies (other than PHP) used on Receiving lines, sorted."""
    found = set()
    for tx in transactions:
        if tx.activity != RECEIVING:
            continue
        for line in tx.lines:
            amount, code = line_value(line)
            if amount is not None and code and code != HOME:
                found.add(code)
    return sorted(found)


def fmt_php(value):
    """Whole pesos: 'PHP 1,234,568'."""
    return f"PHP {value:,.0f}"


def rates_text(rates):
    """'1 JPY = 0.38 PHP  ·  1 USD = 58.5 PHP' (or that none are set)."""
    if not rates:
        return "No exchange rates set: only PHP prices are counted."
    return "  ·  ".join(f"1 {code} = {rate:,.4f}".rstrip("0").rstrip(".")
                        + " PHP" for code, rate in sorted(rates.items()))
