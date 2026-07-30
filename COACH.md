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
    speech.py       Text to speech (ElevenLabs / OpenAI) behind one function.
    claude_client.py Every Claude call goes through here.
    models.py       goals / tasks / sessions / summaries
    routers/        chat.py, goals.py (goals, tasks, dashboard), voice.py (TTS)
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
| `delete_task` | `task_id` | Soft delete, reversible. If it was actually done, `complete_task` keeps it on the record |
| `add_goal` | `text`, `horizon`, `why?` | `horizon` is `daily`/`weekly`/`lifetime` |
| `update_goal` | `goal_id`, `text?`, `why?`, `horizon?`, `status?` | Only supplied fields change |
| `delete_goal` | `goal_id` | Soft delete, reversible. Prefer `status: done`/`paused` |
| `undo_last` | — | Reverses the most recent deletion, so "undo" works by voice |

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

## Voice

Tap the microphone next to the message box, talk, tap again. It sends when you stop.

**Speech in** is the phone's own engine (`webkitSpeechRecognition`) — free, nothing to
configure, and audio never reaches the server. It's set to `continuous` so pausing
mid-thought doesn't cut you off, which is the point when you're rambling. Browsers
without it (Firefox) just don't show the mic button; typing still works.

**Speech out** has two modes, toggled in Settings:

| Mode | How | Cost |
| --- | --- | --- |
| Human voice | `POST /api/speak` → ElevenLabs or OpenAI → mp3 | per word |
| Built-in voice | `speechSynthesis` in the browser | free |

The TTS key lives server-side like the Claude key; the browser asks the API for audio and
never sees a credential. Provider selection is config, not code: `COACH_TTS_PROVIDER=auto`
prefers ElevenLabs, falls back to OpenAI, and if neither key is set **human mode silently
degrades to the built-in voice** rather than erroring — so the app works with no TTS
account at all. Settings says which provider is live, and "Hear it" plays a sample.

Reading replies aloud is **off by default** — a fresh install shouldn't start talking at
you. Turn it on in Settings.

Two mobile details worth knowing, since both are invisible until they break. Audio
playback must be unlocked by a user gesture, so tapping the mic plays a moment of silence
to prime the audio element for the reply that arrives seconds later. And any failure in
the paid path falls through to the browser voice, so a provider outage means a worse
voice rather than silence.

## Nothing is ever really deleted

Voice will mishear things, and a deleted task shouldn't be a lost task. So there are no
hard deletes anywhere in the app:

- `delete_task` and `delete_goal` set `deleted_at` instead of removing the row.
- **Every read filters soft-deleted rows out.** That's the safety property — code that
  forgets `deleted_at` exists gets the safe behaviour by default, because seeing a
  deleted row requires asking for it explicitly (`get_task(..., include_deleted=True)`).
  A deleted goal also disappears from the state block the model sees.
- Each delete writes an `undo_entries` row. Within `COACH_UNDO_WINDOW_SECONDS`
  (default 300) it can be reversed — say "undo" and the coach calls `undo_last`, or tap
  **Undo** on the action note in the chat. Each entry is single-use.
- A deleted goal's tasks keep pointing at it, so an undo restores the goal completely. A
  task whose goal is deleted simply shows no goal.

The undo log lives in the database rather than process memory so it survives a restart
and doesn't depend on which worker handled the original request.

Past the window, the row is still there — it just isn't offered as a one-tap undo any
more, and can be restored by hand. **Soft-deleted rows are never purged**, which is the
point, but it does mean the tables only grow.

Undo currently covers deletions only. Reversing a field edit would mean snapshotting the
before-state on every update; `UndoEntry.action` exists so that can be added without a
migration.

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
| | `/api/goals`, `/api/tasks` | CRUD (`GET`/`POST`/`PATCH`/`DELETE`). `DELETE` is soft and returns `undo_id` |
| `POST` | `/api/undo` | Reverse the most recent deletion |
| `POST` | `/api/undo/{undo_id}` | Reverse one specific change (410 if the window has passed) |
| `GET` | `/api/voice/status` | Whether a human-voice provider is configured |
| `POST` | `/api/speak` | Text → mp3 (503 = no provider, client falls back to browser voice) |

## Deploying

One service, not two: the Dockerfile builds the PWA and the API serves it from the same
origin, so there's no CORS and no second deploy to keep in sync.

**Railway** (primary target — `railway.json` sets the healthcheck to `/api/health`):

1. Point a new project at this repo. It'll pick up the Dockerfile.
2. **Add a volume and mount it at `/data`.** Do this before the first real
   conversation — see below.
3. Set variables: `ANTHROPIC_API_KEY`, plus `ELEVENLABS_API_KEY` or `OPENAI_API_KEY` if
   you want the human voice. `COACH_DATA_DIR=/data` and `COACH_CORS_ORIGINS=""` are
   already baked into the image.
4. Deploy, then open `/api/health` — `claude_configured` should be `true`, and
   `/api/voice/status` tells you whether the human voice is live.

**Render** is configured too (`render.yaml`, disk mounted at `/data`) since the spec
allowed either.

### The volume is not optional

SQLite lives on the container filesystem. Without a volume the database is part of the
image, so **every redeploy silently starts you from an empty list** — no error, just a
coach that's forgotten everything. `COACH_DATA_DIR=/data` plus a mounted volume moves the
file outside the container. This is verified: a rebuilt container against the same volume
keeps its goals and tasks, and the same image without the volume comes up empty.

To move to Postgres later, set `COACH_DATABASE_URL` and install a driver
(`pip install "psycopg[binary]"`, URL `postgresql+psycopg://...`). Nothing else changes —
but there are no migrations, so do it before the data matters.

### Serving, verified

The production layout was exercised end to end (health, SPA root, client-side deep links
like `/goals`, the manifest and service worker, the API, and absent CORS headers).
Building the image itself has **not** been run — there was no Docker daemon available —
so the first `docker build` is still unproven. `npm ci` against the committed lockfile
was checked separately, since that's the step most likely to fail the build.

## Build order

1. ~~Backend + DB + working chat endpoint~~ ✅
2. ~~Minimal chat UI~~ ✅
3. ~~Goals/tasks CRUD + dashboard~~ ✅ (functional, not designed)
4. ~~Session summaries + memory loading~~ ✅
4b. ~~Tool use — the coach edits goals and tasks from conversation~~ ✅
4c. ~~Soft delete + undo, and a live-updating dashboard~~ ✅
5. ~~Voice — STT in, human TTS out, with the toggle~~ ✅
6. Deploy hosted — config ready and the production layout verified; the actual deploy
   needs your Railway account. See Deploying.
7. Polish pass with the frontend-design skill.

Phase 2, not started: scheduled nudges, cheaper model routing for routine calls, the
literal quest/game layer.

## Known gaps

- **No migrations.** Tables come from `create_all` on startup, and columns added to an
  existing model are patched in by `_ADDED_COLUMNS` in `db.py` (SQLite `ALTER TABLE`).
  That's a stopgap, not a migration system — add Alembic before the schema matters.
- **No auth — read this before making the URL public.** Anyone with the link can talk to
  your coach, read your goals, and spend your Claude and TTS credits. A hosted URL is
  guessable in a way `localhost` isn't, so this stops being theoretical the moment you
  deploy. Put it behind Railway's private networking, an auth proxy, or at minimum a
  shared secret before sharing the link anywhere.
- **react-router advisory GHSA-qwww-vcr4-c8h2** (high) is open with no fix published —
  it's flagged as fixed in >8.2.0 and the latest release is 7.18.2. It concerns RSC-mode
  action handling; this app uses plain client-side `BrowserRouter` with no server
  components, data actions, or loaders, so it isn't reachable here. Re-check when 8.x
  ships.
- **Soft-deleted rows are never purged.** Deliberate, but the tables only grow. A
  "permanently forget this" path will eventually be wanted.
- **Undo covers deletions, not edits.** If the coach rewords a task wrongly, there's no
  one-tap way back.
- **Speech recognition is Chrome/Safari only**, and on iOS it needs Safari 14.5+. Firefox
  shows no mic button. Nothing has been tested on a real phone yet — the browser checks
  ran in headless Chromium, which can't exercise a microphone.
- **TTS isn't streamed.** The whole reply is synthesised before playback starts, so a
  long answer has a noticeable pause. Both providers support streaming if that becomes
  annoying.
- **Nothing is designed yet.** The CSS is a restrained baseline so the skeleton is usable
  on a phone, and should be treated as a placeholder for step 7.
