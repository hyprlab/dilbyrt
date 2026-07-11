# SPDX-License-Identifier: MIT
"""Optional Google Sheets sync (service-account based).

Dilbyrt ships with CSV + XLSX export out of the box — those import cleanly
into Google Sheets (upload to Drive → Open with Google Sheets). This module
adds an *optional* live push to an existing spreadsheet so a friend can edit
on a Chromebook without any download step.

It activates only when BOTH of these are provided; otherwise
``sheets_available()`` is False and the UI simply hides the feature:

  1. A service-account JSON key mounted into the container and pointed to by
     the ``DILBYRT_GOOGLE_SA_KEY`` env var (path inside the container).
  2. A target spreadsheet id saved in Settings (SiteSetting.google_sheet_id),
     with the sheet shared (Editor) to the service account's email.

Setup (one time):
  * Google Cloud console → create a project → enable the Google Sheets API.
  * Create a service account → add a JSON key → download it.
  * Mount it into the container and set DILBYRT_GOOGLE_SA_KEY=/data/google_sa.json
  * Create a Google Sheet, Share it (Editor) with the service-account email.
  * Paste the sheet id (the long token in its URL) into Dilbyrt Settings.

The heavy Google client libraries are imported lazily so the app runs fine
without them installed.
"""
import os

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _key_path():
    return (os.environ.get("DILBYRT_GOOGLE_SA_KEY") or "").strip()


def sheets_available():
    """True when a service-account key file is present AND the client libs
    are importable. Does not check the target sheet id (that's per-request)."""
    path = _key_path()
    if not path or not os.path.exists(path):
        return False
    try:
        import google.oauth2.service_account  # noqa: F401
        import googleapiclient.discovery  # noqa: F401
        return True
    except Exception:
        return False


def _service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_service_account_file(_key_path(), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def push_rows(spreadsheet_id, header, rows, tab="Receipts"):
    """Overwrite the target tab with ``header`` + ``rows``.

    Returns (ok, message). Never raises — failures come back as a message
    the caller can flash. Clears the sheet first so deletions propagate.
    """
    if not spreadsheet_id:
        return False, "No Google Sheet id configured in Settings."
    if not sheets_available():
        return False, "Google Sheets sync is not configured on this server."
    try:
        svc = _service().spreadsheets().values()
        svc.clear(spreadsheetId=spreadsheet_id, range=tab).execute()
        body = {"values": [header] + rows}
        svc.update(spreadsheetId=spreadsheet_id, range=f"{tab}!A1",
                   valueInputOption="USER_ENTERED", body=body).execute()
        return True, f"Pushed {len(rows)} row(s) to Google Sheets."
    except Exception as exc:  # pragma: no cover - network/creds dependent
        return False, f"Google Sheets sync failed: {exc}"
