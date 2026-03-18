# HEARTBEAT.md
# Last updated: 2026-03-17 (v3 -- cost optimization)
# Forge reads this file every heartbeat cycle.
# Flag anything that needs Kyle's attention via Telegram.
# Use TIER system: Tier 1 = handle autonomously, Tier 2 = flag to Kyle, Tier 3 = urgent ping.
#
# MODEL ROUTING RULES (follow strictly to minimize API costs):
# Heartbeat / file reads / condition checks  --> google/gemini-2.0-flash (cheapest)
# Content writing / research / analysis      --> anthropic/claude-haiku-4-5
# Complex reasoning / strategy               --> anthropic/claude-sonnet-4-6
# Code tasks                                 --> openai/gpt-5.1-codex
# Heavy multi-step research                  --> google/gemini-3-pro-preview
# Local zero-cost tasks (simple summaries)   --> ollama/llama3.2:3b (once installed)
# NEVER use Sonnet for heartbeat or monitoring. NEVER use Opus unless explicitly requested.

---

## DAILY CHECKS (every morning before 9am)

### Content
- Has Kyle posted on X today? If not, remind him once.
- Has any platform gone 3+ days without a post? Flag as Tier 2.
- Are the warmup day counts current in MEMORY/WARMUP/warmup_status.txt?

### Cold Email Campaign
- Day 7 (2026-03-19): Pull Instantly.ai stats. Run full analysis. Report to Kyle.
- Day 14 (2026-03-26): Optimization review. Recommend changes if reply rate under 1%.
- If Kyle has not checked Instantly.ai in 5+ days: remind once.

### Revenue
- Any new ROK Financial leads to follow up on? Check LEADS folder.
- Revenue log updated? Check FINANCE/revenue_log.txt.
- Any client in active_clients.txt with a missed check-in? Flag.

---

## WEEKLY CHECKS (Mondays)

- Run content batch: Master Daily Runner, all platforms, 5 posts each
- Cold email campaign review (after Day 7)
- Warmup status update -- check which platforms are ready to post freely
- Backup reminder: has run_backup.ps1 been run this week?
- API keys status: are OpenAI and ElevenLabs still not set? Remind Kyle.

---

## MONITORING FLAGS (check these every cycle)

### Tier 1 -- Handle autonomously, log to MISSION_CONTROL
- Routine research tasks
- Content batch generation
- Memory file updates
- Research outputs that need saving

### Tier 2 -- Flag to Kyle via Telegram (not urgent, next check-in is fine)
- Content gap (3+ days without posting on any platform)
- Cold email stats ready for review
- API key still missing after 7+ days
- Backup not run in 7+ days

### Tier 3 -- Ping Kyle immediately (urgent, do not wait)
- Cold email bounce rate over 10% (deliverability emergency)
- Any external service outage affecting active operations
- Client communication that needs human response within 24 hours
- Anything involving real money, real accounts, or Kyle's reputation

---

## LIFE GOALS CHECK (weekly, Fridays)

- Has Kyle mentioned the gym this week? If not, include in Friday briefing.
- Move-out goal: is MRR trending toward $4,000-6,000/month?
- Doctors appointments -- remind once per month until confirmed done.
- App compilation -- has Kyle opened Xcode this week? Remind if not.

---

## NIGHTLY SELF-IMPROVEMENT (after VPS is live)

Run at 2am: Review today's sessions. Find 1 thing to improve. Update memory.
Run at 2:30am: Backup check. If 2am job did not fire, run it now.
Report to Kyle next morning: "Here's what I improved overnight."

---

## BLOCKED ITEMS (do not keep re-flagging, just note status)
- Image generation: UNBLOCKED (OpenAI key active as of 2026-03-17)
- Voiceover pipeline: blocked (ElevenLabs API key not set)
- Kit funnel: blocked (account not created)
- VPS: not yet set up (all cron jobs pending this)
- GitHub backup: not yet initialized
- Ollama: installer ran, model pull in progress (llama3.2:3b)
Status: mention these in weekly briefing only, not daily.
