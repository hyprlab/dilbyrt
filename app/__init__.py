# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dilbyrt application factory.

A small Flask app for scanning, tracking and splitting business receipts.
Mirrors the architecture of the Trusted Servants Pro app (Flask factory,
SQLAlchemy, Flask-Login, CSRF, Turnstile, security headers, light/dark
theming) at a scale appropriate to a single-purpose tool.
"""
import os
from datetime import datetime, timedelta

from flask import Flask, request
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from .models import User, db

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"
csrf = CSRFProtect()


def create_app():
    app = Flask(__name__, instance_relative_config=False)
    app.url_map.strict_slashes = False

    # Honour X-Forwarded-* when behind a reverse proxy (Caddy/nginx/Cloudflare).
    try:
        hops = int(os.environ.get("DILBYRT_TRUSTED_PROXIES", "1"))
    except ValueError:
        hops = 1
    if hops > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)

    data_dir = os.path.abspath(os.environ.get(
        "DILBYRT_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")))
    upload_dir = os.path.abspath(os.environ.get(
        "DILBYRT_UPLOAD_DIR", os.path.join(data_dir, "uploads")))
    login_bg_dir = os.path.abspath(os.environ.get(
        "DILBYRT_LOGIN_BG_DIR", os.path.join(data_dir, "login_bg")))
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(upload_dir, exist_ok=True)
    os.makedirs(login_bg_dir, exist_ok=True)

    is_debug = os.environ.get("DILBYRT_DEBUG", "").lower() in ("1", "true", "yes")
    secret_key = os.environ.get("DILBYRT_SECRET_KEY", "").strip()
    if not secret_key or secret_key == "dev-secret-change-me":
        if is_debug:
            secret_key = secret_key or "dev-secret-change-me"
        else:
            raise RuntimeError(
                "DILBYRT_SECRET_KEY is required. Set a random 32+ byte value "
                "via environment variable.")

    # Secure-cookie flag. Independent of debug so an HTTP LAN deploy can work
    # without turning on Flask tracebacks. Browsers drop `Secure` cookies over
    # plain HTTP on any host other than localhost/127.0.0.1 — which silently
    # breaks login with "CSRF session token is missing". Explicit override wins;
    # otherwise default to on unless in debug.
    _secure_env = os.environ.get("DILBYRT_SECURE_COOKIES", "").strip().lower()
    if _secure_env in ("0", "false", "no"):
        cookie_secure = False
    elif _secure_env in ("1", "true", "yes"):
        cookie_secure = True
    else:
        cookie_secure = not is_debug
    try:
        max_upload_mb = int(os.environ.get("DILBYRT_MAX_UPLOAD_MB", "64"))
    except ValueError:
        max_upload_mb = 64

    app.config.update(
        SECRET_KEY=secret_key,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{os.path.join(data_dir, 'dilbyrt.db')}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        DATA_DIR=data_dir,
        UPLOAD_FOLDER=upload_dir,
        LOGIN_BG_FOLDER=login_bg_dir,
        MAX_CONTENT_LENGTH=max_upload_mb * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(days=90),
        REMEMBER_COOKIE_DURATION=timedelta(days=90),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=cookie_secure,
        REMEMBER_COOKIE_SECURE=cookie_secure,
        REMEMBER_COOKIE_HTTPONLY=True,
        WTF_CSRF_TIME_LIMIT=None,
    )

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .crypto import init_fernet
    init_fernet(app)

    @login_manager.user_loader
    def load_user(user_id):
        u = db.session.get(User, int(user_id))
        if u is not None and getattr(u, "disabled", False):
            return None
        return u

    from .auth import bp as auth_bp
    from .routes import bp as main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    # Template helpers.
    from .icons import icon
    from .version import __version__, __build_id__
    app.jinja_env.globals["icon"] = icon
    app.jinja_env.globals["app_version"] = __version__
    app.jinja_env.globals["app_build_id"] = __build_id__

    # Random login-hero background. Reads the login_bg folder fresh on each
    # render so the picked image changes every time the login page loads;
    # returns None when no images are uploaded (template falls back to the
    # default gradient). Used by templates/login.html.
    import random as _random
    from flask import url_for as _url_for

    def _random_login_bg():
        try:
            files = [f for f in os.listdir(login_bg_dir)
                     if f.rsplit(".", 1)[-1].lower()
                     in ("jpg", "jpeg", "png", "webp", "gif")]
        except OSError:
            files = []
        if not files:
            return None
        return _url_for("main.login_bg", filename=_random.choice(files))
    app.jinja_env.globals["random_login_bg"] = _random_login_bg

    @app.template_filter("money")
    def money(value):
        try:
            return f"{float(value):,.2f}"
        except (ValueError, TypeError):
            return "0.00"

    @app.template_filter("dt")
    def dt(value, fmt="%b %d, %Y"):
        if not isinstance(value, datetime):
            return ""
        return value.strftime(fmt)

    @app.after_request
    def _security_headers(response):
        path = request.path or ""
        if not path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy",
                                    "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(self), payment=()")
        if request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; "
            "frame-src https://challenges.cloudflare.com; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'self'")
        return response

    @app.errorhandler(404)
    def not_found(_e):
        from flask import render_template
        return render_template("404.html"), 404

    with app.app_context():
        from sqlalchemy.exc import OperationalError
        try:
            db.create_all()
        except OperationalError as e:
            if "already exists" not in str(e).lower():
                raise
        _migrate_columns(app)
        _seed_site(app)
        _seed_admin(app)

    return app


def _migrate_columns(app):
    """Add columns introduced after a DB was first created. SQLite's
    create_all() only creates missing *tables*, not missing columns, so new
    nullable columns need an explicit ALTER TABLE. Idempotent + race-tolerant."""
    from sqlalchemy import text
    wanted = {
        "receipt": [("tax_rate", "FLOAT")],
        "site_setting": [
            ("google_drive_enabled", "BOOLEAN DEFAULT 0"),
            ("google_oauth_client_id", "VARCHAR(255)"),
            ("google_oauth_client_secret_enc", "BLOB"),
            ("google_drive_refresh_token_enc", "BLOB"),
            ("google_drive_account_email", "VARCHAR(255)"),
            ("google_drive_root_id", "VARCHAR(128)"),
        ],
        "business_entity": [("drive_folder_id", "VARCHAR(128)")],
    }
    try:
        with db.engine.begin() as conn:
            for table, cols in wanted.items():
                existing = {row[1] for row in conn.execute(
                    text(f"PRAGMA table_info({table})"))}
                for name, coltype in cols:
                    if name not in existing:
                        conn.execute(text(
                            f"ALTER TABLE {table} ADD COLUMN {name} {coltype}"))
                        app.logger.info("Added column %s.%s", table, name)
    except Exception:
        app.logger.exception("column migration failed")


def _seed_site(app):
    # Race-safe: multiple gunicorn workers boot concurrently. If two both see
    # an empty table and insert, the loser hits an IntegrityError — tolerate it.
    from sqlalchemy.exc import IntegrityError
    from .models import SiteSetting
    if SiteSetting.query.first() is None:
        # Name is fixed — the model default ("Dilbyrt") is the only value.
        db.session.add(SiteSetting(id=1))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()


def _seed_admin(app):
    from sqlalchemy.exc import IntegrityError
    if User.query.count() == 0:
        username = os.environ.get("DILBYRT_ADMIN_USERNAME", "admin")
        password = (os.environ.get("DILBYRT_ADMIN_PASSWORD", "") or "").strip()
        email = os.environ.get("DILBYRT_ADMIN_EMAIL", "admin@example.com")
        is_debug = os.environ.get("DILBYRT_DEBUG", "").lower() in ("1", "true", "yes")
        if not password:
            if is_debug:
                password = "admin"
                app.logger.warning("Seeding admin with default password 'admin' "
                                   "(DILBYRT_DEBUG is on). Change it immediately.")
            else:
                raise RuntimeError(
                    "DILBYRT_ADMIN_PASSWORD is required on first boot.")
        u = User(username=username, email=email, role="admin")
        u.set_password(password)
        db.session.add(u)
        try:
            db.session.commit()
            app.logger.info("Seeded admin user: %s", username)
        except IntegrityError:
            # Another worker won the race and already created the admin.
            db.session.rollback()
