# SPDX-License-Identifier: AGPL-3.0-or-later
"""Optional Google Drive backup of receipt images, organised by business entity.

Uses **OAuth 2.0** (not a service account): a service account has no personal
Drive storage quota, so creating files in a normal Google Drive fails with
``storageQuotaExceeded``. Instead the admin connects their own Google account
once. Dilbyrt then keeps a top-level ``Dilbyrt`` folder, a subfolder per
business entity, and uploads each receipt image named

    YYYY-MM-DD_business-entity-name_receipt-vendor.<ext>

A receipt split across several entities is copied into each entity's folder.

Setup (one time, admin):
  1. Google Cloud console → create/pick a project → enable the **Google Drive
     API** → OAuth consent screen (External, add yourself as a test user) →
     Credentials → create an **OAuth client ID** of type *Web application*.
  2. Add the redirect URI shown in Dilbyrt → Settings → Google to the client's
     "Authorized redirect URIs". (Google requires HTTPS except for localhost.)
  3. Paste the client ID + secret into Settings, save, then click
     **Connect Google Drive** and approve.

The ``drive.file`` scope means Dilbyrt only ever sees the files/folders it
creates — it can't read the rest of your Drive.
"""
import os
import re
from datetime import datetime
from urllib.parse import urlencode

from flask import current_app, url_for

from .crypto import decrypt, encrypt
from .models import BusinessEntity, SiteSetting, db

OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
SCOPES = ["openid", "email", "https://www.googleapis.com/auth/drive.file"]
FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT_FOLDER_NAME = "Dilbyrt"


def libs_available():
    try:
        import googleapiclient.discovery  # noqa: F401
        import google.oauth2.credentials  # noqa: F401
        return True
    except Exception:
        return False


def _site():
    return SiteSetting.query.first()


def client_creds(site=None):
    site = site or _site()
    cid = (site.google_oauth_client_id or "") if site else ""
    secret = (decrypt(site.google_oauth_client_secret_enc)
              if (site and site.google_oauth_client_secret_enc) else "")
    return cid, secret


def is_configured(site=None):
    cid, secret = client_creds(site)
    return bool(cid and secret)


def is_connected(site=None):
    site = site or _site()
    return bool(site and site.google_drive_refresh_token_enc)


def is_active(site=None):
    """Uploads happen only when enabled, connected, and the libs are present."""
    site = site or _site()
    return bool(site and site.google_drive_enabled
                and is_connected(site) and libs_available())


def redirect_uri():
    return url_for("main.google_callback", _external=True)


def authorize_url():
    cid, _ = client_creds()
    return OAUTH_AUTH_URL + "?" + urlencode({
        "client_id": cid,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",       # ask for a refresh token
        "prompt": "consent",            # force refresh-token issuance
        "include_granted_scopes": "true",
    })


def exchange_code(code):
    """Exchange the OAuth code for tokens; persist the refresh token + email.
    Returns (ok, message)."""
    import requests
    cid, secret = client_creds()
    if not (cid and secret):
        return False, "Google OAuth client isn't configured."
    try:
        data = requests.post(OAUTH_TOKEN_URL, data={
            "code": code, "client_id": cid, "client_secret": secret,
            "redirect_uri": redirect_uri(), "grant_type": "authorization_code",
        }, timeout=15).json()
    except Exception as exc:  # noqa: BLE001
        return False, f"Token exchange failed: {exc}"
    if data.get("error"):
        return False, f"Google rejected the connection: {data.get('error_description') or data['error']}"
    refresh = data.get("refresh_token")
    access = data.get("access_token")
    if not refresh:
        return False, ("Google didn't return a refresh token. Remove Dilbyrt "
                       "from your account's third-party access and reconnect.")
    email = ""
    try:
        email = requests.get(USERINFO_URL, timeout=10,
                             headers={"Authorization": f"Bearer {access}"}).json().get("email", "")
    except Exception:  # noqa: BLE001
        pass
    site = _site()
    site.google_drive_refresh_token_enc = encrypt(refresh)
    site.google_drive_account_email = email
    site.google_drive_root_id = None   # re-resolve the folder tree lazily
    db.session.commit()
    return True, "Connected to Google Drive" + (f" ({email})." if email else ".")


def disconnect():
    site = _site()
    site.google_drive_refresh_token_enc = None
    site.google_drive_account_email = None
    site.google_drive_root_id = None
    for e in BusinessEntity.query.all():
        e.drive_folder_id = None       # rebuild folder ids on next connect
    db.session.commit()


# ── Drive API helpers ─────────────────────────────────────────────────────
def _service(site):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    cid, secret = client_creds(site)
    creds = Credentials(
        token=None,
        refresh_token=decrypt(site.google_drive_refresh_token_enc),
        token_uri=OAUTH_TOKEN_URL,
        client_id=cid, client_secret=secret, scopes=SCOPES,
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_folder(svc, name, parent=None):
    q = [f"mimeType='{FOLDER_MIME}'", "trashed=false",
         "name='%s'" % name.replace("\\", "\\\\").replace("'", "\\'")]
    if parent:
        q.append(f"'{parent}' in parents")
    res = svc.files().list(q=" and ".join(q), spaces="drive",
                           fields="files(id)", pageSize=5).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _ensure_folder(svc, name, parent=None):
    fid = _find_folder(svc, name, parent)
    if fid:
        return fid
    meta = {"name": name, "mimeType": FOLDER_MIME}
    if parent:
        meta["parents"] = [parent]
    return svc.files().create(body=meta, fields="id").execute()["id"]


def _root_id(svc, site):
    if site.google_drive_root_id:
        return site.google_drive_root_id
    rid = _ensure_folder(svc, ROOT_FOLDER_NAME)
    site.google_drive_root_id = rid
    db.session.commit()
    return rid


def _entity_folder_id(svc, site, entity, root_id):
    if entity.drive_folder_id:
        return entity.drive_folder_id
    fid = _ensure_folder(svc, entity.name, root_id)
    entity.drive_folder_id = fid
    db.session.commit()
    return fid


# ── naming ────────────────────────────────────────────────────────────────
def _slug(text):
    s = re.sub(r"[^\w\s-]", "", (text or "").strip())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s.lower() or "unknown"


def build_filename(receipt, entity_name, ext):
    """YYYY-MM-DD_business-entity-name_receipt-vendor.ext"""
    when = receipt.purchased_at or receipt.created_at or datetime.utcnow()
    return "%s_%s_%s.%s" % (when.strftime("%Y-%m-%d"),
                            _slug(entity_name),
                            _slug(receipt.vendor_name) or "receipt", ext)


def target_entities(receipt):
    """Entities whose Drive folder should receive a copy of the image —
    every entity this receipt is allocated to (single, even-split, or
    itemized)."""
    ids = list(receipt.entity_allocations().keys())
    if not ids:
        return []
    ents = {e.id: e for e in
            BusinessEntity.query.filter(BusinessEntity.id.in_(ids)).all()}
    return [ents[i] for i in ids if i in ents]


def upload_receipt(receipt):
    """Copy the receipt image into each allocated entity's Drive folder.
    Returns (count, message). Never raises — a Drive failure must not block
    saving the receipt."""
    site = _site()
    if not is_active(site) or not receipt.image_filename:
        return 0, ""
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], receipt.image_filename)
    if not os.path.exists(path):
        return 0, ""
    ents = target_entities(receipt)
    if not ents:
        return 0, "Not backed up to Drive yet — assign the receipt to a business."
    ext = (receipt.image_filename.rsplit(".", 1)[-1].lower()
           if "." in receipt.image_filename else "jpg")
    try:
        from googleapiclient.http import MediaFileUpload
        svc = _service(site)
        root = _root_id(svc, site)
        count = 0
        for e in ents:
            folder = _entity_folder_id(svc, site, e, root)
            svc.files().create(
                body={"name": build_filename(receipt, e.name, ext), "parents": [folder]},
                media_body=MediaFileUpload(path, resumable=False),
                fields="id").execute()
            count += 1
        return count, "Backed up to %d Drive folder%s." % (count, "" if count == 1 else "s")
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Google Drive upload failed")
        return 0, f"Saved, but the Google Drive backup failed: {exc}"
