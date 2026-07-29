"""Point the app at a throwaway database before anything imports it.

Without this, running the suite drops and recreates the tables in the real coach.db.
This must run before `app.db` is imported, which is why it lives in conftest.
"""

import os
import tempfile

_TMP_DB = os.path.join(tempfile.gettempdir(), "goal_coach_test.db")
# Must match Settings' env_prefix. If the prefix ever changes and this doesn't, the
# assertion below fails loudly instead of the suite quietly eating the real database.
os.environ["COACH_DATABASE_URL"] = f"sqlite:///{_TMP_DB}"

from app.db import engine  # noqa: E402

assert str(engine.url) == f"sqlite:///{_TMP_DB}", (
    f"Tests are pointed at {engine.url!s}, not the temp database. "
    "Refusing to run — this would destroy real data."
)
