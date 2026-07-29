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
    memory.py       Assembles what the model sees (see Memory design).
    claude_client.py Every Claude call goes through here.
    models.py       goals / tasks / sessions / summaries
    routers/        chat.py (chat + session close), goals.py (goals, tasks, dashboard)
  tests/            Chat loop tested with the Claude call stubbed out.
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
| `POST` | `/api/chat` | One coaching turn (JSON) |
| `POST` | `/api/chat/stream` | Same turn, streamed as SSE |
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
- **The coach can't yet edit your to-do list.** It reads goals and tasks and talks about
  them, but updating them from conversation needs tool use — that's the next backend
  piece worth building.
- **Nothing is designed yet.** The CSS is a restrained baseline so the skeleton is usable
  on a phone, and should be treated as a placeholder for step 7.
