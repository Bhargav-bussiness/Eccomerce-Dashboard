"""
Turns each channel's messy raw dump tab(s) into one common schema so they
can be combined, charted, and compared:

    date | channel | brand | product | sku | units | revenue

Every function here is defensive: if an expected column is missing (a tab
got renamed, a month's dump has slightly different headers), it skips that
piece rather than crashing the whole app, and reports the issue back so it
shows up in the UI instead of failing silently.
"""

import pandas as pd
import streamlit as st

from config import CHANNELS, COLUMN_MAP, AD_COLUMN_MAP, MASTER_SHEET
from sheets_connector import load_tab

STANDARD_COLS = ["date", "channel", "brand", "product", "sku", "units", "revenue"]

# Any parsed date outside this window is treated as bad data (typo, blank row,
# stray header text, a serial-number glitch, etc.) rather than a real order date.
MIN_VALID_DATE = pd.Timestamp("2015-01-01")
MAX_VALID_DATE = pd.Timestamp("2035-12-31")


import re

SHEETS_EPOCH = pd.Timestamp("1899-12-30")  # Google Sheets / Excel serial-date epoch
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}")  # YYYY-MM-DD... is never ambiguous


def _parse_one_date(value):
    """Parse a single cell that may be a Sheets serial number, a date object,
    a text date, or blank."""
    try:
        if pd.isna(value):
            return pd.NaT
    except (TypeError, ValueError):
        pass  # value wasn't a type pd.isna can evaluate — fall through
    if isinstance(value, str) and value.strip() == "":
        return pd.NaT
    if isinstance(value, bool):
        return pd.NaT
    if isinstance(value, (int, float)):
        # Serial day-count from Google Sheets — unambiguous, no day/month guessing.
        try:
            return SHEETS_EPOCH + pd.to_timedelta(float(value), unit="D")
        except (ValueError, OverflowError):
            return pd.NaT
    text = str(value).strip()
    if _ISO_DATE_RE.match(text):
        # Already YYYY-MM-DD — unambiguous, so dayfirst must NOT be applied
        # here (dayfirst=True incorrectly swaps month/day even on ISO strings).
        return pd.to_datetime(text, errors="coerce")

    # Genuinely ambiguous text date (e.g. "08-12-2026"). Try both readings —
    # day-first (Indian convention, our default assumption) and month-first
    # (US convention, in case that's how it was actually typed) — and if
    # exactly one of them is a plausible non-future date while the other
    # isn't, trust that one. A sales order dated in the future is never
    # correct, so this self-corrects cases where the default guess was wrong,
    # instead of always assuming one convention no matter what.
    dayfirst_guess = pd.to_datetime(text, errors="coerce", dayfirst=True)
    monthfirst_guess = pd.to_datetime(text, errors="coerce", dayfirst=False)
    today = pd.Timestamp.now().normalize()
    if pd.notna(dayfirst_guess) and pd.notna(monthfirst_guess) and dayfirst_guess != monthfirst_guess:
        dayfirst_ok = dayfirst_guess <= today
        monthfirst_ok = monthfirst_guess <= today
        if dayfirst_ok and not monthfirst_ok:
            return dayfirst_guess
        if monthfirst_ok and not dayfirst_ok:
            return monthfirst_guess
    return dayfirst_guess if pd.notna(dayfirst_guess) else monthfirst_guess


def _safe_parse_dates(series: pd.Series) -> pd.Series:
    """
    Parse a column to datetimes and guarantee the result is plain
    datetime64[ns] with anything garbage or out-of-range turned into NaT.

    This exists because live Google Sheets occasionally contain a stray
    value in a date column (bad manual entry, a leftover label, a serial
    number) that `errors="coerce"` alone doesn't neutralize early enough —
    pandas can end up representing it in a non-nanosecond resolution, which
    then blows up later with OutOfBoundsDatetime when this channel's data
    is concatenated with another channel's. It also resolves day/month
    ambiguity by preferring Sheets' serial-number representation over
    guessing at a formatted string (see _parse_one_date).
    """
    parsed = series.apply(_parse_one_date)
    parsed = pd.to_datetime(parsed, errors="coerce")
    # Drop anything outside a sane business-data window BEFORE forcing to ns,
    # so we never try to downcast an out-of-range value.
    in_range = parsed.notna() & (parsed >= MIN_VALID_DATE) & (parsed <= MAX_VALID_DATE)
    parsed = parsed.where(in_range, pd.NaT)
    # Now safe to force a single consistent resolution across all channels.
    return parsed.astype("datetime64[ns]")


def _standardize_one(df: pd.DataFrame, channel: str) -> tuple[pd.DataFrame, str | None]:
    if df.empty:
        return pd.DataFrame(columns=STANDARD_COLS), None

    cmap = COLUMN_MAP.get(channel, {})

    exclusion_note = None
    status_col = cmap.get("status_col")
    excluded_statuses = cmap.get("excluded_statuses")
    if status_col and excluded_statuses and status_col in df.columns:
        is_excluded = df[status_col].astype(str).str.strip().isin(excluded_statuses)
        if is_excluded.any():
            n_excluded = int(is_excluded.sum())
            exclusion_note = (
                f"{channel}: excluded {n_excluded} row(s) with {status_col} in "
                f"{excluded_statuses} (cancelled/invalid orders) from revenue and units."
            )
            df = df[~is_excluded]

    out = pd.DataFrame(index=df.index)

    # date
    date_col = cmap.get("date")
    out["date"] = _safe_parse_dates(df[date_col]) if date_col in df.columns else pd.NaT

    # brand / product / sku (best-effort — used for breakdown tables)
    for field in ("brand", "product", "sku"):
        col = cmap.get(field)
        out[field] = df[col] if col in df.columns else None

    # units
    units_col = cmap.get("units")
    if units_col is None:
        out["units"] = 1  # e.g. Myntra: one row = one unit
    elif units_col in df.columns:
        out["units"] = pd.to_numeric(df[units_col], errors="coerce")
    else:
        out["units"] = 0

    # revenue — either a direct column, a list of fallback candidates, or computed
    rev_col = cmap.get("revenue")
    rev_candidates = cmap.get("revenue_candidates")
    if rev_candidates:
        chosen = next((c for c in rev_candidates if c in df.columns), None)
        out["revenue"] = pd.to_numeric(df[chosen], errors="coerce") if chosen else 0
    elif rev_col is not None and rev_col in df.columns:
        out["revenue"] = pd.to_numeric(df[rev_col], errors="coerce")
    elif channel == "Nykaa" and {"Total Qty", "Selling Price"}.issubset(df.columns):
        out["revenue"] = pd.to_numeric(df["Total Qty"], errors="coerce") * pd.to_numeric(
            df["Selling Price"], errors="coerce"
        )
    else:
        out["revenue"] = 0

    out["channel"] = channel
    out = out.dropna(subset=["date"])
    return out[STANDARD_COLS], exclusion_note


@st.cache_data(ttl=300, show_spinner=False)
def get_channel_drr(channel: str) -> tuple[pd.DataFrame, list[str]]:
    """Returns (standardized DRR dataframe, list of warning strings)."""
    conf = CHANNELS[channel]
    frames, warnings = [], []
    for tab in conf.get("dump_tabs", []):
        raw = load_tab(conf["sheet_url"], tab)
        err = raw.attrs.get("error")
        if err:
            warnings.append(f"{channel} / {tab}: {err}")
            continue
        frames.append(_standardize_one(raw, channel))
    parsed_frames = []
    for standardized, note in frames:
        parsed_frames.append(standardized)
        if note:
            warnings.append(note)
    combined = pd.concat(parsed_frames, ignore_index=True) if parsed_frames else pd.DataFrame(columns=STANDARD_COLS)

    # A row dated after today is never a real sale — it means a date got
    # stored wrong at the source (confirmed: these are genuine Date-typed
    # cells holding the wrong value, not a text-parsing ambiguity we can
    # resolve). Rather than let a handful of wrong dates distort the visible
    # totals and charts, exclude them here and say exactly which rows and
    # dates, so they can be corrected directly in the Google Sheet.
    today = pd.Timestamp.now().normalize()
    is_future = combined["date"] > today
    if is_future.any():
        n = int(is_future.sum())
        dates = ", ".join(sorted(combined.loc[is_future, "date"].dt.strftime("%d-%m-%Y").unique())[:5])
        warnings.append(
            f"{channel}: EXCLUDED {n} row(s) dated after today ({dates}"
            f"{'…' if is_future.sum() > 5 else ''}) from all totals and charts — "
            f"these dates are stored incorrectly in the source Google Sheet "
            f"(confirmed as real Date cells, not a text-parsing issue) and need "
            f"a manual correction there. Until fixed, that data simply won't "
            f"appear rather than showing under the wrong day."
        )
        combined = combined[~is_future]

    return combined, warnings


@st.cache_data(ttl=300, show_spinner=False)
def get_all_drr(channels: list[str]) -> tuple[pd.DataFrame, list[str]]:
    all_frames, all_warnings = [], []
    for ch in channels:
        df, warns = get_channel_drr(ch)
        all_frames.append(df)
        all_warnings.extend(warns)
    combined = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame(columns=STANDARD_COLS)
    return combined, all_warnings


@st.cache_data(ttl=300, show_spinner=False)
def get_ad_spend(channel: str) -> tuple[pd.DataFrame, list[str]]:
    """Standardized ad-spend data: date | channel | brand | spends | impressions | revenue | roas"""
    conf = CHANNELS[channel]
    amap = AD_COLUMN_MAP.get(channel)
    cols = ["date", "channel", "brand", "spends", "impressions", "clicks", "revenue", "roas"]
    if not amap or "ad_tabs" not in conf:
        return pd.DataFrame(columns=cols), []

    frames, warnings = [], []
    for tab in conf["ad_tabs"]:
        raw = load_tab(conf["sheet_url"], tab)
        err = raw.attrs.get("error")
        if err:
            warnings.append(f"{channel} / {tab}: {err}")
            continue
        out = pd.DataFrame(index=raw.index)
        date_col = amap.get("date")
        out["date"] = _safe_parse_dates(raw[date_col]) if date_col in raw.columns else pd.NaT
        out["brand"] = raw[amap["brand"]] if amap.get("brand") in raw.columns else None
        out["spends"] = pd.to_numeric(raw.get(amap.get("spends")), errors="coerce")
        out["impressions"] = pd.to_numeric(raw.get(amap.get("impressions")), errors="coerce")
        out["clicks"] = pd.to_numeric(raw.get(amap.get("clicks")), errors="coerce") if amap.get("clicks") else None
        out["revenue"] = pd.to_numeric(raw.get(amap.get("revenue")), errors="coerce")
        out["roas"] = pd.to_numeric(raw.get(amap.get("roas")), errors="coerce")
        out["channel"] = channel
        out = out.dropna(subset=["date"])
        frames.append(out[cols])

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)
    return combined, warnings


@st.cache_data(ttl=300, show_spinner=False)
def get_myntra_imp() -> tuple[pd.DataFrame, str | None]:
    """Myntra's IMP tab is a style-level snapshot (no date), kept separate."""
    conf = CHANNELS["Myntra"]
    tab = conf.get("imp_tab")
    if not tab:
        return pd.DataFrame(), None
    raw = load_tab(conf["sheet_url"], tab)
    return raw, raw.attrs.get("error")


@st.cache_data(ttl=300, show_spinner=False)
def get_pricing_tab(channel: str) -> tuple[pd.DataFrame, str | None]:
    tab = MASTER_SHEET["pricing_tabs"].get(channel)
    if not tab:
        return pd.DataFrame(), None
    raw = load_tab(MASTER_SHEET["sheet_url"], tab)
    return raw, raw.attrs.get("error")
