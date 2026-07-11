# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-user Google Drive backup of receipt images, organised by business entity.

Multi-user "one-click connect" model:

* A **single, central OAuth client** owned by the operator is configured once
  via env vars (``DILBYRT_GOOGLE_CLIENT_ID`` / ``DILBYRT_GOOGLE_CLIENT_SECRET``).
  No user ever touches Google Cloud.
* Each user connects **their own** Google account from their Account page with
  one click. Dilbyrt stores that user's refresh token (encrypted) on the User
  row.
* When a user saves a new receipt, its image is copied into **their** Drive:
  a top-level ``Dilbyrt`` folder → a subfolder per business entity → files named
  ``YYYY-MM-DD_business-entity-name_receipt-vendor.<ext>``. Split receipts land
  in every allocated business's folder.

Uses OAuth (not a service account) with the ``drive.file`` scope, so Dilbyrt
only ever sees the folders/files it creates in each user's Drive.
"""
import os
import re
from datetime import datetime
from urllib.parse import urlencode

from flask import current_app, url_for

from .crypto import decrypt, encrypt
from .models import BusinessEntity, db

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


def client_creds():
    """The central OAuth client, from operator env config."""
    return (os.environ.get("DILBYRT_GOOGLE_CLIENT_ID", "").strip(),
            os.environ.get("DILBYRT_GOOGLE_CLIENT_SECRET", "").strip())


def is_available():
    """True when the server can offer Drive connect at all (client + libs)."""
    cid, secret = client_creds()
    return bool(cid and secret and libs_available())


def is_connected(user):
    return bool(user is not None and getattr(user, "drive_refresh_token_enc", None))


def redirect_uri():
    """The single, fixed OAuth redirect URI to register on the central client.
    Prefer an explicit base URL so it exactly matches what's registered."""
    base = os.environ.get("DILBYRT_BASE_URL", "").strip().rstrip("/")
    if base:
        return base + url_for("main.account_google_callback")
    return url_for("main.account_google_callback", _external=True)


def authorize_url(state):
    cid, _ = client_creds()
    return OAUTH_AUTH_URL + "?" + urlencode({
        "client_id": cid,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",   # get a refresh token
        "prompt": "consent",        # force refresh-token issuance on reconnect
        "include_granted_scopes": "true",
        "state": state,
    })


def exchange_code(user, code):
    """Exchange the OAuth code for tokens and store them on ``user``.
    Returns (ok, message)."""
    import requests
    cid, secret = client_creds()
    if not (cid and secret):
        return False, "Google Drive isn't configured on this server."
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
    user.drive_refresh_token_enc = encrypt(refresh)
    user.drive_account_email = email
    user.drive_root_id = None   # re-resolve the folder tree lazily
    db.session.commit()
    return True, "Connected your Google Drive" + (f" ({email})." if email else ".")


def disconnect(user):
    user.drive_refresh_token_enc = None
    user.drive_account_email = None
    user.drive_root_id = None
    db.session.commit()


# ── Drive API helpers ─────────────────────────────────────────────────────
def _service(user):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    cid, secret = client_creds()
    creds = Credentials(
        token=None,
        refresh_token=decrypt(user.drive_refresh_token_enc),
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


def _root_id(svc, user):
    if user.drive_root_id:
        return user.drive_root_id
    rid = _ensure_folder(svc, ROOT_FOLDER_NAME)
    user.drive_root_id = rid
    db.session.commit()
    return rid


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
    """Every business entity this receipt is allocated to (single, even-split
    or itemized) — each gets a copy of the image."""
    ids = list(receipt.entity_allocations().keys())
    if not ids:
        return []
    ents = {e.id: e for e in
            BusinessEntity.query.filter(BusinessEntity.id.in_(ids)).all()}
    return [ents[i] for i in ids if i in ents]


def upload_receipt(receipt, user):
    """Copy the receipt image into each allocated entity's folder in ``user``'s
    Drive. Returns (count, message). Never raises — a Drive failure must not
    block saving the receipt."""
    if not is_available() or not is_connected(user) or not receipt.image_filename:
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
        svc = _service(user)
        root = _root_id(svc, user)
        count = 0
        for e in ents:
            folder = _ensure_folder(svc, e.name, root)
            svc.files().create(
                body={"name": build_filename(receipt, e.name, ext), "parents": [folder]},
                media_body=MediaFileUpload(path, resumable=False),
                fields="id").execute()
            count += 1
        return count, "Backed up to your Drive (%d folder%s)." % (count, "" if count == 1 else "s")
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Google Drive upload failed")
        return 0, f"Saved, but the Google Drive backup failed: {exc}"
