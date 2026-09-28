# AGENTS.md — Codex project harness

> 담는 것: Codex 세션의 행동 규칙과 라우팅. 담지 않는 것: Claude 전용 행동 규칙(→ `CLAUDE.md`)·상세 규칙(→ 각 정본 MD). 읽는 시점: Codex 세션 진입 시.

This is the Codex-only entry point for this project. Claude Code uses `CLAUDE.md` and `.claude/`; Codex uses this file, `.agents/`, and `.codex/`.

## Dual-agent boundary

- Ordinary Codex work must not load `CLAUDE.md` or scan `.claude/`.
- Shared skill procedures live in [dev/workflows/README.md](dev/workflows/README.md); each Codex skill reads the relevant procedure directly.
- `impeccable-cdx` alone may read the unchanged vendor `.claude/skills/impeccable/SKILL.md` and the task-specific references and scripts it requires. Do not preload or modify vendor assets.
- Worktree operations may use the shared location specified in `workboard/README.md`; that is not permission to load Claude instructions.
- Shared project truth lives in `README.md`, `dev/DEVGUIDE.md`, `design/DESIGN_GUIDE.md`, `dev/`, `design/`, and `kernel/runner.py`.
- Codex-only behavior belongs in `AGENTS.md`, `.agents/`, or `.codex/`. Edit Claude-only harness files only for explicitly requested interoperability.
- Codex skill names end in `-cdx`.

## Initial Codex setup

This harness uses autonomous execution after scope and plan approval.
At initial setup, run `python -X utf8 setup_global_permissions.py --agent codex --check`.
If the global setup is missing, install it with `python -X utf8 setup_global_permissions.py --agent codex`.
The installer preserves unrelated user settings and globally installs the rule that the user is asked only to clarify ambiguous requirements or to approve a plan.
If the runtime enforces its own restrictions, installation may need one approval, and those restrictions stay in effect for the current session.
Do not repeat setup when the check passes.

## Editing prerequisites

Before starting implementation, list `workboard/` for open tasks (one untracked file per task; protocol in that directory's README), then load only the documentation relevant to the target.

| Target | Required shared documentation |
|---|---|
| Any Markdown you write or edit | `dev/MD_STANDARD.md` — three rules and the content test (what belongs in Markdown) |
| Any new file or function | `dev/CONVENTIONS.md` — decided conventions and helper registry |
| Product code in any language | `dev/DEVGUIDE.md`, `dev/ARCHITECTURE.md`, and `dev/COMPONENTS.md` |
| `frontend/` React and TypeScript | `design/DESIGN_GUIDE.md`, then the relevant `design/` sub-document |
| Database schema, tables, columns | `dev/DATA_MODEL.md` and `dev/NAMING.md` |
| Screen work of any kind | `design/RESPONSIVE.md` — desktop and mobile are defined together at plan time |
| Tests | use `$test-cdx`, which routes to `dev/TESTING.md` |
| Harness, hooks, gates | `dev/HARNESS.md` |
| Disputing a rule | `dev/LESSONS.md` — the incident behind it |

Search first and read targeted ranges. Do not preload unrelated Markdown.

## Change workflow

- Use `$feature-workflow-cdx` for code changes except an obvious typo or one configuration value.
- The shared [change procedure](dev/workflows/feature-workflow.md) owns research, scope approval, implementation, verification, and archive requirements.
- Existing approval of a concrete proposal remains valid; record it and continue without repeating the same approval request.
- Runtime filesystem or sandbox approvals are separate from task approval. Request only access actually required by a failed operation; never weaken global permissions as an implementation shortcut.
- At implementation start, check `workboard/` and create a task file named after the change scope, tagged `#sid:<session id first 8>`. If the scope already has a file, add your items to it (join) or branch your worktree from its branch (stack) instead of opening a duplicate.
- Implement in your own worktree (`worktrees/<scope>--<sid8>`, protocol in `workboard/README.md`). The shared PreToolUse hook blocks edits in the main checkout and any edit before your `#sid` task file exists; the exemptions are `workboard/**`, `docs/tasks/**`, and edits that change at most one line.
- Inside a worktree the save and stop gates only notify with a `[WIP]` message. Before `git push`, `gh pr create`, `gh pr merge`, or `git merge` the hook runs `python -X utf8 -m kernel.runner --verify` in that checkout and blocks unless it exits 0.
- Preserve unrelated edits. Never commit, revert, clean, reset, or delete them.
- Use task-suffixed document names when another session may be active: `docs/tasks/research_<task>.md` and `docs/tasks/plan_<task>.md`.
- Archive both documents under `docs/tasks/archive/YYYY-MM-DD-<task>/` in the same turn implementation completes, then delete your task file from `workboard/`.

## Repository invariants

- Preserve component responsibilities and allowed dependencies in the approved graph; see [dev/COMPONENTS.md](dev/COMPONENTS.md).
- Before the first product code, select the stack with the user and run [the assembly workflow](dev/workflows/harness-assembly.md).
- New classifications or boundaries require a concrete proposal to the user and a record of the user's actual response. Routine edits within approved boundaries do not repeat approval.
- UI uses the selected project stack and approved delivery component. Verify the consuming screen when a feature includes one.
- Before changing a signature or response shape, trace callers and consumers across DB, API, and React.
- Prefer existing helpers, the standard library, native platform features, and installed dependencies. Make surgical changes. Report unrelated dead code without removing it.
- Architecture and database conventions live in `dev/ARCHITECTURE.md`, `dev/NAMING.md`, `dev/DATA_MODEL.md`, and `dev/CONVENTIONS.md`. `kernel/runner.py` enforces the machine-checkable subset.

## Evidence and debugging

- Verify paths with search, database state with queries, and behavior by reading or running code. Never state an assumption as fact.
- Reproduce and trace the root cause, compare against a working pattern, test one hypothesis with the smallest change, then add a regression test and fix it.
- After three failed fix attempts, stop editing and report the evidence and the likely architectural issue.
- Re-read targets that may be stale after compaction or concurrent edits.

## Verification and completion

- Run `python -X utf8 -m kernel.runner` and the checks proportionate to the change before claiming completion.
- A bug fix must show its reproduction test passing. UI work also requires a rendered inspection.
- Do not claim a test or build passed unless that command exited 0 in this checkout.
- Update the relevant shared Markdown in the same turn as durable contracts, routes, components, schemas, or user rules. Write it to `dev/MD_STANDARD.md`: one meaning per line, one fact in one place, and nothing that Glob, Grep, or git log already answers.
- Enforce checkable rules in `kernel/runner.py` or another deterministic gate. Markdown explains the rule but is not its enforcement. The Markdown style gate validates structure at write time and `md_style_baseline.txt` may only shrink.

## Codex harness

Use the smallest applicable skill from `.agents/skills/`.
Read [dev/HARNESS.md](dev/HARNESS.md) for shared hook installation, runtime trust, and verification boundaries.
The shared simplicity ladder is [dev/workflows/simplicity.md](dev/workflows/simplicity.md).
Delegated results must be concise and include file:line evidence.
