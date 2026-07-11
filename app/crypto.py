# SPDX-License-Identifier: MIT
"""Symmetric encryption for at-rest secrets (the Turnstile secret key).

Adapted from the Trusted Servants Pro pattern. A single Fernet cipher is
built at app boot and stashed on ``app.config["FERNET"]``. The key is
sourced, in order, from:

  1. the ``DILBYRT_FERNET_KEY`` environment variable,
  2. a ``dilbyrt.key`` file in the data dir (created + chmod 600 on first run),
  3. a freshly generated key, persisted to that file.

``decrypt`` never raises — a rotated/corrupt key makes previously-stored
secrets read back as ``""`` rather than crashing the request.
"""
import os
from cryptography.fernet import Fernet
from flask import current_app


def init_fernet(app):
    key = os.environ.get("DILBYRT_FERNET_KEY")
    if not key:
        data_dir = app.config.get("DATA_DIR") or os.path.dirname(
            app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", ""))
        path = os.path.join(data_dir, "dilbyrt.key")
        if os.path.exists(path):
            with open(path, "rb") as f:
                key = f.read().decode()
        else:
            key = Fernet.generate_key().decode()
            with open(path, "wb") as f:
                f.write(key.encode())
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
    app.config["FERNET"] = Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str) -> bytes:
    return current_app.config["FERNET"].encrypt((value or "").encode())


def decrypt(token: bytes) -> str:
    if not token:
        return ""
    try:
        return current_app.config["FERNET"].decrypt(token).decode()
    except Exception:
        current_app.logger.warning(
            "Fernet decrypt failed — encrypted column unreadable (key rotated?)")
        return ""
