"""
CONFIG — this is the ONLY file you should need to touch every time a new
channel Google Sheet is added, or a tab name changes (e.g. a new month's
dump tab in Meesho / Purplle).

HOW TO FILL THIS IN
--------------------
1. Open each channel's live Google Sheet (the one your team updates).
2. Copy its full URL (or just the Sheet ID) into `sheet_url` below.
3. Share that Google Sheet with your service account's email address
   (see README.md) with "Viewer" access.
4. Check the tab names below match the tab names in the real sheet
   (case-sensitive). Add/remove tab names as your team adds new
   monthly dump tabs.

Nothing else in the app needs to change when your data updates —
only when the *structure* (tab names) changes.
"""

# ---------------------------------------------------------------------------
# Per-channel sales ("DRR") sheets
# ---------------------------------------------------------------------------
CHANNELS = {
    "Amazon": {
        "sheet_url": "https://docs.google.com/spreadsheets/d/1uCXwc_eV3GimTl6B0EmcaKUbn-cMSdan-47ywTcoUIw/edit",
        "dump_tabs": ["Dump-Data"],
    },
    "Blinkit": {
        "sheet_url": "https://docs.google.com/spreadsheets/d/1FsMY1H5RoJioAlONakEOQk9xGIC8st670yDUpfmC6kI/edit",
        "dump_tabs": ["Total Dump"],
        "ad_tabs": ["Paid Dump"],
    },
    "Flipkart": {
        "sheet_url": "https://docs.google.com/spreadsheets/d/1XhCTXkSILrecRkplNjpQlsD10YDpx1OYaElRXmftUcM/edit",
        "dump_tabs": ["DUMP"],
    },
    "Meesho": {
        "sheet_url": "https://docs.google.com/spreadsheets/d/1mrBatILDO8afwTjLJlUUYwvRZbI64fICBoDB6OguNt8/edit",
        # Meesho gets a NEW dump tab every month (e.g. "aug", "sep-dump").
        # Add each new month's tab name here as it appears.
        "dump_tabs": ["aug", "sep-dump"],
    },
    "Myntra": {
        "sheet_url": "https://docs.google.com/spreadsheets/d/1q7Yo8Cy35GDqi8XfRfPMGe0eTkRFzO3GOrHur8WVvCs/edit",
        "dump_tabs": ["net sale Myntra "],  # note: trailing space in source tab name
        "imp_tab": "IMP",
    },
    "Nykaa": {
        "sheet_url": "https://docs.google.com/spreadsheets/d/17NkrkfSmUZVGkwPg427g_nT5EOrUrh0PRUAACcWSPpk/edit",
        "dump_tabs": ["DUMP"],
    },
    "Purplle": {
        "sheet_url": "https://docs.google.com/spreadsheets/d/1IhW270U-uP2KQm70EIQ5t9TK-eojpzyUGmGZO5hTBIs/edit",
        # New month = new dump tab. Add each as it appears.
        "dump_tabs": ["June Dump", "July Dump", "August Dump", "Sept Dump"],
    },
    "Zepto": {
        "sheet_url": "https://docs.google.com/spreadsheets/d/10ZLs3k3JuvRLE3KOaAHZtMNtL7fzCl60EwQqvy0U_3c/edit",
        "dump_tabs": ["TOTAL DUMP DATA"],
        "ad_tabs": ["Paid Daily"],
    },
}

# ---------------------------------------------------------------------------
# Master Sheet (cross-channel pricing)
# ---------------------------------------------------------------------------
MASTER_SHEET = {
    "sheet_url": "https://docs.google.com/spreadsheets/d/1Z_oYwpiwkZZaL7R3NMuajcas_V6KlWdLvCsVEZ5WhzA/edit",
    "pricing_tabs": {
        "Amazon": "Amazon",
        "Blinkit": "Blinkit",
        "Zepto": "Zepto",
        "Meesho": "Meesho",
        "Purplle": "Purplle",
        "Myntra": "Myntra",
        "Nykaa": "Nykaa",
        "Flipkart": "FK seasonal Prices sheet",
    },
}

# ---------------------------------------------------------------------------
# SKU Master: each channel's own SKU-code -> short-name lookup, where one
# exists (found inside that channel's own dump/reporting sheet). These are
# the team's real internal codes (e.g. "RM SS PO2"), which is a far more
# reliable join key than guessing from a full marketing title. Channels not
# listed here (Blinkit, Zepto, Meesho, Nykaa) have no such lookup in their
# sheets, so the SKU Master falls back to parsing the product name directly
# for those — lower confidence, clearly labeled as such in the output.
# ---------------------------------------------------------------------------
SKU_LOOKUP = {
    "Amazon": {"tab": "Dump-Data", "code_col": "sku", "shortname_col": "Short name"},
    "Purplle": {"tabs": ["August Dump", "Sept Dump"], "code_col": "sku",
                "shortname_cols": ["short names", "short name"]},
    "Myntra": {"tab": "IMP", "code_col": "Style ID", "shortname_col": "SHORTNAMES"},
    "Flipkart": {"tab": "Sheet3", "code_col": "FSN", "shortname_col": "ITEM"},
}

# ---------------------------------------------------------------------------
# Column mapping: raw column name in each channel's dump tab -> standard field
# Standard fields: date, units, revenue, brand, product, sku
# Set a field to None if it must be computed (handled in data_pipeline.py)
# ---------------------------------------------------------------------------
COLUMN_MAP = {
    "Amazon": {
        "date": "Date", "units": "quantity", "revenue": "item-price",
        "brand": "Brand", "product": "product-name", "sku": "sku",
    },
    "Blinkit": {
        "date": "Date", "units": "Unit", "revenue": "Sale",
        "brand": "Brand", "product": "item_name", "sku": "item_id",
    },
    "Flipkart": {
        "date": "Order Date", "units": "Final Sale Units", "revenue": "Final Sale Amount",
        "brand": "Brand", "product": "Product", "sku": "SKU ID",
    },
    "Meesho": {
        "date": "Order Date", "units": "Quantity",
        # revenue column name varies by month; pipeline tries these in order
        "revenue_candidates": [
            "Total sale",
            "Supplier Discounted Price (Incl GST and Commision)",
            "Supplier Listed Price (Incl. GST + Commission)",
        ],
        "brand": "Brand", "product": "Product Name", "sku": "SKU",
        # Some monthly dump tabs include cancelled-order rows at full value —
        # confirmed on the Sept dump, where CANCELLED rows were 15.5% of the
        # "Total sale" column. Excluded so revenue reflects real sales only.
        "status_col": "Reason for Credit Entry",
        "excluded_statuses": ["CANCELLED"],
    },
    "Myntra": {
        "date": "Date", "units": None,  # 1 unit per row
        "revenue": "final amount",
        "brand": "brand", "product": "style name", "sku": "style id",
        # "net sale Myntra" still includes cancelled orders (status "C") at
        # full value — confirmed at 11.6% of total revenue. Excluded here.
        # Other statuses (SH=Shipped, PK, WP) are kept as real orders since
        # they aren't confirmed cancellations.
        "status_col": "order status",
        "excluded_statuses": ["C"],
    },
    "Nykaa": {
        "date": "Date", "units": "Total Qty",
        "revenue": None,  # computed: Total Qty * Selling Price
        "brand": "brand", "product": "SKU Name", "sku": "SKU Code",
    },
    "Purplle": {
        "date": "dt", "units": "qty", "revenue": "nmv",
        "brand": "brand_name", "product": "name", "sku": "sku",
    },
    "Zepto": {
        "date": "date", "units": "Sales (Qty) - Units", "revenue": "Gross Merchandise Value",
        "brand": "Brand Name", "product": "SKU Name", "sku": "SKU Number",
    },
}

# Ad-spend tab column mapping
AD_COLUMN_MAP = {
    "Blinkit": {
        "date": "Date", "spends": "Spend", "impressions": "Impressions",
        "revenue": "Rev", "roas": "ROAS", "brand": "Brand",
    },
    "Zepto": {
        "date": "Date", "spends": "Spends", "impressions": "Impressions",
        "clicks": "Clicks", "revenue": "Paid Revenue", "roas": "ROAS",
    },
}

CACHE_TTL_SECONDS = 300  # how long data is cached before re-fetching from Google Sheets
