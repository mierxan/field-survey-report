"""A price with no currency, caught when the report is saved.

The Summary report adds up the Total Price per currency (TOTAL PHP, TOTAL
USD, ...), so a price without a currency cannot be added to any of them;
the form asks before saving it. Plain functions only (no window)."""
import re

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


def needs_currency(currency, unit_price, total_price):
    """True when a line has a price but no currency: no Currency chosen and
    no code typed with the price ('usd 100' carries its own)."""
    if str(currency or "").strip():
        return False
    for text in (total_price, unit_price):
        amount, code = parse_money(text)
        if amount is not None:
            return not code
    return False


def missing_currency_text(places):
    """places: [(item list title, [line numbers])] -> the warning text."""
    lines = []
    for title, numbers in places:
        word = "line" if len(numbers) == 1 else "lines"
        lines.append(f"{title}: {word} " + ", ".join(map(str, numbers)))
    return ("These lines have a price but no Currency:\n\n  "
            + "\n  ".join(lines)
            + "\n\nWithout a Currency the price cannot be added to the "
            "totals of the Summary report. Choose the Currency (PHP, USD, "
            "...) on each line.\n\nSave anyway?")
