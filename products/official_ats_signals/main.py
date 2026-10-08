"""Apify Actor entrypoint for verified public hiring signals.

This is a standalone product candidate, NOT wired into AION production.
The seller must configure a real Apify PPE event and billing/KYC before sales.
"""
from __future__ import annotations

import asyncio
import os
from apify import Actor

from collector import collect, MAX_RESULTS


async def main() -> None:
    async with Actor:
        values = await Actor.get_input() or {}
        try:
            max_results = min(int(values.get("maxResults", 50)), MAX_RESULTS)
            result = await asyncio.to_thread(
                collect,
                values.get("boards"),
                title_keywords=values.get("titleKeywords", []),
                max_results=max_results,
            )
        except (TypeError, ValueError) as exc:
            Actor.log.error("Invalid bounded request: %s", exc)
            await Actor.set_value("OUTPUT", {"status": "invalid_input", "error": str(exc)})
            return
        if not result["jobs"]:
            await Actor.set_value("OUTPUT", {"status": "no_matching_public_postings", "results": 0, "errors": result["errors"]})
            return

        # Only enable after Seller KYC, pricing and no-loss test. This custom
        # one-time PPE event is registered in Apify Console as "verified-batch".
        # Do not ALSO configure nonzero dataset-item charging for this Actor.
        if os.getenv("AION_HIRING_PPE_ENABLED") != "1":
            # Local/free validation deliberately limits the free result volume.
            await Actor.push_data(result["jobs"][:2])
            await Actor.set_value("OUTPUT", {
                "status": "preview_only",
                "results": min(2, result["results"]),
                "monetization_ready": False,
                "errors": result["errors"],
            })
            return

        charged = await Actor.charge(event_name="verified-batch")
        # event_charge_limit_reached can be True AFTER one successful charge:
        # the remaining spend budget may now be zero. Gate delivery on the
        # actual number of charged events, never on post-charge capacity.
        if charged.charged_count != 1:
            await Actor.set_value("OUTPUT", {"status": "payment_not_charged", "results": 0})
            return
        await Actor.push_data(result["jobs"])
        await Actor.set_value("OUTPUT", {
            "status": "fulfilled",
            "results": result["results"],
            "boards_checked": result["boards_checked"],
            "retrieved_at": result["retrieved_at"],
            "errors": result["errors"],
            "evidence_boundary": "Publicly listed at fetch; neither hiring intent nor job validity guaranteed",
        })


if __name__ == "__main__":
    asyncio.run(main())
