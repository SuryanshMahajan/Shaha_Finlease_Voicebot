from datetime import datetime, timezone
from pathlib import Path

from app.models import CallOutcome, Customer
from app.services.demo import run_persona, three_line_summary
from app.services.customer_import import parse_customer_csv


def customer():
    return Customer(customer_ref="DEMO-TEST", display_name="Demo Customer", birth_year=1980, preferred_language="en")


def test_persona_outcomes_and_silence_does_not_fabricate_transcript():
    now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
    person = customer()
    assert run_persona(person, "right_customer_hindi", now, "Asia/Kolkata").outcome == CallOutcome.right_customer
    assert run_persona(person, "wrong_birth_year_english", now, "Asia/Kolkata").outcome == CallOutcome.verification_failed
    assert run_persona(person, "wrong_number", now, "Asia/Kolkata").outcome == CallOutcome.wrong_number
    callback = run_persona(person, "third_party_callback", now, "Asia/Kolkata")
    assert callback.outcome == CallOutcome.callback_requested
    assert callback.callback_at is not None
    no_callback = run_persona(person, "third_party_no_callback", now, "Asia/Kolkata")
    assert no_callback.outcome == CallOutcome.third_party_answered
    assert no_callback.callback_at is None
    silence = run_persona(person, "silence", now, "Asia/Kolkata")
    assert silence.outcome == CallOutcome.not_connected
    assert silence.connected is False
    assert silence.messages == ()
    opt_out = run_persona(person, "do_not_call", now, "Asia/Kolkata")
    assert opt_out.do_not_call is True
    assert opt_out.outcome is None
    assert opt_out.messages[-1][0] == "assistant"


def test_simulated_summary_is_exactly_three_lines():
    value = three_line_summary(CallOutcome.wrong_number, True, None, "Asia/Kolkata")
    assert len(value.splitlines()) == 3


def test_example_csv_contains_ten_valid_fictional_demo_customers():
    example = Path(__file__).resolve().parents[2] / "data" / "example_customers.csv"
    parsed = parse_customer_csv(example.read_bytes())
    assert parsed.total_rows == 10
    assert len(parsed.rows) == 10 and parsed.rejected_rows == 0
    assert all(row.customer_ref.startswith("DEMO-") for row in parsed.rows)

