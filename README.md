# Marketplace DRR Dashboard

A Streamlit dashboard that connects **live** to your team's Google Sheets
(Amazon, Blinkit, Flipkart, Meesho, Myntra, Nykaa, Purplle, Zepto + the
Master Sheet) and shows:

- **Overview** — combined daily run-rate (DRR: units + revenue) across all channels
- **Channel Deep-Dive** — per-channel trend, top brands, top SKUs
- **Ad Spends & ROAS** — Blinkit & Zepto spend/ROAS trends, Myntra style performance
- **Pricing** — Master Sheet's per-channel pricing tabs
- **Raw Sheet Explorer** — browse *any* tab in *any* configured sheet, with search

Because your team updates the Google Sheets directly, the dashboard needs
no manual file uploads — it re-reads the sheets automatically every 5
minutes, and there's a "Refresh now" button for instant updates.

---

## 1. One-time setup: give the app access to your Google Sheets

Streamlit can't just open your private Google Sheets — it needs a
**service account** (a robot Google account) that you explicitly share
each sheet with.

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create
   a project (or use an existing one).
2. Enable two APIs: **Google Sheets API** and **Google Drive API**
   (APIs & Services → Library → search each → Enable).
3. Create a service account: APIs & Services → Credentials → Create
   Credentials → Service Account. Give it any name, e.g. `drr-dashboard`.
4. Open the new service account → Keys → Add Key → Create new key → JSON.
   This downloads a `.json` file — keep it safe, it's a password.
5. Copy the `client_email` field from that JSON (looks like
   `drr-dashboard@your-project.iam.gserviceaccount.com`).
6. **Open every one of your 8 channel Google Sheets + the Master Sheet**,
   click Share, and paste in that service account email with **Viewer**
   access.

## 2. Configure the app

1. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`.
2. Open the JSON key file you downloaded in step 1.4, and copy each value
   into the matching field in `secrets.toml` (`private_key`, `client_email`,
   etc.). Keep the `\n` characters in `private_key` exactly as they are.
3. Open `config.py` and paste each channel's real Google Sheet URL where
   you see `PASTE_..._URL_HERE`, and do the same for the Master Sheet.
4. Check the tab names listed in `config.py` (e.g. `dump_tabs`) match the
   real tab names in your sheets. **Meesho and Purplle get a new tab every
   month** — add each new month's tab name to the list as it's created.

## 3. Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens in your browser at `http://localhost:8501`.

## 4. Deploy it so your whole team can access it

Easiest option — [Streamlit Community Cloud](https://streamlit.io/cloud) (free):

1. Push this folder to a GitHub repo (**do not commit `secrets.toml`** —
   it's already listed in `.gitignore`).
2. On share.streamlit.io, click "New app", point it at your repo/`app.py`.
3. In the app's Settings → Secrets, paste the contents of your
   `secrets.toml` file.
4. Deploy. Share the resulting URL with your team.

---

## How updates flow through

```
Your team edits a channel's Google Sheet (or an automated feed updates it)
        ↓
Dashboard re-reads that sheet (auto every 5 min, or instantly via "Refresh now")
        ↓
Charts, KPIs, and tables update automatically — no file uploads, ever
```

## Adding a new channel later

1. Add an entry to `CHANNELS` in `config.py` with its `sheet_url` and
   `dump_tabs`.
2. Add a matching entry to `COLUMN_MAP` telling the pipeline which raw
   column holds the date, units, revenue, brand, product, and SKU.
3. That's it — it will show up in every tab of the dashboard automatically.

## Troubleshooting

- **"Could not load '...'"** in a warning box → usually means the sheet
  hasn't been shared with the service account email, or the tab name in
  `config.py` doesn't exactly match the real tab name (check for trailing
  spaces / capitalization).
- **Numbers look off** → check `COLUMN_MAP` in `config.py` against the
  actual column headers in that channel's sheet — marketplaces sometimes
  rename export columns.
- **A whole channel is blank** → open the Raw Sheet Explorer tab, pick that
  channel + tab, and see the raw data as-is to debug.
