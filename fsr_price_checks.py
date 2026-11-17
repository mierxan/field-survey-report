"""A price with no currency, caught when the report is saved.

Such a line cannot be counted in the value reports (the Owner's Top 10
Suppliers by Total Value), so the form asks before saving it. Plain
functions only (no window)."""


def needs_currency(currency, unit_price, total_price):
    """True when a line has a price but no currency: no Currency chosen and
    no code typed with the price ('usd 100' carries its own)."""
    if str(currency or "").strip():
        return False
    from warehouse.values import parse_money
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
            + "\n\nWithout a Currency the price cannot be counted in the "
            "value reports. Choose the Currency (PHP, USD, ...) on each "
            "line.\n\nSave anyway?")
