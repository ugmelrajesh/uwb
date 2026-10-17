# WeighMaster Pro (Streamlit)

Streamlit port of the Caffeine weighbridge app. Pages: Gate Pass, New Transaction,
Transactions, Reports, Settings.

## Deploy on Streamlit Community Cloud

1. Push this folder to a GitHub repo (`app.py`, `store.py`, `requirements.txt`, `.streamlit/`).
2. Open https://share.streamlit.io, click **Create app**, pick the repo and set the main file to `app.py`.
3. Deploy.

## Run locally

    pip install -r requirements.txt
    streamlit run app.py

## Data

All data is stored in `data/store.json` (override the path with the `WEIGHMASTER_DATA`
environment variable). On Community Cloud this file is temporary and is wiped on reboot or
redeploy. Use **Settings → Backup & restore** to download and restore your data.

The app has no login. Restrict viewers in the app's Share settings on Community Cloud.
