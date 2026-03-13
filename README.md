# Grant Research Dashboard

A Streamlit dashboard for your org to browse, filter, track and visualise grant opportunities pulled live from Google Sheets.

## Quick Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Connecting your Google Sheet

### Option A — Public sheet (simplest)
1. Open your Google Sheet
2. **File → Share → Publish to web** → choose "CSV" → Publish
3. OR: **Share → Anyone with the link → Viewer**
4. Select **"Public sheet (CSV)"** in the sidebar (default)

### Option B — Private sheet (via service account)
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable **Google Sheets API** and **Google Drive API**
3. Create a **Service Account** → Download JSON key
4. Share your Google Sheet with the service account email (Viewer access)
5. Select **"Service account (private sheet)"** in the sidebar and upload the JSON key

## Deploying to Streamlit Cloud (share with your org)
1. Push this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repo → select `app.py`
4. If using a service account, add the JSON contents as a **Secret** in Streamlit Cloud settings:
   - Key: `GOOGLE_CREDS`
   - Value: paste the entire JSON

## Expected Sheet Columns
| Column | Description |
|--------|-------------|
| Rank | Numeric priority rank |
| Score | Match score (0–100) |
| Grant Name | Name of the grant |
| Grant ID | Internal or external ID |
| Funder | Organisation providing funding |
| Next Deadline | Date (any parseable format) |
| Status | e.g. Active, Applied, Awarded, Declined |
| Is Custom | TRUE/FALSE — whether a custom application is needed |
| Rolling | TRUE/FALSE — rolling deadline |
| Funding Cycle | Annual, Biannual, Rolling, etc. |
| Grant URL | Full URL to grant page |
| Description | Free text description |
| Locations | Comma-separated list of eligible locations |
