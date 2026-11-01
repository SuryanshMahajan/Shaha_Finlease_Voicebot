import pytest

from app.services.metrics import call_rates


@pytest.mark.parametrize(
    "counts,expected",
    [
        ((0, 0, 0), {"connect_rate_percent": 0.0, "right_party_rate_percent": 0.0}),
        ((10, 5, 2), {"connect_rate_percent": 50.0, "right_party_rate_percent": 40.0}),
        ((3, 1, 1), {"connect_rate_percent": 33.33, "right_party_rate_percent": 100.0}),
    ],
)
def test_call_rates_use_persisted_counts_and_zero_denominators(counts, expected):
    assert call_rates(*counts) == expected


def test_call_rates_reject_inconsistent_totals():
    with pytest.raises(ValueError, match="consistent"):
        call_rates(2, 3, 1)
