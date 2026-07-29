"""Seed the four goals from the build spec, with a placeholder 'why' for each.

The 'why' text is what the coach throws back at Kyle, so these are worth editing in
the Goals screen to say what he'd actually say. Run with:

    python -m app.seed
"""

from sqlalchemy import select

from .db import SessionLocal, init_db
from .models import Goal, Horizon

SEED_GOALS = [
    (
        "Grow the business into autonomous income systems",
        Horizon.lifetime,
        "So money isn't something I trade hours for. I want systems that earn while I sleep.",
    ),
    (
        "Write and publish the children's book series",
        Horizon.lifetime,
        "Because I want to make something that outlives me and that a kid actually loves.",
    ),
    (
        "Fitness and body recomposition",
        Horizon.lifetime,
        "I owe it to myself to be in the best shape of my life. Not for anyone else.",
    ),
    (
        "Don't burn out — take care of myself",
        Horizon.lifetime,
        "None of the rest of it counts if I wreck myself getting there.",
    ),
]


def seed() -> None:
    init_db()
    with SessionLocal() as db:
        existing = set(db.scalars(select(Goal.text)))
        added = 0
        for text, horizon, why in SEED_GOALS:
            if text in existing:
                continue
            db.add(Goal(text=text, horizon=horizon, why=why))
            added += 1
        db.commit()
        print(f"Seeded {added} goal(s); {len(existing)} already present.")


if __name__ == "__main__":
    seed()
