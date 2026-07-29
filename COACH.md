# Goal Coach

An interactive to-do list / coach / friend. Talk to it, it knows your goals and open
tasks, and it reflects your "why" back at you.

This is the **scaffold**: backend, database, and the chat loop working end to end, plus
a deliberately plain UI. Voice and the design pass come later (see Build order).

## Layout

```
backend/            FastAPI. Holds the Claude key. Does the memory glue.
  app/
    prompts.py      The coach's personality. The ONLY place it lives.
    tools.py        Tool schemas + argument validation + dispatch.
    agent.py        The tool_use -> execute -> tool_result loop.
    crud.py         Every DB mutation. Shared by the HTTP routes and the tools.
    memory.py       Assembles what the model sees (see Memory design).
    claude_client.py Every Claude call goes through here.
    models.py       goals / tasks / sessions / summaries
    routers/        chat.py (chat + session close), goals.py (goals, tasks, dashboard)
  tests/            Tool loop and chat tested with the API stubbed, DB writes real.
frontend/           React + Vite, installable as a PWA.
  src/pages/        Home (dashboard + chat box), Chat, Goals, Settings
Dockerfile          Builds the PWA and serves it from the API as one service.
```

## Running it

**1. Backend**

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # then put your key in it
.venv/bin/python -m app.seed   # seeds the four goals from the spec
.venv/bin/uvicorn app.main:app --reload
```

**2. Frontend** (separate terminal)

```bash
cd frontend
npm install
npm run dev                 # http://localhost:5173, proxies /api to the backend
```

Check `http://localhost:8000/api/health` — `claude_configured` tells you whether the key
was picked up.

Tests: `cd backend && .venv/bin/python -m pytest tests/`

## Configuration

All settings are namespaced `COACH_*` (see `backend/.env.example`). The prefix is not
cosmetic: bare names like `CLAUDE_MODEL` and `CLAUDE_EFFORT` are used by other tooling
and an ambient value will silently override your `.env`. `ANTHROPIC_API_KEY` is the one
exception — it's read unprefixed too, because hosts set it by convention.

The key is only ever read server-side. The frontend calls `/api/*` and nothing else.

## Memory design

The thing this app must not do is stuff every past conversation into the context
window. So it doesn't:

- **Goals and tasks are structured data**, rendered into the prompt from SQLite.
- **After a session, the model writes a compact recap** of what happened and what was
  committed to (`POST /api/sessions/{id}/close`).
- **The next session loads** the system prompt + current goals/tasks + the last N recaps
  (`COACH_RECENT_SUMMARY_COUNT`, default 8). Transcripts are stored for the record but
  are **never** replayed to the model.

Token use per turn therefore stays flat no matter how long the app has been in use.

**Prompt caching** is set up with two breakpoints: the persona (byte-identical forever)
and the current-state block. Never interpolate a timestamp or anything volatile into
`COACH_PERSONA` — that would invalidate the cache on every single request.

One caveat to watch: the API silently declines to cache prefixes under ~1024 tokens, and
the persona is currently around 800. Until the state block grows (more goals, tasks, and
recaps), caching may not engage at all. Check `usage.cache_read_input_tokens` on a chat
response — if it's always 0, that's why, not a misconfiguration.

## Tools — the coach changes things itself

The coach doesn't just read the to-do list, it edits it. Say "add call the accountant to
today" or "mark the workout done" and the change is committed before the reply comes
back.

| Tool | Arguments | Notes |
| --- | --- | --- |
| `add_task` | `text`, `linked_goal_id?`, `due?` | `due` is `YYYY-MM-DD`; today's date is in the prompt so the model resolves "today" itself |
| `complete_task` | `task_id` | |
| `update_task` | `task_id`, `text?`, `due?`, `status?`, `linked_goal_id?` | Only supplied fields change. `due: null` clears the date |
| `delete_task` | `task_id` | For tasks that shouldn't exist. If it was actually done, `complete_task` keeps it on the record |
| `add_goal` | `text`, `horizon`, `why?` | `horizon` is `daily`/`weekly`/`lifetime` |
| `update_goal` | `goal_id`, `text?`, `why?`, `horizon?`, `status?` | Only supplied fields change |

Schemas live in `backend/app/tools.py`, so the persona prompt stays about tone and the
tool descriptions stay about behaviour.

**How a turn runs** (`backend/app/agent.py`): call the API → if `stop_reason` is
`tool_use`, execute *every* `tool_use` block in the response, append the assistant turn
plus **one** user message containing all the `tool_result` blocks, and call again. Repeat
until the model stops asking for tools, capped at `MAX_TOOL_ITERATIONS` (6) since each
iteration is a billed request. Chained calls in a single turn work — "did the workout and
add a massage" is two calls in one response.

**Errors go back to the model, not to a stack trace.** Arguments are validated with
Pydantic before anything touches the database, and a bad task id, a malformed date, or a
hallucinated argument name all come back as a `tool_result` with `is_error: true` and a
readable message. The model can then correct itself or tell you what failed. Nothing is
written on a rejected call.

**One implementation of the DB logic.** `crud.py` owns every mutation; the tools and the
Goals screen's HTTP routes both call it. The tools are not a second path into the
database.

Tool definitions render *before* the system prompt, so they're part of the cached prefix
— `TOOL_DEFINITIONS` order is deliberately stable, and reordering it silently invalidates
the prompt cache. A test asserts the order.

Note that tool blocks are not replayed in later turns' history: a `tool_use` only has to
be answered within the turn it happened in. Subsequent turns see the *result* of the
change, because the current goals and tasks are re-rendered into the system prompt each
time.

## The personality

All of it is in `backend/app/prompts.py`. There are no hardcoded coaching lines anywhere
else in the codebase — if the coach should say something different, change the prompt.

The `why` field on each goal is what gives it teeth, so it's worth writing those in the
Goals screen the way you'd actually say them. The seeded ones are placeholders.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness + whether the key is configured |
| `GET` | `/api/dashboard` | Goals, open tasks, recent recaps — one call for Home |
| `POST` | `/api/chat` | One coaching turn (JSON). Returns `actions[]` — what the coach changed |
| `POST` | `/api/chat/stream` | Same turn as SSE: `session`, `delta`, `action`, `done`, `error` events |
| `POST` | `/api/sessions/{id}/close` | End session, write its recap |
| | `/api/goals`, `/api/tasks` | CRUD (`GET`/`POST`/`PATCH`/`DELETE`) |

## Deploying

Railway, via the Dockerfile — it builds the PWA and serves it from the API, so it's one
service, not two. Set `ANTHROPIC_API_KEY` in the Railway environment. `railway.json`
points the healthcheck at `/api/health`.

SQLite lives on the container filesystem, which on Railway means **it does not survive a
redeploy**. Attach a volume and point `COACH_DATABASE_URL` at it, or move to Postgres,
before there's data worth keeping.

## Build order

1. ~~Backend + DB + working chat endpoint~~ ✅
2. ~~Minimal chat UI~~ ✅
3. ~~Goals/tasks CRUD + dashboard~~ ✅ (functional, not designed)
4. ~~Session summaries + memory loading~~ ✅
4b. ~~Tool use — the coach edits goals and tasks from conversation~~ ✅
5. Voice — STT in, human TTS out, with the toggle. The Settings toggle saves its
   preference already; nothing is wired to speech yet.
6. Deploy hosted — Dockerfile and railway.json are ready.
7. Polish pass with the frontend-design skill.

Phase 2, not started: scheduled nudges, cheaper model routing for routine calls, the
literal quest/game layer.

## Known gaps

- **No migrations.** Tables are created with `create_all` on startup. Add Alembic before
  the schema matters.
- **No auth.** Anyone with the URL can talk to your coach and spend your tokens. Fine on
  a private URL; not fine indefinitely.
- **No undo.** The coach deletes and overwrites for real, and a misheard sentence is a
  lost task. `delete_task` is the one to watch. Worth adding a soft-delete or an undo
  window before voice lands, since speech recognition will misfire more than typing does.
- **The dashboard doesn't live-update.** Chat emits `action` events and the Chat screen
  shows them inline, but Home only refetches when you navigate to it.
- **Nothing is designed yet.** The CSS is a restrained baseline so the skeleton is usable
  on a phone, and should be treated as a placeholder for step 7.
