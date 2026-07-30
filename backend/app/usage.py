"""Recording what the coach costs.

Every model call writes a row; the API adds it up. The point is that spend is visible
before the bill is, and that a jump is attributable — a tool loop that ran six times
looks different from one long answer.

Cost is an *estimate*. Prices are a hardcoded snapshot (below) and there's no way to
reconcile against actual billing from here, so treat the number as a sense of scale
rather than an invoice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import clock
from .models import UsageEvent

log = logging.getLogger("coach")


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens."""

    input: float
    output: float

    @property
    def cache_read(self) -> float:
        return self.input * 0.1  # cache reads bill at roughly a tenth of input

    @property
    def cache_write(self) -> float:
        return self.input * 1.25  # writes carry a premium over plain input


# Snapshot of list prices. Wrong prices are worse than no prices, so if a model isn't
# listed its usage is still counted in tokens and simply contributes no cost estimate.
PRICES: dict[str, Price] = {
    "claude-sonnet-5": Price(input=3.00, output=15.00),
    "claude-opus-5": Price(input=5.00, output=25.00),
    "claude-haiku-4-5": Price(input=1.00, output=5.00),
}


def record(
    db: Session,
    *,
    kind: str,
    model: str,
    usage: object | None,
) -> None:
    """Log one call's usage. Never raises — telemetry must not break a conversation."""
    if usage is None:
        return
    try:
        event = UsageEvent(
            kind=kind,
            model=model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )
        db.add(event)
        db.commit()
    except Exception:
        log.exception("Could not record usage")
        db.rollback()


def estimate_cost(model: str, inp: int, out: int, cache_read: int, cache_write: int) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    return (
        inp * price.input
        + out * price.output
        + cache_read * price.cache_read
        + cache_write * price.cache_write
    ) / 1_000_000


def summarise(db: Session, *, days: int) -> dict:
    """Totals over the last `days` local days, inclusive of today."""
    start_local = clock.now_local() - timedelta(days=days - 1)
    start = start_local.replace(hour=0, minute=0, second=0, microsecond=0)

    row = db.execute(
        select(
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cache_read_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cache_write_tokens), 0),
        ).where(UsageEvent.created_at >= start)
    ).one()

    calls, inp, out, cache_read, cache_write = row

    # Cost is per-model, so total it model by model rather than assuming one price.
    per_model = db.execute(
        select(
            UsageEvent.model,
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cache_read_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cache_write_tokens), 0),
        )
        .where(UsageEvent.created_at >= start)
        .group_by(UsageEvent.model)
    ).all()

    cost: float | None = 0.0
    for model, mi, mo, mr, mw in per_model:
        part = estimate_cost(model, mi, mo, mr, mw)
        if part is None:
            cost = None  # an unpriced model makes the total untrustworthy; say so
            break
        cost += part

    cached_share = (cache_read / (cache_read + inp)) if (cache_read + inp) else 0.0

    return {
        "days": days,
        "calls": calls,
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        # How much of the input came from cache — the number that tells you whether
        # prompt caching is doing its job.
        "cached_share": round(cached_share, 3),
        "estimated_cost_usd": None if cost is None else round(cost, 4),
    }
