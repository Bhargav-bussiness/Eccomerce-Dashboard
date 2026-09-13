"""
Builds the SKU Master (unified product master) LIVE from Google Sheets —
the Master Sheet's per-channel pricing tabs, joined to each channel's own
internal SKU-code-to-shortname lookup where one exists. Everything here
goes through sheets_connector.load_tab, the same cached/auto-refreshing
reader the DRR pages use — so this updates automatically whenever your
team adds or edits a product in the Master Sheet. No manual re-export,
no separate file to regenerate.
"""

import re
import pandas as pd
import streamlit as st

from config import CHANNELS, MASTER_SHEET, SKU_LOOKUP, SKU_MASTER_CACHE_TTL_SECONDS
from sheets_connector import load_tab

LONG_COLS = ["Channel", "Brand", "Category", "Variant", "Product Name (raw)",
             "Channel SKU/Code", "MRP", "Base/Current Price", "Canonical Key", "Match Basis"]


# ---------------------------------------------------------------------------
# Parsing a short code (e.g. "RM SS PO2", "MC NIA", "RM 15g") into
# (Brand, Category, Variant). Verified against every real code found across
# your files — see the SKU Master build notes for the full check.
# ---------------------------------------------------------------------------
def _parse_short_code(code: str):
    raw = str(code).strip()
    u = raw.upper().replace("(", " ").replace(")", " ")
    u = re.sub(r"[^A-Z0-9. ]", " ", u)
    u = re.sub(r"\s+", " ", u).strip()

    if u.startswith("RM") or "REGINALD" in u:
        brand = "Reginald Men"
        rest = u[2:] if u.startswith("RM") else u.replace("REGINALD MEN", "").replace("REGINALD", "")
    elif u.startswith("MC") or "MOLECULAR" in u:
        brand = "Molecular Company"
        rest = u[2:] if u.startswith("MC") else u.replace("MOLECULAR COMPANY", "").replace("MOLECULAR", "")
    else:
        brand = "Unknown"
        rest = u
    rest = rest.strip()

    if re.search(r"\bKIT\b|\bCOMBO\b|DE ?TAN|GLOW|\bGNP\b", rest):
        category = "Kit/Combo"
    elif re.search(r"\bFW\b|FACEWASH|FACE WASH", rest):
        category = "Facewash"
    elif re.search(r"\bHS\b|HAIR ?SERUM", rest):
        category = "Hair Serum"
    elif re.search(r"\bNIA\b|NIACINAMIDE", rest):
        category = "Niacinamide Serum"
    elif re.search(r"VIT ?C|VITAMIN C", rest):
        category = "Vitamin C Serum"
    elif re.search(r"\bLB\b|LIP ?BALM", rest):
        category = "Lip Balm"
    elif re.search(r"\bMOS\b|MOIS|MOISTURI", rest):
        category = "Moisturiser"
    elif re.search(r"\bINTI\b|INTIMACY", rest):
        category = "Intimacy Serum"
    elif re.search(r"\bFS\b", rest) and not re.search(r"\bSS\b", rest):
        category = "Face Serum"
    elif re.search(r"\bSS\b", rest) or re.search(r"\bP[O0]\d\b", rest) or re.search(r"\d+ ?G\b", rest):
        category = "Sunscreen"
    else:
        category = None

    variant = None
    m_po = re.search(r"P[O0](\d)\s*(L)?", rest)
    m_combo = re.search(r"(\d+)\s*X\s*(\d+)\s*G", rest)
    m_gram = re.search(r"(\d+)\s*G\b", rest)
    if m_combo:
        variant = f"{m_combo.group(1)}x{m_combo.group(2)}G"
    elif m_po and int(m_po.group(1)) >= 2:
        variant = f"PO{m_po.group(1)}" + ("(L)" if m_po.group(2) else "")
    elif m_gram:
        variant = f"{m_gram.group(1)}G"
    elif m_po:
        variant = f"PO{m_po.group(1)}" + ("(L)" if m_po.group(2) else "")
    if variant is None:
        variant = "Std"

    if category is None:
        category = f"Unmapped: {raw}"

    return brand, category, variant


def _row(channel, brand, category, variant, product_raw, channel_code, mrp, base_price, match_basis):
    return {
        "Channel": channel, "Brand": brand, "Category": category, "Variant": variant,
        "Product Name (raw)": product_raw, "Channel SKU/Code": channel_code,
        "MRP": pd.to_numeric(mrp, errors="coerce"),
        "Base/Current Price": pd.to_numeric(base_price, errors="coerce"),
        "Canonical Key": f"{brand}|{category}|{variant}".upper(),
        "Match Basis": match_basis,
    }


@st.cache_data(ttl=SKU_MASTER_CACHE_TTL_SECONDS, show_spinner=False)
def _build_lookup(channel: str) -> dict:
    """Build a {code: shortname} dict from a channel's own lookup tab(s)."""
    conf = SKU_LOOKUP.get(channel)
    if not conf:
        return {}
    sheet_url = CHANNELS[channel]["sheet_url"]
    lookup = {}
    tabs = conf.get("tabs") or [conf.get("tab")]
    shortname_cols = conf.get("shortname_cols") or [conf.get("shortname_col")]
    for tab in tabs:
        df = load_tab(sheet_url, tab)
        if df.attrs.get("error") or df.empty:
            continue
        code_col = conf["code_col"]
        sn_col = next((c for c in shortname_cols if c in df.columns), None)
        if code_col not in df.columns or sn_col is None:
            continue
        sub = df[[code_col, sn_col]].dropna()
        sub = sub[(sub[code_col].astype(str).str.strip() != "") & (sub[sn_col].astype(str).str.strip() != "")]
        lookup.update(dict(zip(sub[code_col].astype(str), sub[sn_col].astype(str))))
    return lookup


@st.cache_data(ttl=SKU_MASTER_CACHE_TTL_SECONDS, show_spinner=False)
def get_sku_master() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Returns (long_df, comparison_df, warnings) — the live SKU Master."""
    warnings = []
    rows = []

    amazon_lookup = _build_lookup("Amazon")
    purplle_lookup = _build_lookup("Purplle")
    myntra_lookup = _build_lookup("Myntra")
    flipkart_lookup = _build_lookup("Flipkart")

    for channel, tab in MASTER_SHEET["pricing_tabs"].items():
        df = load_tab(MASTER_SHEET["sheet_url"], tab)
        err = df.attrs.get("error")
        if err:
            warnings.append(f"SKU Master / {channel}: {err}")
            continue
        if df.empty:
            continue

        if channel == "Amazon":
            for _, r in df.iterrows():
                title = r.get("Title")
                if not title or str(title).strip() == "":
                    continue
                code = amazon_lookup.get(str(r.get("Sku")))
                if code:
                    brand, cat, var = _parse_short_code(code)
                    basis = "SKU-code lookup (Dump-Data)"
                else:
                    brand, cat, var, basis = "Unknown", f"Unmapped: {title}", "Std", "No matching SKU code — kept unique"
                rows.append(_row(channel, brand, cat, var, title, r.get("Sku"), r.get("MRP"), r.get("BAU"), basis))

        elif channel == "Blinkit":
            for _, r in df.iterrows():
                name = r.get("Product Name")
                if not name or str(name).strip() == "":
                    continue
                brand, cat, var = _parse_short_code(name)
                rows.append(_row(channel, brand, cat, var, name, r.get("ITEM ID"), r.get("MRP"), r.get("SP"),
                                  "Name pattern match (no SKU-code lookup available)"))

        elif channel == "Flipkart":
            for _, r in df.iterrows():
                name = r.get("Product")
                if not name or str(name).strip() == "":
                    continue
                code = flipkart_lookup.get(str(r.get("FSN")))
                if code:
                    brand, cat, var = _parse_short_code(code)
                    basis = "SKU-code lookup (Sheet3 FSN)"
                else:
                    brand, cat, var, basis = "Unknown", f"Unmapped: {name}", "Std", "No matching FSN — kept unique"
                rows.append(_row(channel, brand, cat, var, name, r.get("SKU"), None, r.get("BAU"), basis))

        elif channel == "Zepto":
            # Master Sheet's Zepto tab has an unrelated reference table pasted
            # below the real 5-row pricing table, separated by a blank row.
            # Truncate at the first blank Product Name to avoid scraping it up.
            if "Product Name" in df.columns:
                blank_mask = df["Product Name"].isna() | (df["Product Name"].astype(str).str.strip() == "")
                if blank_mask.any():
                    df = df.iloc[: blank_mask.idxmax()]
            for _, r in df.iterrows():
                name = r.get("Product Name")
                if not name or str(name).strip() == "":
                    continue
                brand, cat, var = _parse_short_code(name)
                rows.append(_row(channel, brand, cat, var, name, r.get("SKU"), r.get("MRP"), r.get("BAU"),
                                  "Name pattern match (no SKU-code lookup available)"))

        elif channel == "Meesho":
            for _, r in df.iterrows():
                name = r.get("Product")
                if not name or str(name).strip() == "":
                    continue
                brand, cat, var = _parse_short_code(name)
                if brand == "Unknown" and r.get("Brand"):
                    b = str(r.get("Brand"))
                    brand = "Reginald Men" if "reginald" in b.lower() else ("Molecular Company" if "molecular" in b.lower() else b)
                rows.append(_row(channel, brand, cat, var, name, r.get("Style ID"), r.get("MRP"), r.get("BAU Pricing"),
                                  "Name pattern match (no SKU-code lookup available)"))

        elif channel == "Purplle":
            for _, r in df.iterrows():
                name = r.get("name") or r.get("Product name")
                if not name or str(name).strip() == "":
                    continue
                code = purplle_lookup.get(str(r.get("SKU")))
                if code:
                    brand, cat, var = _parse_short_code(code)
                    basis = "SKU-code lookup (dump sku -> short names)"
                else:
                    brand, cat, var, basis = "Unknown", f"Unmapped: {name}", "Std", "No matching SKU — kept unique"
                rows.append(_row(channel, brand, cat, var, name, r.get("SKU"), r.get("MRP Price"), r.get("BAU price"), basis))

        elif channel == "Myntra":
            for _, r in df.iterrows():
                name = r.get("Product Name")
                if not name or str(name).strip() == "":
                    continue
                style_id = str(r.get("Style ID")) if r.get("Style ID") else None
                code = myntra_lookup.get(style_id) if style_id else None
                if code:
                    brand, cat, var = _parse_short_code(code)
                    basis = "SKU-code lookup (IMP Style ID)"
                else:
                    brand, cat, var, basis = "Unknown", f"Unmapped: {name}", "Std", "No matching Style ID — kept unique"
                rows.append(_row(channel, brand, cat, var, name, r.get("Style ID"), r.get("MRP"), r.get("BAU Price"), basis))

        elif channel == "Nykaa":
            for _, r in df.iterrows():
                name = r.get("SKU Name")
                if not name or str(name).strip() == "":
                    continue
                brand, cat, var = _parse_short_code(name)
                mrp = pd.to_numeric(r.get("MRP"), errors="coerce")
                disc = pd.to_numeric(r.get("Default Discount %"), errors="coerce")
                base = round(mrp * (1 - disc / 100), 2) if pd.notna(mrp) and pd.notna(disc) else None
                rows.append(_row(channel, brand, cat, var, name, r.get("SKU"), mrp, base,
                                  "Name pattern match; base price estimated from MRP x (1-discount%)"))

    long_df = pd.DataFrame(rows, columns=LONG_COLS) if rows else pd.DataFrame(columns=LONG_COLS)
    if long_df.empty:
        return long_df, pd.DataFrame(), warnings

    channel_order = ["Amazon", "Blinkit", "Flipkart", "Meesho", "Myntra", "Nykaa", "Purplle", "Zepto"]
    pivot = long_df.pivot_table(index="Canonical Key", columns="Channel", values="Base/Current Price", aggfunc="first")
    pivot = pivot.reindex(columns=[c for c in channel_order if c in pivot.columns])
    match_count = long_df.groupby("Canonical Key")["Channel"].nunique()
    mrp_ref = long_df.groupby("Canonical Key")["MRP"].max()
    sample_name = long_df.groupby("Canonical Key")["Product Name (raw)"].first()
    verified = long_df.groupby("Canonical Key")["Match Basis"].apply(lambda s: s.str.startswith("SKU-code lookup").any())

    pivot.insert(0, "Sample Product Name", sample_name)
    pivot.insert(1, "Reference MRP", mrp_ref)
    pivot["# Channels Found In"] = match_count
    pivot["Verified by SKU code"] = verified.map({True: "Yes", False: "No — name-pattern only"})
    pivot = pivot.reset_index()
    pivot.insert(1, "Brand", pivot["Canonical Key"].str.split("|").str[0].str.title())
    pivot.insert(2, "Category", pivot["Canonical Key"].str.split("|").str[1].str.title())
    pivot.insert(3, "Variant", pivot["Canonical Key"].str.split("|").str[2])
    pivot = pivot.sort_values(["Brand", "Category", "Variant"])

    return long_df, pivot, warnings
