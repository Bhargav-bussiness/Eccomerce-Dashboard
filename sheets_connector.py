"""
Handles all live reads from Google Sheets via a service account.
Every function here is cached (see config.CACHE_TTL_SECONDS) so the app
doesn't hammer the Sheets API — data auto-refreshes every few minutes,
and there's a manual "Refresh now" button in the sidebar (app.py) that
clears the cache on demand.
"""

import time
import random

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

from config import CACHE_TTL_SECONDS

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


@st.cache_resource
def _get_client():
    """Build an authenticated gspread client from Streamlit secrets."""
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "Quota exceeded" in text or "RESOURCE_EXHAUSTED" in text


def _with_retry(fn, *args, max_retries=5, base_delay=3, **kwargs):
    """
    Call fn(*args, **kwargs), retrying with exponential backoff (+ jitter)
    specifically on a 429 rate-limit response. The Sheets API's default free
    quota is small enough that this app can legitimately hit it — every
    extra tab read (the SKU Master feature added ~12 more) makes that more
    likely, especially right after a cache-clearing "Refresh now" or a cold
    start with several people viewing at once. A short wait-and-retry
    resolves it without the person ever seeing an error, instead of failing
    immediately on the first hiccup.
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if _is_rate_limit_error(e) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                time.sleep(delay)
                continue
            raise
    raise last_exc


@st.cache_resource(ttl=CACHE_TTL_SECONDS)
def _open_spreadsheet(sheet_url: str):
    """
    Open a Google Sheet once and reuse the handle for every tab read against
    it. Previously each load_tab() call re-opened the spreadsheet from
    scratch even when reading multiple tabs from the same sheet (e.g.
    Purplle's 4 monthly dump tabs) — that's an extra API call per tab for no
    reason, and a meaningful chunk of what was pushing us over the read-quota
    limit. Cached as a resource (not cache_data) since a gspread Spreadsheet
    object isn't the kind of plain data cache_data is meant for.
    """
    client = _get_client()
    return _with_retry(client.open_by_url, sheet_url)


def _dedupe_headers(headers: list) -> list[str]:
    """
    Turn a raw header row into safe, unique column names.
    Blank cells become col_N; repeated names get a _2, _3... suffix.
    This is needed because several of your real sheets have multiple
    blank trailing header cells (leftover formatting), which gspread's
    get_all_records() refuses to handle on its own. It also has to cope
    with a header cell that's a number rather than text (confirmed on
    Purplle's July Dump tab) since UNFORMATTED_VALUE returns those as
    actual int/float, not strings.
    """
    seen: dict[str, int] = {}
    result = []
    for i, h in enumerate(headers):
        if h is None or h == "":
            h = f"col_{i + 1}"
        else:
            h = str(h).strip()
            if h == "":
                h = f"col_{i + 1}"
        if h in seen:
            seen[h] += 1
            h = f"{h}_{seen[h]}"
        else:
            seen[h] = 0
        result.append(h)
    return result


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_tab(sheet_url: str, tab_name: str) -> pd.DataFrame:
    """
    Load a single tab from a Google Sheet as a DataFrame.
    Returns an empty DataFrame (with an 'error' attr) rather than raising,
    so one broken tab doesn't take down the whole dashboard.
    """
    if not sheet_url or sheet_url.startswith("PASTE_"):
        df = pd.DataFrame()
        df.attrs["error"] = "Sheet URL not configured yet (see config.py)."
        return df

    try:
        sh = _open_spreadsheet(sheet_url)
        ws = _with_retry(sh.worksheet, tab_name)

        # UNFORMATTED_VALUE returns Google Sheets' underlying serial numbers for
        # date cells (the same day-count system Excel uses) instead of a
        # locale-dependent formatted string. This matters because a formatted
        # date like "08-12-2026" is genuinely ambiguous — "8th December" or
        # "December 8th" — and guessing wrong silently misplaces rows into the
        # wrong month. Serial numbers have no such ambiguity.
        values = _with_retry(ws.get_all_values, value_render_option="UNFORMATTED_VALUE")
        if not values or len(values) < 1:
            df = pd.DataFrame()
            df.attrs["error"] = None
            return df

        headers = _dedupe_headers(values[0])
        body = values[1:]
        df = pd.DataFrame(body, columns=headers)
        df = df.replace("", pd.NA)  # blank cells -> NA instead of empty string
        df.attrs["error"] = None
        return df
    except gspread.exceptions.WorksheetNotFound:
        df = pd.DataFrame()
        df.attrs["error"] = f"Tab '{tab_name}' not found in this sheet."
        return df
    except Exception as e:  # noqa: BLE001 — surface any auth/API error to the UI
        df = pd.DataFrame()
        if _is_rate_limit_error(e):
            df.attrs["error"] = (
                f"Could not load '{tab_name}': Google Sheets API rate limit hit, even "
                f"after retrying. Try 'Refresh now' again in a minute, or see the "
                f"README's note on requesting a quota increase."
            )
        else:
            df.attrs["error"] = f"Could not load '{tab_name}': {e}"
        return df


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def list_tabs(sheet_url: str) -> list[str]:
    """List every tab name in a given Google Sheet (for the Raw Explorer)."""
    if not sheet_url or sheet_url.startswith("PASTE_"):
        return []
    try:
        sh = _open_spreadsheet(sheet_url)
        return [ws.title for ws in _with_retry(sh.worksheets)]
    except Exception:
        return []


def clear_cache():
    st.cache_data.clear()
    st.cache_resource.clear()
