"""Pure subscription entitlement policy for NEYRONIX.

No payment or database side effects. Counts are illustrative staging defaults;
actual rollout requires verified provider costs and monthly budget caps.
"""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Entitlement:
    included_uses: int
    max_cost_usd_per_use: Decimal
    monthly_cost_ceiling_usd: Decimal


POLICY = {
    "start": {
        "economy_chat": Entitlement(100, Decimal("0.005"), Decimal("0.50")),
        "short_document": Entitlement(10, Decimal("0.02"), Decimal("0.20")),
    },
    "pro": {
        "economy_chat": Entitlement(500, Decimal("0.005"), Decimal("2.50")),
        "short_document": Entitlement(50, Decimal("0.02"), Decimal("1.00")),
    },
    "ultimate": {
        "economy_chat": Entitlement(2000, Decimal("0.005"), Decimal("10.00")),
        "short_document": Entitlement(150, Decimal("0.02"), Decimal("3.00")),
    },
}


def is_included(*, tier, feature, used, spent_usd, estimated_cost_usd):
    """Reject requests exceeding count, per-use cost, or monthly provider budget."""
    entitlement = POLICY.get(str(tier), {}).get(str(feature))
    if entitlement is None:
        return False
    cost = Decimal(str(estimated_cost_usd))
    spent = Decimal(str(spent_usd))
    if not cost.is_finite() or not spent.is_finite() or cost < 0 or spent < 0:
        return False
    return (
        0 <= int(used) < entitlement.included_uses
        and cost <= entitlement.max_cost_usd_per_use
        and spent + cost <= entitlement.monthly_cost_ceiling_usd
    )
