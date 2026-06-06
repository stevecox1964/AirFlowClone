# AirFlowClone — Agent Driver via Claude Code Skill

## Context

The AirFlowClone engine is already API-first: every UI action has a REST endpoint and FastAPI auto-publishes OpenAPI at `/openapi.json` + `/docs`. The next step toward the Phase 3 vision (LLMs authoring and operating DAGs) does **not** require a new protocol layer.

We considered building an MCP server wrapper; it adds a new module, a new SDK dependency, a separate entry point, and per-client config — all to expose a surface that already exists. A **portable markdown skill** that teaches the LLM how to drive the existing REST API is dramatically simpler and matches the "simplicity first, no speculative abstractions" rule from CLAUDE.md.

The skill turns the engine's documented HTTP surface into the agent's tool surface — no new code paths, no duplicated validation, no extra process.

**Cross-model from day one.** The skill is not Claude-Code-exclusive. Multiple Claude variants (Opus, Sonnet, Haiku — possibly across versions) must be able to read the same file and drive the engine. This shapes how the skill is written (unambiguous, copy-paste-ready, weakest-reader-first) and how it's located (one canonical file, both auto-discoverable in Claude Code and ingestable as a system prompt elsewhere).

## Decision: spec vs `.py` (open question from NOTES.md — resolved)

**The spec dict is the authoring source. The `.py` file under `dags/` is the deterministic compile target. The runtime executes only `.py` files.**

- `POST /api/dags` (with a spec) calls `templating.render_dag_py()`, writes the file, and stores `spec_json` on the `Dag` row.
- `PUT /api/dags/{id}` rejects hand-authored DAGs (no `spec_json`) with 409.
- `GET /api/dags/{id}/spec` 404s for hand-authored DAGs.

This already matches the implementation in `backend/airflowclone/api.py` and `backend/airflowclone/templating.py` — no code change. Only documentation: append the decision to `NOTES.md` so the question is closed.

**Why:** one execution path (loader reads `.py`), one debugging surface (`cat dags/foo.py` works), one place where scheduler + file-watcher already work. Storing DAGs as JSON and running through a generic harness would fork the runtime for no current benefit.

## Cross-model portability — first-class constraint

The skill must work for **multiple Claude variants** (Opus, Sonnet, Haiku) and across versions. That changes the design:

- The skill file is a **portable markdown contract**, not a Claude-Code-exclusive artifact. The same file is consumed three ways:
  1. **Claude Code** — auto-discovered as a skill (frontmatter + `.claude/skills/` location), invokable via `/airflowclone`.
  2. **Any Claude via the Anthropic API** — loaded into context as a system prompt or first user message (e.g., a thin Python harness that reads the file and prepends it).
  3. **Direct human reading** — it doubles as the README for "how to drive this thing."
- Write for the **weakest expected reader (Haiku)**: unambiguous imperatives, copy-paste-ready payloads, no clever inferences, no implicit context. If an instruction can be misread, rewrite it.
- Tool assumption: the LLM has **shell/HTTP access** (Bash, PowerShell, or a generic `http_request` tool). The skill assumes nothing else.
- Keep the file **self-contained** — anything the LLM needs to drive a DAG end-to-end is in this one file. The OpenAPI reference is a pointer for ambiguity resolution, not a required read.

## Skill design

**One file, dual-purpose, description-triggered in Claude Code and ingestable anywhere else.**

- Path: `C:\Users\user\Desktop\React\AirFlowClone\.claude\skills\airflowclone\SKILL.md`
- Symlink or copy alias also at `C:\Users\user\Desktop\React\AirFlowClone\AGENT_GUIDE.md` (or include a one-line top-level pointer) so non-Claude-Code clients have a canonical path to load.
- Frontmatter:
  - `name: airflowclone`
  - `description:` worded so Claude auto-invokes it when the user mentions running, authoring, triggering, retrying, or inspecting AirFlowClone DAGs/runs/tasks. Example: *"Drive the AirFlowClone DAG engine over HTTP at http://127.0.0.1:8000. Use when the user wants to list, author, trigger, retry, monitor, or fetch outputs from DAGs/runs/tasks."*
- Also user-invocable via `/airflowclone`.
- Frontmatter is YAML-fenced (`---`); the body below it is plain markdown and renders/reads correctly even when the frontmatter is ignored — so non-skill-aware clients lose nothing.

## Skill body — what it teaches the LLM

Keep the markdown tight (target ~200 lines, hard cap ~300). Written for the weakest expected reader (Haiku). Style rules:

- Imperatives, not narrative. "Do X." not "you might want to X."
- Every payload shown as a complete copy-paste-ready JSON block — no `...` ellipses, no "fill in the rest."
- Use full URLs (`http://127.0.0.1:8000/...`) in every example — don't assume the reader composed the base URL correctly.
- No conditional logic that depends on prior reasoning — checks are explicit ("if status is `failed`, do Y").

Sections, in this order:

1. **What this is.** Two sentences: what AirFlowClone is, what this file is for (driving the engine via HTTP).
2. **Prereq check (do this first, every session).** `GET http://127.0.0.1:8000/api/dags`. If it errors, tell the user to run `python -m airflowclone.main` from `backend/` and stop. Do not proceed without a 200.
3. **Authoring model — single rule.** Spec is the authoring source; the `.py` file is generated. Use `POST /api/dags` with a spec. Never write or edit `dags/*.py` directly for agent-authored DAGs. Hand-authored DAGs (no `spec_json`) cannot be edited via API — tell the user.
4. **Spec template (copy this, change the fields).** One worked JSON block: `dag_id`, `description`, `schedule` (nullable), `tasks[]` with `task_id`, `depends_on`, `body`. Body rules: function-body Python text; upstream task ids become kwargs; `return <json-serializable>` to pass data downstream.
5. **Validation-first workflow.** Always `POST /api/dags/preview` first. If `errors` is non-empty, fix the spec and preview again. Only call `POST /api/dags` when `errors` is `[]`.
6. **Async polling pattern — exact procedure.**
   - `POST /api/dags/{dag_id}/runs` → capture `id` from the response, call it `run_id`.
   - Loop: `GET /api/runs/{run_id}`. If `status` is `pending` or `running`, wait 2 seconds and loop again. Cap the loop at 300 iterations (10 minutes) before reporting a timeout to the user.
   - If `status` is `success`: for each task in `tasks[]`, optionally `GET /api/runs/{run_id}/tasks/{task_id}/output` and surface the values.
   - If `status` is `failed`: find the task whose `status` is `failed`. `GET /api/runs/{run_id}/tasks/{task_id}/log` for that task. Surface the log tail to the user. Offer `POST /api/runs/{run_id}/tasks/{task_id}/retry`.
7. **Endpoint cheat sheet.** Compact table — method, path, purpose, success status. One row per endpoint (~15 rows).
8. **Recipes.** Four self-contained examples, each runnable as-is:
   - `curl` GET dags
   - `curl` POST preview
   - `curl` POST create
   - PowerShell `Invoke-RestMethod` polling loop (the user's shell is PowerShell)
9. **Status code semantics.** What 400/404/409/500 mean *in this engine* (parse error, unknown DAG, hand-authored conflict, internal). Action per code, no guessing or blind retry.
10. **What NOT to do.** Explicit "don't" list: don't edit `.py` files for UI/agent-authored DAGs; don't poll faster than 2s; don't `POST /api/reload` after every edit (only after editing a hand-authored `.py`); don't assume a run is done without checking `status`.

**Helper scripts: deferred, with one contingency.** v1 ships no helper — the polling loop is short enough that even Haiku should handle it given the explicit procedure in section 6. **Contingency:** if the smoke test (verification step 9) shows Haiku failing on polling, add `wait_for_run.ps1` and `wait_for_run.sh` shell helpers in the same skill directory and update section 6 to "prefer the helper script; fall back to the loop if shell access is limited." Do not pre-build the helpers.

## Files to add / modify

| File | Action |
|---|---|
| `C:\Users\user\Desktop\React\AirFlowClone\.claude\skills\airflowclone\SKILL.md` | **new** — the skill content above (single source of truth, frontmatter + portable markdown body) |
| `C:\Users\user\Desktop\React\AirFlowClone\AGENT_GUIDE.md` | **new** — one-liner: "See `.claude/skills/airflowclone/SKILL.md` — same file works as a skill in Claude Code or as an injected system prompt for any Claude variant." Gives non-Claude-Code consumers a discoverable entry point. |
| `C:\Users\user\Desktop\React\AirFlowClone\NOTES.md` | append a "Session 2" block: spec/.py decision resolved; MCP deferred in favor of skill; cross-model portability constraint documented |
| `C:\Users\user\Desktop\React\AirFlowClone\README.md` | small addendum under Roadmap: "Agent driver: implemented as a portable skill at `.claude/skills/airflowclone/SKILL.md`. Works in Claude Code and as injected context for any Claude variant. MCP wrapper deferred." |

Nothing in `backend/` or `frontend/` changes.

## Future direction — multi-channel LLM/user coordination (NOT implementing)

Capture as design intent only, in the same `NOTES.md` append:

- **Vision:** a pub/sub channel layer where multiple LLMs (potentially different Claude variants — Opus authoring, Sonnet reviewing, Haiku monitoring) and end-user(s) can join the same channel to coordinate on running DAGs — broadcast status changes, share intermediate outputs, group-chat about the work.
- **Multi-model is already in scope today.** The portable-skill design (above) is the first step: any Claude variant can already read the same `SKILL.md` and drive the engine. A future channel layer adds *coordination* on top of that shared driver.
- **Likely transport:** WebSocket or SSE service alongside FastAPI (not in the REST request/response path).
- **The skill approach does not paint us into a corner:** the skill is instructions; when a pub/sub service is added later, an updated section or a sibling `CHANNELS.md` teaches every Claude variant how to subscribe — same portability model.
- **One concrete hook to leave undisturbed:** `executor.py` already writes status transitions to the DB at a single point — that's the natural place to emit channel events later. Don't bury that write deeper in v1.
- Out of scope for this plan; revisit when there is a real second-LLM use case to drive concrete requirements.

## Verification

End-to-end smoke test, in order. **Steps 1–8 verify the skill works for the primary client (Opus/Sonnet via Claude Code). Step 9 verifies cross-model portability — required to call the plan done.**

1. **Backend up.** `cd backend; .\.venv\Scripts\Activate.ps1; python -m airflowclone.main`. Confirm `http://127.0.0.1:8000/docs` loads.
2. **Skill discoverable.** Open Claude Code in `C:\Users\user\Desktop\React\AirFlowClone`. Confirm the skill appears in the available-skills list and via `/airflowclone`.
3. **List DAGs.** Ask Claude: "list my airflowclone dags". Skill should fire, hit `GET /api/dags`, return `example_etl`.
4. **Preview + create.** Ask: "author a tiny dag `skill_smoke` with one task that returns `[1,2,3]`". Expect a preview call, then create. Verify `dags/skill_smoke.py` exists on disk.
5. **Trigger + poll.** Ask: "run it and tell me when it's done." Expect `POST /api/dags/skill_smoke/runs` then polling on `GET /api/runs/{run_id}` until terminal, then output fetch returning `[1,2,3]`.
6. **Retry flow.** Update `skill_smoke` body to `raise RuntimeError("boom")` via `PUT /api/dags/skill_smoke`. Trigger; observe failure; ask Claude to fetch the log and explain; revert body; retry; confirm success cascades.
7. **UI cross-check.** Open `http://localhost:5173` — skill-authored DAG and its runs appear (same SQLite, same `dags/`, same `runs/`).
8. **Hand-authored guardrail.** Ask Claude to "edit the example_etl spec" — expect it to hit `GET /api/dags/example_etl/spec`, receive 404, and tell the user the DAG is hand-authored and must be edited as a `.py` file.
9. **Cross-model smoke (Haiku).** Using the Anthropic API directly (small Python script: read `SKILL.md`, prepend as system prompt, give the model shell-tool access or paste in `curl` outputs as user turns), ask `claude-haiku-4-5-20251001` to run the trigger+poll flow on `skill_smoke`. Expected: Haiku follows the procedure, polls correctly, reports output. If Haiku writes a broken polling loop or skips the prereq check, that's a skill-clarity bug — tighten the offending section. Trigger the contingency (ship `wait_for_run.ps1`/`.sh`) only if clarity fixes do not resolve it.

If step 2 fails (skill not visible), the most likely cause is the skill directory location or frontmatter format — fix before continuing. If step 9 fails on instruction-following rather than capability, do not lower the bar by simplifying the engine — fix the skill prose.
