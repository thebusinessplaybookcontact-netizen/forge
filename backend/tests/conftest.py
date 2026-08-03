"""Pin the database and the clock before anything imports the app.

Without this, running the suite drops and recreates the tables in the real coach.db.
This must run before `app.db` is imported, which is why it lives in conftest.
"""

import os
import tempfile

_TMP_DB = os.path.join(tempfile.gettempdir(), "goal_coach_test.db")
# Must match Settings' env_prefix. If the prefix ever changes and this doesn't, the
# assertion below fails loudly instead of the suite quietly eating the real database.
os.environ["COACH_DATABASE_URL"] = f"sqlite:///{_TMP_DB}"

# The suite must not depend on the developer's timezone. Tests build `created_at` at UTC
# midnight and then assert against local calendar dates; under a negative-offset zone
# like America/Los_Angeles that instant is the *previous* day locally, so a habit reads
# as a day older than the test intended and every consistency denominator is one day too
# wide. That's correct behaviour for a real user in LA — it's the fixtures that mean UTC.
# Pinning the zone here keeps the failure from depending on whose machine ran it.
os.environ["COACH_TIMEZONE"] = "UTC"

from app.clock import zone  # noqa: E402
from app.db import engine  # noqa: E402

assert str(engine.url) == f"sqlite:///{_TMP_DB}", (
    f"Tests are pointed at {engine.url!s}, not the temp database. "
    "Refusing to run — this would destroy real data."
)

assert str(zone()) == "UTC", (
    f"Tests are running in {zone()!s}, not UTC. Date-sensitive assertions would "
    "depend on local configuration."
)
