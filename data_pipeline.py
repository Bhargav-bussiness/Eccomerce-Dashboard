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


def _standardize_one(df: pd.DataFrame, channel: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=STANDARD_COLS)

    cmap = COLUMN_MAP.get(channel, {})
    out = pd.DataFrame(index=df.index)

    # date
    date_col = cmap.get("date")
    out["date"] = pd.to_datetime(df[date_col], errors="coerce") if date_col in df.columns else pd.NaT

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
    return out[STANDARD_COLS]


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
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=STANDARD_COLS)
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
        out["date"] = pd.to_datetime(raw.get(amap.get("date")), errors="coerce")
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
