"""
Indian number formatting.

Python/Plotly format numbers in the Western style by default (142,823,584).
Indian business reporting groups digits differently — the last 3 digits,
then groups of 2 after that (1,42,82,584) — and headline figures are
usually spoken in Lakhs (1,00,000) and Crores (1,00,00,000) rather than
millions/billions. These helpers convert to that convention everywhere
the dashboard shows a rupee figure.
"""

import pandas as pd


def format_inr(value, decimals: int = 0) -> str:
    """Full Indian-grouped currency string, e.g. 142823584 -> '₹14,28,23,584'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "₹0"
    value = float(value)
    sign = "-" if value < 0 else ""
    value = abs(value)

    s = f"{value:,.{decimals}f}"
    int_part, _, dec_part = s.partition(".")
    int_part = int_part.replace(",", "")

    if len(int_part) > 3:
        last3 = int_part[-3:]
        rest = int_part[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        formatted = ",".join(groups) + "," + last3
    else:
        formatted = int_part

    result = f"{sign}₹{formatted}"
    if decimals and dec_part:
        result += f".{dec_part}"
    return result


def format_inr_short(value) -> str:
    """Abbreviated Indian currency for headline KPIs, e.g. 142823584 -> '₹14.28 Cr'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "₹0"
    value = float(value)
    sign = "-" if value < 0 else ""
    value = abs(value)

    if value >= 1e7:
        return f"{sign}₹{value / 1e7:.2f} Cr"
    if value >= 1e5:
        return f"{sign}₹{value / 1e5:.2f} L"
    if value >= 1e3:
        return f"{sign}₹{value / 1e3:.1f} K"
    return f"{sign}₹{value:,.0f}"


def format_units_short(value) -> str:
    """Abbreviated plain-number formatting for unit counts (no currency symbol)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "0"
    value = float(value)
    if value >= 1e7:
        return f"{value / 1e7:.2f} Cr"
    if value >= 1e5:
        return f"{value / 1e5:.2f} L"
    if value >= 1e3:
        return f"{value / 1e3:.1f} K"
    return f"{value:,.0f}"
