"""Secret-safe, read-only readiness contract for one authorized first SAT."""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..release_identity import EXPECTED_SCHEMA_REVISION, release_identity
from .direct_base_usdc import direct_base_usdc_readiness


_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


def first_sat_activation_preflight(
    db: Session, *, expected_release_sha: str | None = None
) -> dict:
    """Inspect prerequisites without payment broadcast or money-moving work."""
    readiness = direct_base_usdc_readiness()
    try:
        revisions = list(db.scalars(text("SELECT version_num FROM alembic_version")))
    except Exception:
        revisions = []
    schema_current = revisions == [EXPECTED_SCHEMA_REVISION]
    identity = release_identity()
    expected = (
        expected_release_sha.strip().lower()
        if isinstance(expected_release_sha, str) and _SHA.fullmatch(expected_release_sha.strip())
        else None
    )
    reasons = list(readiness["blocking_reasons"])
    if identity["release_sha"] is None:
        reasons.append("release_sha_unavailable")
    if expected is None:
        reasons.append("expected_release_sha_missing_or_invalid")
    elif identity["release_sha"] is not None and identity["release_sha"] != expected:
        reasons.append("release_sha_mismatch")
    if not schema_current:
        reasons.append("database_schema_not_current")
    reasons = list(dict.fromkeys(reasons))
    non_gate_reasons = [reason for reason in reasons if reason != "real_money_execution_disabled"]
    activation_ready_except_master_gate = bool(
        readiness["activation_ready_except_master_gate"] and not non_gate_reasons
    )
    activation_ready = bool(activation_ready_except_master_gate and readiness["launch_ready"])
    return {
        "preflight_only": True,
        "facilitator_contacted": False,
        "blockchain_rpc_contacted": False,
        "payment_attempted": False,
        "entitlement_created": False,
        "revenue_claimed": False,
        "release": {
            **identity,
            "expected_release_sha": expected,
            "matches_expected": bool(expected and identity["release_sha"] == expected),
        },
        "schema": {
            "expected_revision": EXPECTED_SCHEMA_REVISION,
            "observed_revisions": revisions,
            "current": schema_current,
        },
        "payment": readiness,
        "blocking_reasons": reasons,
        "activation_ready_except_master_gate": activation_ready_except_master_gate,
        "activation_ready": activation_ready,
        "human_gate": {
            "required": bool(
                activation_ready_except_master_gate
                and not readiness["real_money_execution_enabled"]
            ),
            "action": (
                "explicitly_enable_AION_REAL_MONEY_EXECUTION_ENABLED_for_one_authorized_SAT"
                if activation_ready_except_master_gate
                and not readiness["real_money_execution_enabled"]
                else None
            ),
        },
        "truth_boundaries": {
            "buyer_pays_gas": True,
            "facilitator_credentials_not_required": True,
            "preflight_does_not_contact_base_rpc": True,
            "preflight_is_not_payment": True,
            "configured_quote_is_not_revenue": True,
            "schema_current_is_not_production_deployment": True,
            "database_read_may_use_network": True,
        },
    }