"""Shared resource-matching helper.

Lives here so the detection layer and the scoring layer use the SAME rule for
deciding whether a requested resource is restricted. They previously disagreed:
detection matched by prefix while scoring matched by exact membership, so
/admin scored High (15) while /admin/login.php scored Medium (6) — the same
violation, two tiers apart.

Keep this the only implementation. A copy in a second module recreates that bug.
"""
from __future__ import annotations


def matches_restricted(resource: str, restricted) -> bool:
    """Return True if resource starts with any restricted prefix.

    Prefix match (not substring): /admin matches /admin, /admin/, and
    /admin/login.php, but /administrator does not.  Query strings are
    stripped before matching so /admin?page=1 is caught too.
    """
    path = resource.split("?")[0]
    path = path.rstrip("/") or "/"
    for prefix in restricted:
        clean_prefix = prefix.rstrip("/")
        if path == clean_prefix or path.startswith(clean_prefix + "/"):
            return True
    return False
