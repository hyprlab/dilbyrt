# Dilbyrt

A small, self-hosted web app for tracking business receipts. Snap a photo of
a receipt or invoice, let OCR read it into fields, correct anything it got
wrong, and split the cost across one or more businesses. Export to CSV/Excel
or push straight into a Google Sheet you can edit on a Chromebook.

Built with Flask + SQLite, containerised with Docker. It shares its design
language, auth model, and security posture with the Trusted Servants Pro app.

## Features

- **Photo → fields via OCR.** Take a receipt photo on your phone; Tesseract
  reads it and auto-fills vendor, date/time, city/state, line items, subtotal,
  tax, and grand total. Every field stays editable.
- **Manual entry & editing** for anything OCR misses or for paper you'd rather
  type in. The original image is stored with the record.
- **Cost splitting.** Assign a whole receipt to one business, split it evenly
  (50/50 or more), or itemize — billing each line item to its own business.
- **Live search** across vendors, locations, notes, and businesses (⌘K / Ctrl-K).
- **Exports.** Download CSV or Excel (both open cleanly in Google Sheets), or
  push directly to a Google Sheet when a service-account key is configured.
- **Google Drive backup.** Optionally copy each new receipt image into per-business
  folders on your Drive (split receipts land in every business's folder).
- **Users, roles & permissions** — viewer / editor / admin.
- **Cloudflare Turnstile** bot-check on the login screen (optional, per-instance).
- **Light / dark theme**, fully mobile-responsive, brute-force login lockout,
  CSRF protection, encrypted secret storage, and hardened security headers.

## Run from Docker Hub (no build)

The image is published as [`hyprlab/dilbyrt`](https://hub.docker.com/r/hyprlab/dilbyrt).
You don't need to clone the repo — just grab the compose file and an env file:

```bash
curl -O https://raw.githubusercontent.com/hyprlab/dilbyrt/main/docker-compose.hub.yml
curl -o .env https://raw.githubusercontent.com/hyprlab/dilbyrt/main/.env.example
# edit .env: set DILBYRT_SECRET_KEY and DILBYRT_ADMIN_PASSWORD
docker compose -f docker-compose.hub.yml up -d
```

Or run it directly:

```bash
docker run -d --name dilbyrt -p 8099:8000 -v "$PWD/data:/data" \
  -e DILBYRT_SECRET_KEY="$(openssl rand -base64 48)" \
  -e DILBYRT_ADMIN_PASSWORD=change-me \
  -e DILBYRT_SECURE_COOKIES=0 \
  hyprlab/dilbyrt:latest
```

Then open <http://localhost:8099> and sign in with the admin credentials.

## Quick start (build from source)

```bash
cp .env.example .env
# edit .env: set DILBYRT_SECRET_KEY and DILBYRT_ADMIN_PASSWORD
docker compose up -d --build
```

Then open <http://localhost:8099> and sign in with the admin credentials from
your `.env`. Change the password after first login (Users → your account).

Data (SQLite DB + uploaded receipt images + the encryption key) lives in
`./data`, which is bind-mounted into the container — back up that folder.

## Local development (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# OCR needs the tesseract binary on your PATH:
#   Debian/Ubuntu: sudo apt install tesseract-ocr
#   macOS:         brew install tesseract
export DILBYRT_DEBUG=1 DILBYRT_ADMIN_PASSWORD=admin DILBYRT_SECRET_KEY=dev
python run.py     # http://localhost:8000  (admin / admin)
```

Without Tesseract installed the app still runs — OCR simply falls back to
manual entry and the scan panel says so.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `DILBYRT_SECRET_KEY` | — (required in prod) | Flask session/CSRF signing key. |
| `DILBYRT_ADMIN_USERNAME` | `admin` | First-boot admin username. |
| `DILBYRT_ADMIN_PASSWORD` | — (required in prod) | First-boot admin password. |
| `DILBYRT_ADMIN_EMAIL` | `admin@example.com` | First-boot admin email. |
| `DILBYRT_DEBUG` | off | Dev mode: HTTP cookies, Flask debug, default admin pw. |
| `DILBYRT_SECURE_COOKIES` | `0` in compose | Set to `1` when serving over HTTPS. Leave `0` for plain-HTTP access (otherwise browsers drop the session cookie and login fails with "CSRF session token is missing"). |
| `DILBYRT_MAX_UPLOAD_MB` | `64` | Max upload size for receipt images. |
| `DILBYRT_TRUSTED_PROXIES` | `1` | Reverse-proxy hop count for real client IPs. |
| `DILBYRT_FERNET_KEY` | auto | Key for encrypting secrets; auto-generated in `./data` if unset. |
| `DILBYRT_GOOGLE_SA_KEY` | — | Path to a Google service-account JSON key (enables live Sheets sync). |

Turnstile keys are configured in-app under **Settings** (admin only), not via
env — the secret key is stored encrypted at rest.

## Cloudflare Turnstile

1. In your Cloudflare dashboard → **Turnstile**, create a widget for your
   domain and copy the **Site key** and **Secret key**.
2. In Dilbyrt → **Settings → Cloudflare Turnstile**, paste both keys and tick
   *Enable*. Both keys must be present before it can be turned on.

## Getting data into Google Sheets

**The easy way (no setup):** on the Receipts page, **Export → CSV** or
**Excel**. In Google Drive choose *New → File upload*, then open the file with
Google Sheets. Each business allocation is its own row, so per-business totals
sum correctly with a pivot table or `SUMIF`.

**Live sync (optional):** push rows straight into an existing sheet.

1. In the [Google Cloud console](https://console.cloud.google.com/): create a
   project → enable the **Google Sheets API** → create a **service account** →
   add a **JSON key** and download it.
2. Put the key in `./data/google_sa.json` and set
   `DILBYRT_GOOGLE_SA_KEY=/data/google_sa.json` in `docker-compose.yml`
   (uncomment the line), then `docker compose up -d`.
3. Create a Google Sheet, **Share** it (Editor) with the service account's
   email (from the JSON key), and copy the sheet **ID** (the long token in its
   URL between `/d/` and `/edit`).
4. Paste that ID into Dilbyrt → **Settings → Google → Google Sheets sync** and save.
5. On the Receipts page, **Export → Push to Google Sheet** now writes the data
   into a `Receipts` tab you can edit from your Chromebook.

## Google Drive backup of receipt images

When a new receipt is saved, Dilbyrt can copy its image into your Google Drive,
organised by business: a top-level **`Dilbyrt`** folder containing a subfolder
per business entity, with files named
`YYYY-MM-DD_business-entity-name_receipt-vendor.<ext>`. Receipts split across
multiple businesses are copied into **each** business's folder.

This uses **OAuth** (you connect your own Google account) rather than a service
account — a service account has no personal-Drive storage and its uploads fail.
The `drive.file` scope means Dilbyrt only ever sees the folders/files it
creates, never the rest of your Drive.

One-time setup (admin):

1. In the [Google Cloud console](https://console.cloud.google.com/): create/pick
   a project → enable the **Google Drive API** → configure the **OAuth consent
   screen** (User type *External*; add your Google account under *Test users*).
2. **Credentials → Create credentials → OAuth client ID → Web application.**
   Copy the **Authorized redirect URI** shown in Dilbyrt → **Settings → Google →
   Google Drive backup → OAuth client setup** into the client's *Authorized
   redirect URIs*. Google requires **HTTPS** for this URI (except `localhost`),
   so Drive backup needs Dilbyrt served over HTTPS or accessed at `localhost`.
3. Paste the **client ID** and **client secret** into that same panel and
   **Save Google settings**.
4. Click **Connect Google Drive** and approve. Tick **Back up new receipts to
   Google Drive** (auto-enabled on connect).

From then on, saving a new receipt uploads its image to the right folder(s). The
backup is best-effort — if Drive is unreachable the receipt still saves and you
get a warning. (Backup runs on receipt *creation*; edits don't re-upload.)

## Roles

- **Viewer** — browse receipts and run exports.
- **Editor** — plus create/edit/delete receipts and businesses.
- **Admin** — plus manage users and settings.

## Backups

Everything persistent is in `./data` (`dilbyrt.db`, `uploads/`, `dilbyrt.key`).
Stop the container (or just copy live — SQLite tolerates it for small apps) and
archive that directory.

## License

Dilbyrt is free software licensed under the **GNU Affero General Public
License v3.0 or later** (AGPL-3.0-or-later). See [`LICENSE`](LICENSE) for the
full text. In short: you may use, modify, and redistribute it, but if you run a
modified version as a network service you must make your source available to
its users.
