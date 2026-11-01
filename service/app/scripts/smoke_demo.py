"""Import fictional CSV rows and persist all six outcomes twice, locally."""
from pathlib import Path

from sqlalchemy import false, func, select

from app.db.session import SessionLocal
from app.main import _save_demo_call, settings
from app.models import Call, CallSummary, Customer, TranscriptMessage
from app.services.customer_import import parse_customer_csv
from app.services.demo import SUITE_PERSONAS


if settings.app_env != "development":
    raise SystemExit("Refusing to seed demo records outside APP_ENV=development.")

csv_path = Path("/app/demo-data/example_customers.csv")
if not csv_path.is_file():
    raise SystemExit("Mount the repository data folder so the fictional CSV is available.")
parsed = parse_customer_csv(csv_path.read_bytes())
if parsed.total_rows != 10 or parsed.rejected_rows or len(parsed.rows) != 10:
    raise SystemExit("Example CSV must parse as exactly ten valid fictional customers.")

with SessionLocal() as db:
    before = db.scalar(select(func.count()).select_from(Call)) or 0
    existing_refs = set(db.scalars(select(Customer.customer_ref)).all())
    for row in parsed.rows:
        if row.customer_ref not in existing_refs:
            db.add(Customer(
                customer_ref=row.customer_ref,
                display_name=row.display_name,
                birth_year=row.birth_year,
                phone_last4=row.phone_last4,
                preferred_language=row.preferred_language,
                do_not_call=row.do_not_call,
                verification_status="unverified",
            ))
    db.commit()
    demo_refs = [row.customer_ref for row in parsed.rows]
    customers = db.scalars(select(Customer).where(Customer.customer_ref.in_(demo_refs), Customer.customer_ref.like("DEMO-%"), Customer.do_not_call == false(), Customer.birth_year.is_not(None)).order_by(Customer.customer_ref).limit(6)).all()
    if len(customers) < 6:
        raise SystemExit("Need six eligible fictional demo customers.")
    calls = []
    for _ in range(2):
        for customer, persona in zip(customers, SUITE_PERSONAS, strict=True):
            calls.append(_save_demo_call(db, customer, persona))
    db.commit()
    after = db.scalar(select(func.count()).select_from(Call)) or 0
    if after - before != 12:
        raise SystemExit("Persisted call count did not increase by twelve.")
    for call in calls:
        db.refresh(call)
        if not call.simulated:
            raise SystemExit("A demo call was not marked simulated.")
        if call.outcome and call.outcome.value != "not_connected":
            summary = db.scalar(select(CallSummary).where(CallSummary.call_id == call.id))
            if summary is None or summary.status != "completed" or len(summary.content.splitlines()) != 3:
                raise SystemExit("A responded persona is missing its three-line summary.")
    transcript_rows = db.scalar(select(func.count()).select_from(TranscriptMessage).where(TranscriptMessage.call_id.in_([call.id for call in calls]))) or 0
    outcomes = {str(call.outcome.value) for call in calls if call.outcome}
    required = {"right_customer", "wrong_number", "third_party_answered", "callback_requested", "verification_failed", "not_connected"}
    if outcomes != required:
        raise SystemExit("The twelve-call suite did not exercise all six outcomes.")
    print(f"PASS: parsed 10 fictional CSV customers; persisted {after - before} calls across all six outcomes; {transcript_rows} transcript segments; total calls={after}.")
