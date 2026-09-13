import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import CHANNELS, MASTER_SHEET
from sheets_connector import clear_cache, list_tabs, load_tab
from data_pipeline import get_all_drr, get_channel_drr, get_ad_spend, get_myntra_imp, get_pricing_tab
from sku_master_pipeline import get_sku_master
from formatting import format_inr, format_inr_short, format_units_short

st.set_page_config(page_title="Marketplace DRR Dashboard", layout="wide", page_icon="📈")

ALL_CHANNELS = list(CHANNELS.keys())
AD_CHANNELS = [c for c in ALL_CHANNELS if "ad_tabs" in CHANNELS[c]]

# A single consistent palette used across every chart so a channel is always
# the same color no matter which tab you're looking at.
CHANNEL_COLORS = {
    "Amazon": "#FF9900",
    "Blinkit": "#F8CB46",
    "Flipkart": "#2874F0",
    "Meesho": "#9F2089",
    "Myntra": "#FF3F6C",
    "Nykaa": "#FC2779",
    "Purplle": "#6A2C70",
    "Zepto": "#8B2FC9",
}
PLOTLY_TEMPLATE = "plotly_dark"

# ---------------------------------------------------------------------------
# Global styling
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .kpi-card {
        background: linear-gradient(155deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px;
        padding: 18px 20px;
        margin-bottom: 6px;
    }
    .kpi-label {
        font-size: 0.8rem;
        color: rgba(255,255,255,0.55);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 6px;
    }
    .kpi-value {
        font-size: 1.9rem;
        font-weight: 700;
        line-height: 1.1;
    }
    .kpi-sub {
        font-size: 0.78rem;
        color: rgba(255,255,255,0.4);
        margin-top: 4px;
    }
    .section-title {
        font-size: 1.05rem;
        font-weight: 600;
        margin: 22px 0 8px 0;
        color: rgba(255,255,255,0.9);
    }
    div[data-testid="stMetric"] { display: none; } /* we use custom KPI cards instead */
    </style>
    """,
    unsafe_allow_html=True,
)


def kpi_card(label: str, value: str, sub: str = "") -> str:
    return f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        <div class="kpi-sub">{sub}</div>
    </div>
    """


def section(title: str):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)


def style_fig(fig, y_title=None):
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Arial, sans-serif", size=13),
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hoverlabel=dict(font_size=13),
    )
    if y_title:
        fig.update_yaxes(title=y_title)
    return fig


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
    date_range = st.sidebar.date_input(
        "Date range", value=(min_d, max_d), min_value=min_d, max_value=max_d, format="DD/MM/YYYY"
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        drr_df = drr_df[(drr_df["date"].dt.date >= start) & (drr_df["date"].dt.date <= end)]

tab_overview, tab_channel, tab_ads, tab_pricing, tab_sku, tab_raw = st.tabs(
    ["📊 Overview", "🔍 Channel Deep-Dive", "💰 Ad Spends & ROAS", "🏷️ Pricing (Master Sheet)",
     "🧬 SKU Master", "🗂️ Raw Sheet Explorer"]
)


def channel_colors_for(names):
    return {n: CHANNEL_COLORS.get(n, "#999999") for n in names}


# ---------------------------------------------------------------------------
# OVERVIEW
# ---------------------------------------------------------------------------
with tab_overview:
    if drr_df.empty:
        st.info("No data loaded yet — configure your Google Sheet URLs in config.py.")
    else:
        n_days = max(drr_df["date"].dt.date.nunique(), 1)
        total_rev = drr_df["revenue"].sum()
        total_units = drr_df["units"].sum()

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(kpi_card("Total Revenue", format_inr_short(total_rev), format_inr(total_rev)), unsafe_allow_html=True)
        with c2:
            st.markdown(kpi_card("Total Units", format_units_short(total_units), f"{total_units:,.0f} units"), unsafe_allow_html=True)
        with c3:
            st.markdown(kpi_card("Avg Daily Revenue (DRR)", format_inr_short(total_rev / n_days), format_inr(total_rev / n_days) + " / day"), unsafe_allow_html=True)
        with c4:
            st.markdown(kpi_card("Avg Daily Units (DRR)", f"{total_units / n_days:,.0f}", f"{total_units / n_days:,.1f} units / day"), unsafe_allow_html=True)

        section("Revenue trend")
        show_breakdown = st.toggle("Break down by channel", value=False)
        if show_breakdown:
            daily = drr_df.groupby([drr_df["date"].dt.date, "channel"], as_index=False)["revenue"].sum()
            daily.columns = ["date", "channel", "revenue"]
            daily["revenue_label"] = daily["revenue"].apply(format_inr)
            fig = px.line(
                daily, x="date", y="revenue", color="channel", markers=True,
                color_discrete_map=channel_colors_for(daily["channel"].unique()),
                custom_data=["revenue_label", "channel"],
            )
            fig.update_traces(hovertemplate="%{customdata[1]}<br>%{x}<br>%{customdata[0]}<extra></extra>")
        else:
            daily = drr_df.groupby(drr_df["date"].dt.date, as_index=False)["revenue"].sum()
            daily.columns = ["date", "revenue"]
            daily["revenue_label"] = daily["revenue"].apply(format_inr)
            fig = px.line(
                daily, x="date", y="revenue", markers=True,
                custom_data=["revenue_label"],
                color_discrete_sequence=["#4C9AFF"],
            )
            fig.update_traces(hovertemplate="%{x}<br>%{customdata[0]}<extra></extra>")
        st.plotly_chart(style_fig(fig, y_title="Revenue (₹)"), use_container_width=True)

        cA, cB = st.columns(2)
        with cA:
            section("Revenue share by channel")
            by_channel = drr_df.groupby("channel", as_index=False)["revenue"].sum().sort_values("revenue", ascending=False)
            by_channel["revenue_label"] = by_channel["revenue"].apply(format_inr)
            fig_pie = px.pie(
                by_channel, names="channel", values="revenue", hole=0.55,
                color="channel", color_discrete_map=channel_colors_for(by_channel["channel"]),
                custom_data=["revenue_label"],
            )
            fig_pie.update_traces(textinfo="percent+label", hovertemplate="%{label}<br>%{customdata[0]}<extra></extra>")
            st.plotly_chart(style_fig(fig_pie), use_container_width=True)
        with cB:
            section("Units by channel")
            by_channel_u = drr_df.groupby("channel", as_index=False)["units"].sum().sort_values("units", ascending=False)
            fig_bar = px.bar(
                by_channel_u, x="channel", y="units", color="channel",
                color_discrete_map=channel_colors_for(by_channel_u["channel"]),
                text=by_channel_u["units"].apply(format_units_short),
            )
            fig_bar.update_traces(textposition="outside", showlegend=False)
            st.plotly_chart(style_fig(fig_bar, y_title="Units"), use_container_width=True)

        section("Daily DRR summary")
        pivot = drr_df.pivot_table(index=drr_df["date"].dt.date, columns="channel", values="revenue", aggfunc="sum", fill_value=0)
        pivot = pivot.sort_index(ascending=False)
        pivot.index = pd.to_datetime(pivot.index).strftime("%d-%m-%Y")
        pivot.index.name = "date"
        display_pivot = pivot.map(format_inr)
        st.dataframe(display_pivot, use_container_width=True)

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
        rev_total = ch_df["revenue"].sum()
        units_total = ch_df["units"].sum()
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(kpi_card(f"{ch} — Total Revenue", format_inr_short(rev_total), format_inr(rev_total)), unsafe_allow_html=True)
        with c2:
            st.markdown(kpi_card(f"{ch} — Total Units", format_units_short(units_total), f"{units_total:,.0f} units"), unsafe_allow_html=True)

        daily = ch_df.groupby(ch_df["date"].dt.date, as_index=False).agg(revenue=("revenue", "sum"), units=("units", "sum"))
        daily["revenue_label"] = daily["revenue"].apply(format_inr)

        section(f"{ch} — Daily Revenue")
        fig = px.bar(daily, x="date", y="revenue", custom_data=["revenue_label"],
                     color_discrete_sequence=[CHANNEL_COLORS.get(ch, "#4C9AFF")])
        fig.update_traces(hovertemplate="%{x}<br>%{customdata[0]}<extra></extra>")
        st.plotly_chart(style_fig(fig, y_title="Revenue (₹)"), use_container_width=True)

        section(f"{ch} — Daily Units")
        fig2 = px.line(daily, x="date", y="units", markers=True,
                        color_discrete_sequence=[CHANNEL_COLORS.get(ch, "#4C9AFF")])
        st.plotly_chart(style_fig(fig2, y_title="Units"), use_container_width=True)

        cA, cB = st.columns(2)
        with cA:
            st.markdown('<div class="section-title">Top brands</div>', unsafe_allow_html=True)
            top_brand = ch_df.groupby("brand", as_index=False)["revenue"].sum().sort_values("revenue", ascending=False).head(15)
            top_brand["revenue"] = top_brand["revenue"].apply(format_inr)
            st.dataframe(top_brand, use_container_width=True, hide_index=True)
        with cB:
            st.markdown('<div class="section-title">Top SKUs / products</div>', unsafe_allow_html=True)
            top_sku = ch_df.groupby(["product", "sku"], as_index=False)["revenue"].sum().sort_values("revenue", ascending=False).head(15)
            top_sku["revenue"] = top_sku["revenue"].apply(format_inr)
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
        section(ch)
        ad_df, ad_warnings = get_ad_spend(ch)
        if ad_df.empty:
            st.info(f"No ad-spend data available for {ch} yet.")
        else:
            daily = ad_df.groupby(ad_df["date"].dt.date, as_index=False).agg(
                spends=("spends", "sum"), revenue=("revenue", "sum")
            )
            daily["roas"] = (daily["revenue"] / daily["spends"]).round(2)
            spend_total, rev_total = daily["spends"].sum(), daily["revenue"].sum()
            blended_roas = f"{(rev_total / spend_total):.2f}x" if spend_total else "—"

            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(kpi_card("Total Spend", format_inr_short(spend_total), format_inr(spend_total)), unsafe_allow_html=True)
            with c2:
                st.markdown(kpi_card("Total Attributed Revenue", format_inr_short(rev_total), format_inr(rev_total)), unsafe_allow_html=True)
            with c3:
                st.markdown(kpi_card("Blended ROAS", blended_roas, "revenue ÷ spend"), unsafe_allow_html=True)

            daily["spends_label"] = daily["spends"].apply(format_inr)
            fig = px.bar(daily, x="date", y="spends", custom_data=["spends_label"],
                         color_discrete_sequence=[CHANNEL_COLORS.get(ch, "#4C9AFF")])
            fig.update_traces(hovertemplate="%{x}<br>%{customdata[0]}<extra></extra>")
            st.plotly_chart(style_fig(fig, y_title="Ad Spend (₹)"), use_container_width=True)

            fig2 = px.line(daily, x="date", y="roas", markers=True,
                            color_discrete_sequence=[CHANNEL_COLORS.get(ch, "#4C9AFF")])
            st.plotly_chart(style_fig(fig2, y_title="ROAS (x)"), use_container_width=True)
        if ad_warnings:
            with st.expander(f"⚠️ warnings for {ch}"):
                for w in ad_warnings:
                    st.write("-", w)
        st.markdown("---")

    if "Myntra" in selected_channels:
        section("Myntra — Style Performance (impressions / clicks / purchases)")
        imp_df, err = get_myntra_imp()
        if err:
            st.info(err)
        elif not imp_df.empty:
            imp_df = imp_df.copy()
            for col in ["Impressions", "Clicks", "Add to Carts", "Purchases", "Return %", "Consideration %", "Conversion %", "Rating"]:
                if col in imp_df.columns:
                    imp_df[col] = pd.to_numeric(imp_df[col], errors="coerce")
            if "Purchases" in imp_df.columns:
                imp_df = imp_df.sort_values("Purchases", ascending=False, na_position="last")
            st.dataframe(imp_df, use_container_width=True, hide_index=True)

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
# SKU MASTER — live product master, auto-updates whenever the Master Sheet
# or any of the SKU-code lookup source sheets change. No manual re-export.
# ---------------------------------------------------------------------------
with tab_sku:
    st.caption(
        "Built live from the Master Sheet's pricing tabs, joined to each channel's own SKU-code "
        "lookup where one exists (Amazon, Purplle, Myntra, Flipkart). Updates automatically — "
        "add a new product to the Master Sheet and it appears here on the next refresh."
    )
    long_df, comparison_df, sku_warnings = get_sku_master()

    if long_df.empty:
        st.info("No SKU Master data loaded yet — check the Master Sheet URL in config.py.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total SKUs", f"{len(long_df):,}")
        verified_pct = (long_df["Match Basis"].str.startswith("SKU-code lookup")).mean() * 100
        c2.metric("Verified by SKU code", f"{verified_pct:.0f}%")
        c3.metric("Product concepts matched across channels", f"{(comparison_df['# Channels Found In'] >= 2).sum()} of {len(comparison_df)}")

        st.markdown("#### Cross-Channel Comparison")
        st.dataframe(comparison_df, use_container_width=True, hide_index=True)

        with st.expander("Full SKU list (every row, every channel)"):
            st.dataframe(long_df, use_container_width=True, hide_index=True)

        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "⬇️ Download as JSON",
                data=comparison_df.to_json(orient="records", indent=2),
                file_name="sku_master.json",
                mime="application/json",
                use_container_width=True,
            )
        with dl2:
            st.download_button(
                "⬇️ Download as CSV",
                data=comparison_df.to_csv(index=False),
                file_name="sku_master.csv",
                mime="text/csv",
                use_container_width=True,
            )

    if sku_warnings:
        with st.expander(f"⚠️ {len(sku_warnings)} warning(s)"):
            for w in sku_warnings:
                st.write("-", w)

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
