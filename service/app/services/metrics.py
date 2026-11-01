"""Safe database report rate calculations, including zero-denominator policy."""


def call_rates(total_calls: int, connected_calls: int, right_customers: int) -> dict[str, float]:
    if min(total_calls, connected_calls, right_customers) < 0:
        raise ValueError("Metric counts cannot be negative.")
    if connected_calls > total_calls or right_customers > connected_calls:
        raise ValueError("Metric counts must be internally consistent.")
    return {
        "connect_rate_percent": round(100 * connected_calls / total_calls, 2) if total_calls else 0.0,
        "right_party_rate_percent": round(100 * right_customers / connected_calls, 2) if connected_calls else 0.0,
    }
