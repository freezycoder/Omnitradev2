#!/usr/bin/env python3
"""Send the weekly Strong Buy digest or a rare intraday review email.

The free Render web process does not run this script. GitHub Actions is the
clock, and the dispatch ledger lives in Postgres.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Running `python scripts/send_alerts.py` puts scripts/ on sys.path, not the repo root.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from application.alert_service import AlertConfig, AlertService
from application.scan_service import run_scan
from config.settings import settings
from providers.email.resend import ResendClient
from storage.repositories.email_dispatch_repository import MemoryEmailDispatchRepository
from storage.repositories.operator_book_repository import open_operator_book
from storage.repositories.postgres_email_dispatch import PostgresEmailDispatchRepository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send OmniTrade operator buy alerts.")
    parser.add_argument("kind", choices=("weekly", "urgent", "status"))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the email. Skips the send window, the ledger, and Resend.",
    )
    args = parser.parse_args(argv)
    config = AlertConfig(
        resend_api_key=settings.resend_api_key,
        alert_from=settings.alert_from,
        alert_recipients=settings.alert_recipients,
        alert_timezone=settings.alert_timezone or "Europe/London",
    )
    if args.dry_run and args.kind != "status":
        ledger = MemoryEmailDispatchRepository()
    elif not settings.alert_database_url:
        print("OMNITRADE_ALERT_DATABASE_URL is required", file=sys.stderr)
        return 1
    else:
        ledger = PostgresEmailDispatchRepository(settings.alert_database_url)

    service = AlertService(
        config=config,
        ledger=ledger,
        mailer=ResendClient(config.resend_api_key),
        scan_fn=run_scan,
        clock=lambda: datetime.now(timezone.utc),
        book_loader=lambda: open_operator_book(settings.alert_database_url).load(),
    )
    if args.kind == "status":
        due = service.weekly_due()
        state = "sent" if due.sent else "overdue"
        print(f"weekly {due.iso_week} {state}")
        print(f"deadline {due.deadline.isoformat()}")
        return 0
    result = service.run(args.kind, dry_run=args.dry_run)
    if args.dry_run:
        if not result.preview:
            print(f"{args.kind} produced no email ({result.suppressed_reason or 'empty'})")
        for message in result.preview:
            print(message.subject)
            print(message.text)
    elif result.already_sent:
        print(f"{args.kind} already sent for {result.due_week}")
    elif result.window_skipped:
        print(f"{args.kind} skipped: outside the send window")
    elif result.exit_code and result.suppressed_reason:
        print(f"{args.kind} suppressed: {result.suppressed_reason}", file=sys.stderr)
    elif result.sent_keys:
        print("sent " + ", ".join(result.sent_keys))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
