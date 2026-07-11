# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authentication: login, logout, Turnstile verification, brute-force lockout.

Passwords use Werkzeug's PBKDF2 hashing. Cloudflare Turnstile is verified
server-side and fails closed. Failed logins are recorded in the DB on two
dimensions (client IP + username) so lockout survives restarts and is shared
across gunicorn workers.
"""
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin

import requests
from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user, login_user, logout_user
from sqlalchemy import func

from .crypto import decrypt
from .models import LoginFailure, SiteSetting, User, db

bp = Blueprint("auth", __name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

_LOGIN_WINDOW_SECONDS = 900          # 15 minutes
_LOGIN_MAX_FAILURES_IP = 8
_LOGIN_MAX_FAILURES_USER = 5


# ── safe redirect ────────────────────────────────────────────────────────
def _is_safe_url(target):
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


# ── brute-force lockout ──────────────────────────────────────────────────
def _prune_stale():
    cutoff = datetime.utcnow() - timedelta(seconds=_LOGIN_WINDOW_SECONDS)
    LoginFailure.query.filter(LoginFailure.failed_at < cutoff).delete()


def _count(kind, key):
    cutoff = datetime.utcnow() - timedelta(seconds=_LOGIN_WINDOW_SECONDS)
    return (LoginFailure.query
            .filter(LoginFailure.kind == kind, LoginFailure.key == key,
                    LoginFailure.failed_at >= cutoff)
            .count())


def _rate_limited(ip, username):
    """Return (blocked, retry_seconds)."""
    if _count("ip", ip) >= _LOGIN_MAX_FAILURES_IP:
        return True, _LOGIN_WINDOW_SECONDS
    if username and _count("user", username.lower()) >= _LOGIN_MAX_FAILURES_USER:
        return True, _LOGIN_WINDOW_SECONDS
    return False, 0


def _record_failure(ip, username):
    try:
        _prune_stale()
        db.session.add(LoginFailure(kind="ip", key=ip))
        if username:
            db.session.add(LoginFailure(kind="user", key=username.lower()))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _clear_failures(ip, username):
    try:
        LoginFailure.query.filter(
            ((LoginFailure.kind == "ip") & (LoginFailure.key == ip)) |
            ((LoginFailure.kind == "user") & (LoginFailure.key == (username or "").lower()))
        ).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()


# ── Turnstile ────────────────────────────────────────────────────────────
def _verify_turnstile(site, token, remote_ip):
    """Return (ok, error_message). Fails closed on any failure."""
    secret = decrypt(site.turnstile_secret_key_enc) if site.turnstile_secret_key_enc else ""
    if not secret:
        return False, "Turnstile is enabled but no secret key is configured."
    if not token:
        return False, "Please complete the security check."
    try:
        resp = requests.post(
            TURNSTILE_VERIFY_URL,
            data={"secret": secret, "response": token, "remoteip": remote_ip or ""},
            timeout=5,
        )
        data = resp.json()
    except Exception as exc:
        current_app.logger.warning("Turnstile verify failed: %s", exc)
        return False, "Security check failed — please try again."
    if data.get("success"):
        return True, None
    return False, "Security check failed — please try again."


# ── routes ───────────────────────────────────────────────────────────────
@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    site = SiteSetting.query.first()
    ip = request.remote_addr or "unknown"

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter(func.lower(User.username) == username.lower()).first()
        # Admins are exempt from per-username lockout so an attacker can't
        # lock an admin out by name; IP lockout still applies to them.
        lockout_username = None if (user and user.is_admin()) else username

        blocked, retry = _rate_limited(ip, lockout_username)
        if blocked:
            flash(f"Too many failed attempts. Try again in "
                  f"{max(retry, 1) // 60 + 1} minutes.", "danger")
            return render_template("login.html", site=site), 429

        if site and site.turnstile_enabled and site.turnstile_site_key:
            token = request.form.get("cf-turnstile-response", "")
            ok, err = _verify_turnstile(site, token, ip)
            if not ok:
                _record_failure(ip, lockout_username)
                flash(err, "danger")
                return render_template("login.html", site=site)

        if user and not user.disabled and user.check_password(password):
            _clear_failures(ip, lockout_username)
            session.permanent = True
            login_user(user, remember=bool(request.form.get("remember")))
            user.last_seen_at = datetime.utcnow()
            db.session.commit()
            nxt = request.args.get("next") or request.form.get("next")
            return redirect(nxt if _is_safe_url(nxt) else url_for("main.index"))

        _record_failure(ip, lockout_username)
        flash("Invalid credentials.", "danger")
        return render_template("login.html", site=site)

    return render_template("login.html", site=site)


@bp.route("/logout")
def logout():
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))
