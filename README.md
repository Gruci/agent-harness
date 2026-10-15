<div align="center">

# agent-harness

**Every AI session picks up where the last one left off — as if one engineer did all the work.**

Plans, decisions, conventions and lessons stay in the repo, and hooks keep every session working from them —
Claude Code or Codex, today's session or next month's.

agent-harness v1.1.0 · Claude Code · Codex

[English](README.md) · [한국어](README.ko.md)

<img src="docs/readme/handoff.en.svg" width="900" alt="Today three agent sessions work on separate tasks at the same time and write into one harness; tomorrow the next agent reads it and picks up where the plan left off.">

</div>

## What carries over between sessions (template)

| | Without | With agent-harness |
|:--|:--|:--|
| A new session starts | You explain the project again | It gets the open tasks, reads their plans and continues from the next step |
| Yesterday's decisions | Gone with the chat | Kept in the plan. Rejected ideas are recorded so they are not proposed again |
| Conventions | Each session invents its own | One registry. A renamed copy of an existing function is caught |
| A mistake | Happens again next week | Written up as a lesson, and turned into a check when it can be |
| Several sessions at once | They overwrite each other | One worktree per task. A shared board shows who has what |
| Claude Code and Codex | Follow different rules | Read the same rules and run the same checks |
| "Done" | A claim | The full check has to pass before the work merges |

<details>
<summary><b>Two ways to install — the full template or the checks-only plugin</b></summary>

| | Template — the full harness | Plugin — the checks only |
|:--|:--|:--|
| How | Clone into a new project | Two commands in Claude Code, on any existing repo |
| Open tasks, plans, decisions and lessons carried to the next session | ✓ | — |
| Checks on save, at session end, before push | ✓ | ✓ |
| Blocks writing source files through the shell | ✓ | ✓ |
| Plan before code: scope → research → plan → your approval | ✓ | — |
| One worktree per task and a shared task board | ✓ | — |
| GitHub remote | optional — without one, finished work merges locally | — |
| Codex support | ✓ | — |
| Lessons become gates, the harness map stays in sync, maintenance reminders | ✓ | — |
| Update | `python -X utf8 harness_install.py --upgrade` | `/plugin update agent-harness@agent-harness` |

</details>

## Quick start — template

```bash
git clone https://github.com/Gruci/agent-harness.git my-project
cd my-project
python -X utf8 harness_install.py --new
```

Same in PowerShell, cmd and bash (`python3` on macOS and Linux). Needs Python 3.10+ and git; GitHub is optional.

> **Permissions.** Inside this folder Claude Code runs without approval prompts, and hooks still stop irreversible commands. `setup_global_permissions.py` turns prompts off for **every project on this computer** — run it only if you want that.

Open Claude Code in the folder and say:

```
set up the harness
```

It asks what you want to build, helps you pick a stack, and sets everything up. Then just ask for work:

```
add a login feature
```

## Quick start — plugin

```
/plugin marketplace add Gruci/agent-harness
/plugin install agent-harness@agent-harness
```

Then say `set up the harness` in the repo you want checked. Only a settings file and a few check records are added; other repos are left alone.

## How a change flows (template)

```
[questions] → [research] → [plan] → [approval] → [build + checks] → [pre-merge check] → [merge]
                                        ▲
                                  where you answer
```

- You answer twice: the scope questions and the plan approval. Screen work adds a mockup to approve.
- Small fixes (up to 3 files, 40 lines) skip the plan; a fix that grows goes back to one.
- Each task is built in its own work copy (worktree). The main folder holds only plans and the task board.
- Every save runs the checks, and the AI fixes what they find.
- Nothing merges or pushes until every check passes.

## What it catches

The rules every session works under. When one is broken the session hears about it right away, and the work cannot merge until it is fixed.

<p align="center"><img src="docs/readme/gate-demo.svg" width="900" alt="A recorded Claude Code session: agent-harness refuses a shell write, blocks a 520-line file, and the agent stops instead of working around the gate."></p>
<p align="center"><sub>A recorded session with the plugin. The agent tries to write a file through the shell and is refused, writes a 520-line file and hits the 400-line limit, then stops instead of working around the gate. The grey lines are notes added for this README.</sub></p>

A few examples. How the pieces fit together and what the terms mean is in the [overview](dev/OVERVIEW.md) (Korean); the full list of checks is in the [harness map](dev/HARNESS.md).

| Caught | Why |
|:--|:--|
| New code with no assigned component | Decide where it belongs first so the structure holds |
| Hard-coded colors in screen code | Colors live in one place |
| Fixed pixel widths | They break phone screens |
| Files over 400 lines, functions over 80 | One file, one function, one job |
| API keys in source | Move them to settings; rotate if already pushed |
| Docs pointing at files that don't exist | Leftovers from a rename |
| An existing function rebuilt under a new name, or copied with its variables renamed | One job, one place |
| A second HTTP client, database connection or date formatter | One module owns each shared capability |
| Mixed naming — camelCase functions or response keys in a snake_case project, `get_` and `fetch_` for the same data | Names follow one style |
| A route that returns its own error or response shape | Every response goes through one wrapper |
| An API with no screen that uses it | Users can't see it |
| Force-pushing over the main branch, wiping the main folder, deleting outside the project | It can't be undone. The AI stops and leaves it to you |

<details>
<summary><b>Reading check results — what [OK], [FAIL], [SKIP] and the other marks mean</b></summary>

| Mark | Meaning | What to do |
|:--|:--|:--|
| `[OK]` | Checked, no problems | Nothing |
| `[FAIL]` | Rule broken | Fix it. It won't be merged into the main copy until fixed |
| `[WIP]` | A violation inside a work copy | Fix it before merging. It doesn't block while you work |
| `[SKIP]` | Settings empty, so it didn't run | Fill in the setting. Not a pass |
| `[N/A]` | Doesn't apply to this kind of project | Nothing |
| `[TOOL]` | A required tool is missing | Install it. Not counted as done |
| `[DECISION]` | A new classification needs your decision | Answer the proposal |
| `[REPORT]` | An uncertain signal | Take a look |

Guesses never block. For example, "this work copy looks finished" is only a warning; you can still end the session.

</details>

## FAQ

| Question | Answer |
|:--|:--|
| Can I install before choosing a stack? | Yes. You pick it together before the first line of code. |
| Which languages are checked? | Python, Go, TypeScript and Java out of the box. Setup ports any other language with one short file. |
| No screens, but screen checks show `[SKIP]` | Set `ARCH = "backend_only"` or `"headless"` in `harness_profile.py`. |
| Do I need GitHub? | No. Without a remote, work merges on your computer. |
| How do I drop a task? | Ask the AI. Unsaved or unmerged work is never deleted without your OK. |
| How do I update? | Plugin: `/plugin update agent-harness@agent-harness`. Template: `python -X utf8 harness_install.py --upgrade`. |

## Details

You don't need these to get started — the AI handles them.

<details>
<summary><b>Using it with Codex</b></summary>

Claude Code and Codex share the rules, the working steps and the check engine. The shared steps are in the [workflow index](dev/workflows/README.md).

```bash
python -X utf8 setup_global_permissions.py --agent both   # set up both tools at once
python -X utf8 harness_install.py --check-agents          # check the wiring
```

For the Codex side, Python 3.11+ is recommended (3.10 needs the `toml` package). Changes apply from the next session, and host policies such as company settings take precedence.

</details>

<details>
<summary><b>Work happens in work copies</b></summary>

- One session or many, every task gets its own work copy at `worktrees/<task scope>--<session tag>`, so the list shows who is doing what.
- Starting a task registers it on the work board (`workboard/`). Editing code without registering is blocked.
- Touching a scope another session has claimed shows a warning.
- While a work copy exists, commits and branch switches in the main folder are blocked. Merge a finished branch with `git merge --ff-only <branch>`.
- Every check runs in that folder right before push, PR or merge, and nothing goes out until it passes.

</details>

<details>
<summary><b>Manual install</b></summary>

```bash
python -X utf8 harness_install.py --doctor            # check the environment; exit 1 if something would block
python -X utf8 harness_install.py                     # create settings and verify
python -X utf8 setup_global_permissions.py            # optional: turns approval prompts off for EVERY project on this computer
```

You need a Git repository and Python 3.10+ (as `python` or `python3`). Screen checks need Node.js and ESLint in the screen folder; Go can use tree-sitter when it is installed. `--doctor` lists anything missing and says which items block.

For a project that already has code, run `--dry-run` first to see current violations.

</details>

## Changelog

| Version | Changes |
|:--|:--|
| **v1.1.0** | Broader language support. |
| **v1.0.0** | First public release. |

## License

Daehyun Kim · [LinkedIn](https://www.linkedin.com/in/daehyun-kim-b00365176/)

MIT License
