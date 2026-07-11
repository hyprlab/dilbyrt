# SPDX-License-Identifier: AGPL-3.0-or-later
"""Role-based access control.

Three tiers, deliberately enumerated rather than computed so the matrix
stays explicit:

  - viewer : read-only. Can browse receipts, entities and run exports.
  - editor : viewer + create/edit/delete receipts and business entities.
  - admin  : editor + manage users and site settings (Turnstile, etc.).
"""

ROLE_TIERS = [
    ("viewer", "Viewer — read only"),
    ("editor", "Editor — manage receipts"),
    ("admin", "Admin — full control"),
]
ROLE_TIER_KEYS = {k for k, _ in ROLE_TIERS}


def user_meets_role(user, required):
    """True if ``user``'s role satisfies ``required``. Anonymous users
    always fail; an unknown requirement falls closed to admin-only."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    role = getattr(user, "role", None)
    if required == "viewer":
        return role in ("admin", "editor", "viewer")
    if required == "editor":
        return role in ("admin", "editor")
    if required == "admin":
        return role == "admin"
    return role == "admin"
