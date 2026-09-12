"""Operator-only Package 5D pilot CLI. Dry-run is the default; no scheduler."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal  # noqa: E402
from app.services.ambassador import (  # noqa: E402
    AmbassadorError,
    campaign_status,
    create_campaign,
    prepare_target,
    qualify_target,
    scout_campaign,
    send_contact,
    set_campaign_state,
    suppress_target,
)


def _parser():
    parser = argparse.ArgumentParser(description="Bounded AION Ambassador pilot; no automatic outreach")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-campaign")
    create.add_argument("--name", required=True)
    create.add_argument("--purpose", required=True)
    create.add_argument("--maximum-targets", type=int, default=30)
    create.add_argument("--maximum-contacts", type=int, default=30)
    state = sub.add_parser("set-state")
    state.add_argument("--campaign", required=True)
    state.add_argument("--state", required=True, choices=("draft", "ready", "paused", "closed"))
    scout = sub.add_parser("scout")
    scout.add_argument("--campaign", required=True)
    scout.add_argument("--query", required=True)
    qualify = sub.add_parser("qualify")
    qualify.add_argument("--target", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--target", required=True)
    prepare.add_argument("--public-url", required=True)
    send = sub.add_parser("contact")
    send.add_argument("--target", required=True)
    send.add_argument("--idempotency-key", required=True)
    send.add_argument("--send", action="store_true", help="Requires both AION_AMBASSADOR_* gates")
    suppress = sub.add_parser("suppress")
    suppress.add_argument("--target", required=True)
    suppress.add_argument("--reason", required=True)
    status = sub.add_parser("status")
    status.add_argument("--campaign", required=True)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        with SessionLocal() as db:
            if args.command == "create-campaign":
                result = create_campaign(db, name=args.name, purpose=args.purpose, maximum_targets=args.maximum_targets, maximum_contacts=args.maximum_contacts)
            elif args.command == "set-state":
                result = set_campaign_state(db, args.campaign, args.state)
            elif args.command == "scout":
                result = scout_campaign(db, campaign_id=args.campaign, query=args.query)
            elif args.command == "qualify":
                result = qualify_target(db, args.target)
            elif args.command == "prepare":
                result = prepare_target(db, target_id=args.target, public_base_url=args.public_url)
            elif args.command == "contact":
                # Read the one-time prepared message from stdin so its raw
                # distribution token is not placed in process arguments.
                result = send_contact(db, target_id=args.target, message=json.load(sys.stdin), idempotency_key=args.idempotency_key, send=args.send)
            elif args.command == "suppress":
                result = suppress_target(db, target_id=args.target, reason=args.reason)
            else:
                result = campaign_status(db, args.campaign)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (AmbassadorError, json.JSONDecodeError) as exc:
        payload = {"error": getattr(exc, "code", "invalid_json"), "message": str(exc)}
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
