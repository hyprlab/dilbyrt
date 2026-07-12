# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server-side live search across receipts and business entities.

A query is tokenised on whitespace; every token must match at least one
column (AND across tokens, OR across columns), matched case-insensitively
with SQL ``LIKE``. Results are returned as grouped sections the frontend
renders in the command palette (``/api/search``) or a full page
(``/search``).
"""
from datetime import datetime

from sqlalchemy import and_, or_
from sqlalchemy import func as sa_func

from .models import BusinessEntity, Receipt


def _match(tokens, cols):
    clauses = []
    for tok in tokens:
        like = f"%{tok.lower()}%"
        clauses.append(or_(*[sa_func.lower(col).like(like) for col in cols]))
    return and_(*clauses)


def tokenize(raw):
    return [t for t in (raw or "").strip().split() if t]


def search_sections(raw, per_section=8, owner_id=None):
    """Return a list of {type,label,icon,items:[{label,snippet,url,icon}]}.

    When ``owner_id`` is given, results are limited to that user's receipts and
    businesses (per-user isolation); ``None`` searches everything (admins)."""
    from flask import url_for

    tokens = tokenize(raw)
    if len(raw.strip()) < 2 or not tokens:
        return []

    sections = []

    # Receipts — match vendor, city, state, notes, and the raw OCR text.
    r_cols = [Receipt.vendor_name, Receipt.city, Receipt.state,
              Receipt.notes, Receipt.ocr_text]
    rq = Receipt.query.filter(_match(tokens, r_cols))
    if owner_id is not None:
        rq = rq.filter(Receipt.created_by == owner_id)
    receipts = (rq.order_by(Receipt.purchased_at.desc().nullslast(),
                            Receipt.created_at.desc())
                .limit(per_section).all())
    if receipts:
        items = []
        for r in receipts:
            when = r.purchased_at.strftime("%b %d, %Y") if r.purchased_at else ""
            bits = [b for b in (when, r.city, r.state) if b]
            snippet = " · ".join(bits)
            total = f"${r.grand_total:,.2f}" if r.grand_total else ""
            items.append({
                "label": r.vendor_name or "(no vendor)",
                "snippet": (snippet + ("  " + total if total else "")).strip(),
                "url": url_for("main.receipt_detail", rid=r.id),
                "icon": "receipt",
            })
        sections.append({"type": "receipt", "label": "Receipts",
                         "icon": "receipt", "items": items})

    # Business entities.
    eq = BusinessEntity.query.filter(_match(tokens, [BusinessEntity.name]))
    if owner_id is not None:
        eq = eq.filter(BusinessEntity.owner_id == owner_id)
    entities = eq.order_by(BusinessEntity.name).limit(per_section).all()
    if entities:
        items = [{
            "label": e.name,
            "snippet": "Business entity" + ("" if e.active else " · inactive"),
            "url": url_for("main.entities"),
            "icon": "building",
        } for e in entities]
        sections.append({"type": "entity", "label": "Businesses",
                         "icon": "building", "items": items})

    return sections
