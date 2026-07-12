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
| `DILBYRT_BASE_URL` | — | Public base URL (e.g. `https://dilbyrt.example.com`); used to build the exact OAuth redirect URI for Drive. |
| `DILBYRT_GOOGLE_CLIENT_ID` | — | Central OAuth client ID for per-user Google Drive backup. |
| `DILBYRT_GOOGLE_CLIENT_SECRET` | — | Central OAuth client secret for Drive backup. |

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

## Google Drive backup of receipt images (per-user)

Each user can connect **their own** Google Drive with one click (**Account →
Connect Google Drive**). When they save a new receipt, its image is copied into
a top-level **`Dilbyrt`** folder in their Drive, under a subfolder per business,
named `YYYY-MM-DD_business-entity-name_receipt-vendor.<ext>`. Receipts split
across multiple businesses are copied into **each** business's folder.

It uses **OAuth** (not a service account — those have no personal-Drive storage
and their uploads fail), with the `drive.file` scope, so Dilbyrt only ever sees
the folders/files it creates in each user's Drive.

### One-time server setup (operator)

You register **one** central OAuth client; end-users never touch Google Cloud.

1. In the [Google Cloud console](https://console.cloud.google.com/): create/pick
   a project → enable the **Google Drive API** → configure the **OAuth consent
   screen** (User type *External*; add a privacy-policy URL if publishing).
2. **Credentials → Create credentials → OAuth client ID → Web application.** Add
   this exact **Authorized redirect URI**: `https://<your-domain>/account/google/callback`
   (shown in Dilbyrt → **Settings → Google**). Google requires **HTTPS** here
   (except `localhost`), so Drive backup needs Dilbyrt served over HTTPS.
3. Provide the client to Dilbyrt via env (see `docker-compose.yml`):

   ```
   DILBYRT_BASE_URL=https://your-domain
   DILBYRT_GOOGLE_CLIENT_ID=…apps.googleusercontent.com
   DILBYRT_GOOGLE_CLIENT_SECRET=GOCSPX-…
   ```

While the consent screen is in **Testing**, add each user as a *Test user*
(max 100) — they'll see a one-time "unverified app" screen. Publishing the app
removes that; because Dilbyrt only uses the non-sensitive `drive.file` scope you
need Google's lightweight brand verification, **not** the costly restricted-scope
security assessment.

### For each user

Open **Account** (click your name in the sidebar) → **Connect Google Drive** →
approve. From then on, receipts *they* create back up to *their* Drive. Backup is
best-effort (a Drive outage never blocks a save) and runs on receipt
**creation** only (edits don't re-upload).

## Per-user data isolation

Each user has a private workspace: they see only **their own** receipts and
businesses, and can't view or reference anyone else's. Two users can even have
businesses with the same name. **Admins are the exception** — an admin sees and
can manage every user's receipts and businesses (plus users and settings).

## Roles

- **Viewer** — browse *their own* receipts and run exports.
- **Editor** — plus create/edit/delete *their own* receipts and businesses,
  and connect their own Google Drive.
- **Admin** — sees/manages **everything** (all users' receipts and businesses),
  plus manages users and site settings.

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
