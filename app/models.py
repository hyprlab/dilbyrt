# SPDX-License-Identifier: AGPL-3.0-or-later
"""Database models for Dilbyrt — receipt & invoice tracking.

SQLite via Flask-SQLAlchemy. The schema is intentionally small:

  User            — accounts + roles (viewer / editor / admin)
  SiteSetting     — single-row app config (Turnstile keys, site name, sheet id)
  LoginFailure    — DB-backed brute-force lockout buckets (IP + username)
  BusinessEntity  — the businesses a receipt / item can be billed to
  Receipt         — one scanned or hand-entered receipt + its stored image
  ReceiptItem     — a single line item, optionally billed to its own entity
"""
from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), nullable=False, default="viewer")
    name = db.Column(db.String(120))
    disabled = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    @property
    def is_active(self):  # Flask-Login: disabled accounts can't log in
        return not self.disabled

    def is_admin(self):
        return self.role == "admin"


class SiteSetting(db.Model):
    """Single-row settings table (id is always 1)."""
    id = db.Column(db.Integer, primary_key=True)
    site_name = db.Column(db.String(120), nullable=False, default="Dilbyrt")

    # Cloudflare Turnstile — site key is public (plaintext); secret is
    # Fernet-encrypted at rest. Turnstile only engages when enabled AND
    # both keys are present.
    turnstile_enabled = db.Column(db.Boolean, nullable=False, default=False)
    turnstile_site_key = db.Column(db.String(128))
    turnstile_secret_key_enc = db.Column(db.LargeBinary)

    # Optional Google Sheets sync (activates when a service-account key is
    # mounted and a target spreadsheet id is set — see app/sheets.py).
    google_sheet_id = db.Column(db.String(128))

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LoginFailure(db.Model):
    """One row per failed login attempt, pruned lazily. Tracked on two
    dimensions — client IP and lowercased username — so both single-IP
    spraying and distributed attacks on one account trip the lockout."""
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(8), nullable=False)   # 'ip' or 'user'
    key = db.Column(db.String(255), nullable=False)
    failed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        db.Index("ix_loginfailure_lookup", "kind", "key", "failed_at"),
    )


class BusinessEntity(db.Model):
    """A business a receipt (or individual line item) is billed to."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), unique=True, nullable=False)
    color = db.Column(db.String(9), default="#0b5cff")   # chip colour, hex
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<BusinessEntity {self.name}>"


class Receipt(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    vendor_name = db.Column(db.String(200), default="")
    purchased_at = db.Column(db.DateTime)          # date/time on the receipt
    city = db.Column(db.String(120), default="")
    state = db.Column(db.String(64), default="")

    subtotal = db.Column(db.Float, default=0.0)
    tax = db.Column(db.Float, default=0.0)
    grand_total = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(8), default="USD")

    notes = db.Column(db.Text, default="")

    # Stored receipt image + the raw OCR text it was parsed from.
    image_filename = db.Column(db.String(255))
    ocr_text = db.Column(db.Text)

    # How the receipt total is apportioned to businesses:
    #   'single'   — whole receipt → entity_id
    #   'even'      — split evenly across the entities in split_entity_ids
    #   'itemized'  — each ReceiptItem carries its own entity_id
    split_mode = db.Column(db.String(16), nullable=False, default="single")
    entity_id = db.Column(db.Integer, db.ForeignKey("business_entity.id"))
    split_entity_ids = db.Column(db.String(255), default="")  # CSV of entity ids for 'even'

    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    entity = db.relationship("BusinessEntity", foreign_keys=[entity_id])
    creator = db.relationship("User", foreign_keys=[created_by])
    items = db.relationship(
        "ReceiptItem", backref="receipt", cascade="all, delete-orphan",
        order_by="ReceiptItem.id")

    def split_ids(self):
        """Parsed list of entity ids for the 'even' split mode."""
        if not self.split_entity_ids:
            return []
        out = []
        for tok in self.split_entity_ids.split(","):
            tok = tok.strip()
            if tok.isdigit():
                out.append(int(tok))
        return out

    def entity_allocations(self):
        """Return {entity_id: amount} apportioning grand_total per split_mode.

        Falls back to an empty dict when the receipt is unassigned, so
        callers can treat "no allocation" uniformly.
        """
        total = self.grand_total or 0.0
        if self.split_mode == "single" and self.entity_id:
            return {self.entity_id: round(total, 2)}
        if self.split_mode == "even":
            ids = self.split_ids()
            if not ids:
                return {}
            share = round(total / len(ids), 2)
            alloc = {eid: share for eid in ids}
            # Push any rounding remainder onto the first entity so the
            # allocations always sum exactly to grand_total.
            drift = round(total - share * len(ids), 2)
            if drift:
                alloc[ids[0]] = round(alloc[ids[0]] + drift, 2)
            return alloc
        if self.split_mode == "itemized":
            alloc = {}
            for it in self.items:
                if it.entity_id:
                    alloc[it.entity_id] = round(
                        alloc.get(it.entity_id, 0.0) + (it.line_total()), 2)
            return alloc
        return {}


class ReceiptItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey("receipt.id"), nullable=False)
    description = db.Column(db.String(300), default="")
    qty = db.Column(db.Float, default=1.0)
    cost = db.Column(db.Float, default=0.0)   # unit cost
    entity_id = db.Column(db.Integer, db.ForeignKey("business_entity.id"))

    entity = db.relationship("BusinessEntity", foreign_keys=[entity_id])

    def line_total(self):
        return round((self.qty or 1.0) * (self.cost or 0.0), 2)
