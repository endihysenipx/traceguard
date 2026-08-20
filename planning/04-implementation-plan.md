# TraceGuard Implementation Plan

Planning artifacts are phase zero. Application work starts with the deterministic domain core.

## Phase 1 — Deterministic Domain Core

### Tasks

- Define workflow, investigation, recovery, failure, event-outcome, and recovery-action enums.
- Define Pydantic contracts for extracted candidates, domain orders, validated orders, events, investigation reports, and policy inputs/outputs.
- Implement structural/type, required-field/domain, and business-rule validation as separate operations.
- Implement allowed state transitions and the deterministic recovery-policy matrix.

### Dependencies

- Approved planning artifacts only.

### Acceptance criteria and tests

- Missing fields are allowed in `ExtractedOrderCandidate` but rejected by domain validation where required.
- Type/shape failures produce `ORDER_STRUCTURE_INVALID`.
- Missing customer produces `CUSTOMER_NUMBER_MISSING` only during domain validation.
- Negative quantity reaches business validation and produces `QUANTITY_NON_POSITIVE`.
- Tests cover every valid and invalid state transition and every policy branch.
- No LLM, HTTP, UI, or storage adapter is required to run this test group.

## Phase 2 — Trace Repository and Workflow

### Tasks

- Implement the in-memory repository abstraction and append-only trace operations.
- Add four fixture definitions containing editable text and explicit mock ERP behavior.
- Implement workflow orchestration and the stateful mock ERP, including fail-once-503 behavior.
- Record stage artifacts and noisy events with severity and outcome metadata.

### Dependencies

- Phase 1 models, validators, transitions, and errors.

### Acceptance criteria and tests

- Each fixture reaches its expected workflow state and canonical deterministic error using controlled extraction results.
- The ERP-unavailable trace includes a continued optional-field warning, a recovered cache failure/fallback, and a terminal 503 in order.
- Prior events remain unchanged after later operations.
- ERP attempts are observable and capped by the adapter contract.

## Phase 3 — Provider Boundary and Extraction

### Tasks

- Implement the shared LLM-provider interface.
- Add the fixture-limited scripted extraction adapter.
- Add the live structured-extraction adapter.
- Validate that the exact submitted textarea content reaches the live adapter.
- Reject edited/non-fixture content clearly in scripted mode.

### Dependencies

- Phase 1 extraction contract and Phase 2 workflow.

### Acceptance criteria and tests

- Default tests use no network or API key.
- All exact fixtures work through scripted mode.
- Unsupported scripted input fails explicitly and never falls back to fabricated parsing.
- A fake live client test proves the submitted text is passed unchanged and parsed structurally.
- Provider failure, refusal, timeout, and invalid output become sanitized workflow failures.

## Phase 4 — Investigator and Runbook

### Tasks

- Create tagged local runbook entries and deterministic exact-tag/lexical ranking.
- Implement the four scoped, read-only tools.
- Implement the bounded investigator loop for scripted and live providers.
- Validate and store the structured report and tool-call history.
- Enforce terminal-evidence requirements and safe failure behavior.

### Dependencies

- Phase 2 trace/artifact access and Phase 3 provider boundary.

### Acceptance criteria and tests

- Investigation is rejected for non-failed runs.
- The investigator starts without the canonical error or full trace.
- Tool arguments, response size, current-run scope, three-turn limit, and six-call limit are enforced.
- The noisy ERP integration test cites the terminal ERP event and does not classify continued or recovered warnings as causal.
- A report blaming the recovered cache warning is rejected or results in blocked recovery.
- Malformed output, unknown tools, and budget exhaustion record investigation failure safely.

## Phase 5 — Controlled Recovery

### Tasks

- Connect validated investigation output to deterministic policy.
- Implement idempotency-key creation, attempt records, policy re-evaluation, one-second backoff, and the controlled ERP retry domain path. The API endpoint belongs to Phase 6.
- Preserve the failed workflow trace while adding recovery events and statuses.

### Dependencies

- Phase 1 policy, Phase 2 mock ERP/repository, and Phase 4 report validation.

### Acceptance criteria and tests

- Every missing required-input error returns `REQUIRE_REVIEW` for correction or human-review recommendations; conflicting actions and negative quantity return `BLOCK`.
- Only eligible canonical `ERP_UNAVAILABLE` plus `RETRY_SAME_INPUT` returns `ALLOW`.
- The allowed retry succeeds on the second total ERP attempt.
- Repeated retry requests with the same idempotency key return the recorded outcome without another ERP call.
- Conflicting diagnosis, missing key, invalid report, or exhausted attempts produces `BLOCK`.

## Phase 6 — Thin Demo UI and API Assembly

### Tasks

- Add API endpoints and one static browser page.
- Populate the editable textarea and ERP behavior from preset controls.
- Display provider mode, workflow trace, artifacts, tool calls, report, policy, and recovery outcome.
- Show retry only for `ALLOW` and explain that `REQUIRE_REVIEW` requires correction and a new run.

### Dependencies

- Phases 2 through 5.

### Acceptance criteria and tests

- All four scenarios are demonstrable from one page.
- Edited live input is submitted unchanged.
- Scripted custom input produces a clear live-provider-required message.
- UI labels consistently use `REQUIRE_REVIEW` for human correction or review.
- The noisy trace visually distinguishes continued, recovered, terminal, and successful events.
- Lightweight API tests cover successful and invalid endpoint transitions.

## Phase 7 — Verification and Handoff

### Tasks

- Run deterministic unit and integration suites.
- Perform an opt-in live extraction/investigation smoke test when credentials are available.
- Document local startup, provider selection, architecture, scenario walkthrough, limitations, and test commands.
- Update the decision log, agent handoff, and retrospective using real implementation events only.

### Dependencies

- All implementation phases.

### Acceptance criteria

- Credential-free scripted fixture demo and test suite are reproducible.
- The live smoke test demonstrates genuine custom extraction and tool selection or records an honest external limitation.
- Documentation matches implemented behavior and explicitly labels scripted behavior.

## Cut Order If Time Is Constrained

1. Remove UI styling beyond one functional page.
2. Omit execution of the allowed retry while preserving and testing the policy decision.
3. Reduce runbook ranking to exact error-code/tag matching.
4. Remove reserved non-scenario error categories and automated live smoke-test wiring.

Do not cut the validation boundaries, editable fixture input, real live-provider path, visible tool use, noisy-trace test, structured output validation, deterministic policy, or four core scenario tests.
