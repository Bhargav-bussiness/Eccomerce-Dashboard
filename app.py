  import pandas as pd
import plotly.express as px
import streamlit as st

from config import CHANNELS, MASTER_SHEET
from sheets_connector import clear_cache, list_tabs, load_tab
from data_pipeline import get_all_drr, get_channel_drr, get_ad_spend, get_myntra_imp, get_pricing_tab

st.set_page_config(page_title="Marketplace DRR Dashboard", layout="wide", page_icon="📈")

ALL_CHANNELS = list(CHANNELS.keys())
AD_CHANNELS = [c for c in ALL_CHANNELS if "ad_tabs" in CHANNELS[c]]

# ---------------------------------------------------------------------------
# Sidebar — filters + manual refresh
# ---------------------------------------------------------------------------
st.sidebar.title("📈 DRR Dashboard")
st.sidebar.caption("Live from your team's Google Sheets")

if st.sidebar.button("🔄 Refresh now", use_container_width=True):
    clear_cache()
    st.rerun()

selected_channels = st.sidebar.multiselect("Channels", ALL_CHANNELS, default=ALL_CHANNELS)

st.sidebar.markdown("---")
st.sidebar.caption(
    "Data auto-refreshes every 5 minutes. First-time setup? See README.md "
    "— you need to paste each channel's Google Sheet URL into config.py "
    "and share it with the service account."
)

if not selected_channels:
    st.warning("Select at least one channel from the sidebar.")
    st.stop()

# ---------------------------------------------------------------------------
# Load combined DRR data once
# ---------------------------------------------------------------------------
drr_df, drr_warnings = get_all_drr(selected_channels)

if not drr_df.empty:
    min_d, max_d = drr_df["date"].min().date(), drr_df["date"].max().date()
    date_range = st.sidebar.date_input("Date range", value=(min_d, max_d), min_value=min_d, max_value=max_d)
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        drr_df = drr_df[(drr_df["date"].dt.date >= start) & (drr_df["date"].dt.date <= end)]

tab_overview, tab_channel, tab_ads, tab_pricing, tab_raw = st.tabs(
    ["📊 Overview", "🔍 Channel Deep-Dive", "💰 Ad Spends & ROAS", "🏷️ Pricing (Master Sheet)", "🗂️ Raw Sheet Explorer"]
)

# ---------------------------------------------------------------------------
# OVERVIEW
# ---------------------------------------------------------------------------
with tab_overview:
    if drr_df.empty:
        st.info("No data loaded yet — configure your Google Sheet URLs in config.py.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        n_days = max(drr_df["date"].dt.date.nunique(), 1)
        c1.metric("Total Revenue", f"₹{drr_df['revenue'].sum():,.0f}")
        c2.metric("Total Units", f"{drr_df['units'].sum():,.0f}")
        c3.metric("Avg Daily Revenue (DRR)", f"₹{drr_df['revenue'].sum() / n_days:,.0f}")
        c4.metric("Avg Daily Units (DRR)", f"{drr_df['units'].sum() / n_days:,.1f}")

        st.markdown("#### Revenue trend by channel")
        daily = drr_df.groupby([drr_df["date"].dt.date, "channel"], as_index=False)["revenue"].sum()
        daily.columns = ["date", "channel", "revenue"]
        fig = px.line(daily, x="date", y="revenue", color="channel", markers=True)
        st.plotly_chart(fig, use_container_width=True)

        cA, cB = st.columns(2)
        with cA:
            st.markdown("#### Revenue share by channel")
            by_channel = drr_df.groupby("channel", as_index=False)["revenue"].sum().sort_values("revenue", ascending=False)
            st.plotly_chart(px.pie(by_channel, names="channel", values="revenue", hole=0.4), use_container_width=True)
        with cB:
            st.markdown("#### Units by channel")
            by_channel_u = drr_df.groupby("channel", as_index=False)["units"].sum().sort_values("units", ascending=False)
            st.plotly_chart(px.bar(by_channel_u, x="channel", y="units"), use_container_width=True)

        st.markdown("#### Daily DRR summary")
        pivot = drr_df.pivot_table(index=drr_df["date"].dt.date, columns="channel", values="revenue", aggfunc="sum", fill_value=0)
        st.dataframe(pivot.sort_index(ascending=False), use_container_width=True)

    if drr_warnings:
        with st.expander(f"⚠️ {len(drr_warnings)} data warning(s)"):
            for w in drr_warnings:
                st.write("-", w)

# ---------------------------------------------------------------------------
# CHANNEL DEEP-DIVE
# ---------------------------------------------------------------------------
with tab_channel:
    ch = st.selectbox("Channel", selected_channels)
    ch_df, ch_warnings = get_channel_drr(ch)
    if ch_df.empty:
        st.info(f"No data available for {ch} yet.")
    else:
        c1, c2 = st.columns(2)
        c1.metric(f"{ch} — Total Revenue", f"₹{ch_df['revenue'].sum():,.0f}")
        c2.metric(f"{ch} — Total Units", f"{ch_df['units'].sum():,.0f}")

        daily = ch_df.groupby(ch_df["date"].dt.date, as_index=False).agg(revenue=("revenue", "sum"), units=("units", "sum"))
        fig = px.bar(daily, x="date", y="revenue", title=f"{ch} — Daily Revenue")
        st.plotly_chart(fig, use_container_width=True)
        fig2 = px.line(daily, x="date", y="units", markers=True, title=f"{ch} — Daily Units")
        st.plotly_chart(fig2, use_container_width=True)

        cA, cB = st.columns(2)
        with cA:
            st.markdown("##### Top brands")
            top_brand = ch_df.groupby("brand", as_index=False)["revenue"].sum().sort_values("revenue", ascending=False).head(15)
            st.dataframe(top_brand, use_container_width=True, hide_index=True)
        with cB:
            st.markdown("##### Top SKUs / products")
            top_sku = ch_df.groupby(["product", "sku"], as_index=False)["revenue"].sum().sort_values("revenue", ascending=False).head(15)
            st.dataframe(top_sku, use_container_width=True, hide_index=True)

    if ch_warnings:
        with st.expander(f"⚠️ {len(ch_warnings)} data warning(s) for {ch}"):
            for w in ch_warnings:
                st.write("-", w)

# ---------------------------------------------------------------------------
# AD SPENDS & ROAS
# ---------------------------------------------------------------------------
with tab_ads:
    if not AD_CHANNELS:
        st.info("No channels are configured with ad-spend tabs (see config.py -> ad_tabs).")
    for ch in [c for c in AD_CHANNELS if c in selected_channels]:
        st.markdown(f"### {ch}")
        ad_df, ad_warnings = get_ad_spend(ch)
        if ad_df.empty:
            st.info(f"No ad-spend data available for {ch} yet.")
        else:
            daily = ad_df.groupby(ad_df["date"].dt.date, as_index=False).agg(
                spends=("spends", "sum"), revenue=("revenue", "sum")
            )
            daily["roas"] = (daily["revenue"] / daily["spends"]).round(2)
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Spend", f"₹{daily['spends'].sum():,.0f}")
            c2.metric("Total Attributed Revenue", f"₹{daily['revenue'].sum():,.0f}")
            c3.metric("Blended ROAS", f"{(daily['revenue'].sum() / daily['spends'].sum()):.2f}x" if daily['spends'].sum() else "—")

            fig = px.bar(daily, x="date", y="spends", title=f"{ch} — Daily Ad Spend")
            st.plotly_chart(fig, use_container_width=True)
            fig2 = px.line(daily, x="date", y="roas", markers=True, title=f"{ch} — Daily ROAS")
            st.plotly_chart(fig2, use_container_width=True)
        if ad_warnings:
            with st.expander(f"⚠️ warnings for {ch}"):
                for w in ad_warnings:
                    st.write("-", w)
        st.markdown("---")

    if "Myntra" in selected_channels:
        st.markdown("### Myntra — Style Performance (impressions / clicks / purchases)")
        imp_df, err = get_myntra_imp()
        if err:
            st.info(err)
        elif not imp_df.empty:
            st.dataframe(imp_df.sort_values("Purchases", ascending=False), use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# PRICING (Master Sheet)
# ---------------------------------------------------------------------------
with tab_pricing:
    st.caption("Read directly from the Master Sheet's per-channel pricing tabs.")
    for ch in [c for c in MASTER_SHEET["pricing_tabs"] if c in selected_channels]:
        with st.expander(f"{ch} pricing"):
            pdf, err = get_pricing_tab(ch)
            if err:
                st.info(err)
            elif pdf.empty:
                st.info("No rows found.")
            else:
                st.dataframe(pdf, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# RAW SHEET EXPLORER — open literally any tab in any configured sheet
# ---------------------------------------------------------------------------
with tab_raw:
    st.caption("Browse any tab from any configured Google Sheet, exactly as it appears.")
    source_options = {**{c: CHANNELS[c]["sheet_url"] for c in ALL_CHANNELS}, "Master Sheet": MASTER_SHEET["sheet_url"]}
    src = st.selectbox("Source sheet", list(source_options.keys()))
    sheet_url = source_options[src]
    tabs = list_tabs(sheet_url)
    if not tabs:
        st.info("Could not list tabs — check the sheet URL in config.py and sharing permissions.")
    else:
        tab_name = st.selectbox("Tab", tabs)
        raw = load_tab(sheet_url, tab_name)
        err = raw.attrs.get("error")
        if err:
            st.warning(err)
        elif raw.empty:
            st.info("This tab has no rows.")
        else:
            search = st.text_input("Filter rows (search all columns)")
            view = raw
            if search:
                mask = raw.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
                view = raw[mask]
            st.dataframe(view, use_container_width=True, hide_index=True)
            st.caption(f"{len(view):,} rows × {len(view.columns)} columns")
