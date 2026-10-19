# Distributed team execution

> Holds: ownership, trust and operating contracts for multiple computers developing one repository. Excludes: local worktree mechanics in [the workboard protocol](../workboard/README.md). Read when: enabling, operating or recovering team execution.

## Responsibilities

Each computer keeps its own clone, worktrees and ignored workboard.
The optional coordinator owns shared execution metadata.
Git remains the authority for source, reviewed decisions and immutable submitted commits.
GitHub CI and the protected merge queue own integration into the default branch.
Local metadata updates do not commit to main or start code CI.

TEAM is disabled by default.
Enabling it requires the PR merge flow.
An independent writer uses its own worktree.
Related tasks can share a goal identifier without sharing a working directory.
Separate, reviewable changes use separate PRs.
Closely related work may be integrated into one reviewed submission with reservations covering the entire diff.

## Coordinator deployment

Run the coordinator on a host all participating computers can reach.
Its SQLite database belongs on that host's local filesystem.
Never share the database file over a network filesystem.
The server serializes short metadata transactions, not the developers' entire execution.
The serve command's max-active setting bounds active work and submitted integration reservations together.
Tune that capacity against CI runner availability and merge waiting time.

Keep the server configuration outside the repository.
Credentials are distinct environment variables containing at least 32 printable characters.
The server derives the actor and integration capability from the authenticated credential.
The client cannot choose its actor or grant itself integration privileges.

```json
{
  "repository": "your-organization/your-repository",
  "actors": {
    "developer-a": {"token_env": "TEAM_DEVELOPER_A_TOKEN", "role": "worker"},
    "developer-b": {"token_env": "TEAM_DEVELOPER_B_TOKEN", "role": "worker"},
    "ci": {"token_env": "TEAM_INTEGRATION_TOKEN", "role": "integration"}
  }
}
```

```console
python -X utf8 -m kernel.team serve --database /srv/harness/team.sqlite --config /srv/harness/team.json
```

Loopback binding is the default.
Remote client connections require HTTPS.
For direct TLS, configure tls.certfile and tls.keyfile in the server configuration.
An explicit reverse_proxy setting permits a non-loopback listener behind an operator-managed TLS proxy.
That listener must be isolated from direct worker access.
Tokens are never passed as command-line arguments or committed in receipts.
Back up the coordinator database with SQLite's backup facilities while it is running.
Retain its event history when investigating ownership or merge incidents.

## Connecting each clone

The shared profile declares the endpoint and repository identity.
The repository must match the clone's origin using the harness's existing remote normalization.
Each computer supplies its own credential through the configured local environment variable.

```python
MERGE_FLOW = "pr"
TEAM = {
    "url": "https://coordinator.example",
    "repository": "your-organization/your-repository",
    "token_env": "HARNESS_TEAM_TOKEN",
}
```

Use the local task start command with explicit write paths.
The optional goal identifies the common outcome.
The optional depends-on argument lists coordinator task IDs that must be merged before this task starts.
Read-only preparation can happen before a writing task is eligible.

```console
python -X utf8 -m kernel.task start orders-export-api --sid abcdef12 --branch feat/orders-export-api --touch api/export.py tests/test_export.py --plan docs/tasks/plan_orders-export-api.md --goal orders-export
python -X utf8 -m kernel.team heartbeat --scope orders-export-api
```

Keep the heartbeat command running while the worker is executing.
It stops renewing when the local receipt records submission or cancellation.
Edit guards also renew a nearly expired active receipt before editing.
Stopping heartbeats eventually expires an active claim.
Submission transfers the reservation to integration; a submitted task does not expire with the worker.

## Ownership and conflict policy

Claim atomically reserves the task and every requested write resource.
An overlap rejects the entire request, leaving no partial reservation.
Independent resources can proceed concurrently within the configured repository capacity.
File paths are repository relative and normalized conservatively for mixed Windows and Linux clients.
A glob reserves its fixed parent subtree, including future files.
A broad glob can therefore serialize more work than expected.
Prefer explicit paths or narrow component subtrees.
Named contract resources reserve changes to shared API or schema contracts.
Reading a contract does not require its write reservation.
Contract reservations do not authorize source-file edits by themselves.

```console
python -X utf8 -m kernel.team scope orders-export-api expand --resources api/export_types.py contract:orders-export-v1
```

Reserve added paths before editing them.
Local guards provide early feedback, and trusted CI validates the actual submitted Git diff.
Different files can still conflict semantically.
The component owner and merged-result tests must cover API consumers and data behavior.
Resource ownership does not prove the absence of semantic defects.

## Submission and integration

Team finish verifies the local worktree and freezes its base and head commits.
It opens or recovers the PR without repeatedly merging moving main into the worker branch.
The worker can request queue entry after the repository's required review policy is satisfied.

```console
python -X utf8 -m kernel.task finish --sid abcdef12
python -X utf8 -m kernel.team scope orders-export-api enqueue
```

Protect the integration branch against direct worker pushes and bypasses.
Require the product's behavior tests as well as the harness verification and team admission checks.
Protect changes to the CI workflow, coordinator configuration and admission checker with a separate trusted review policy.
Do not expose an integration credential to untrusted PR code.
The integration identity is trusted to run tests and inspect Git before attesting results.
The coordinator validates ownership and proof binding; it does not execute product tests itself.

The unprivileged harness workflow handles pull_request and merge_group candidates.
It uploads a small tested-candidate identity document as data.
The separate team-admission workflow runs on workflow_run using protected default-branch code and configuration.
It binds the source run, repository, workflow identity and tested commit before authenticating admission.
Candidate code and Python profiles are never executed with the integration credential.
The required commit status is harness-team-admission.
Bind that required status to the GitHub Actions app in the branch rules where the provider supports a required source.
Changes to protected source workflow policy require an operator-reviewed policy update before team admission.
It suppresses duplicate heavy branch-push runs when a PR already supplies the check path.
Only superseded runs of the same PR are cancelled.
Queue candidates retain their independent validation runs.
GitHub's native merge queue has repository and plan eligibility requirements.
Operators must enable it and configure the required checks themselves.

Admission reconstructs the expected tree from the frozen submitted commits and the candidate base.
The candidate tree must match that reconstruction.
This rejects extra edits even when they touch a path already reserved by a valid submission.
PR and queue candidates may record separate verification proofs for the same frozen worker head.
A changed queued head requires withdrawal and a new ownership epoch.

Supply the integration credential to the protected admission workflow as HARNESS_TEAM_CI_TOKEN.
An authorized integration operator can also supply it in a trusted local environment for recovery commands.
Keep that environment separate from candidate code and ordinary worker sessions.
Successful default-branch integration triggers reconciliation against GitHub's exact PR head and merge evidence.
Reconciliation releases reservations only after confirmation of the integration branch.
Run reconcile-all again if the coordinator was temporarily unavailable.
Task finish cleans the local worktree only after the coordinator and GitHub confirm completion.

## Recovery

```console
python -X utf8 -m kernel.team list
python -X utf8 -m kernel.team scope orders-export-api status
python -X utf8 -m kernel.team scope orders-export-api reclaim
```

The following recovery commands require integration authority through HARNESS_TEAM_CI_TOKEN or an integration-actor profile.
Run them from a trusted harness checkout.

```console
python -X utf8 -m kernel.team scope orders-export-api withdraw
python -X utf8 -m kernel.team reconcile-all
```

Expired claims can be explicitly reclaimed if no current owner conflicts.
Reassignment increments the epoch so late results from an earlier attempt are rejected.
Withdrawal retains reservations while clearing the frozen candidate and incrementing its epoch.
An integration operator must confirm that the exact frozen PR is closed before withdrawing a checked candidate.
The scope withdrawal command closes and rechecks the provider PR before changing the coordinator generation.
An already merged PR must be reconciled instead.
Mutating client operations persist retry identities before contacting the server.
After an ambiguous connection failure, retry the same operation before changing its arguments.
Never treat a failed remote lookup as an empty workboard.
The list command returns bounded pages of active reservations.
Use its next_cursor with the cursor argument for later pages.
Historical task state remains available by task ID.
An integration outage preserves submitted reservations for recovery.
Worker cancellation cannot release a submitted candidate without the integration authority.
Stop or withdraw queued PR work before administrative cancellation.

## Verification and limits

The local regression suite uses independent clones, a bare Git remote, real HTTP requests and real concurrent processes.
It exercises resource competition, stale owners, diff admission and local push recovery.
The suite does not establish an unmeasured hundreds-of-workers throughput guarantee.
Measure claim latency, integration wait, invalidated candidates and rework before increasing repository capacity.
The coordinator is one service and one durable database, not a highly available cluster.
Product test databases, ports and caches must use task-specific namespaces.
The harness does not provision an arbitrary product's external infrastructure.
Speculative merged-result CI reduces waiting; failures can still require rebuilding later candidates.
Dependency caches reduce setup costs without treating stale test results as successful checks.
Existing installations must install the matching workflows in addition to upgrading kernel files.
The ordinary kernel upgrade preserves project-owned workflows and does not change GitHub settings.
