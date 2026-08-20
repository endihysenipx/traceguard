# Agent Handoff

## Current State

- Architecture and scope are approved.
- Deterministic domain-core and Phases 2 through 5 are complete.
- Implemented core enums and canonical errors, immutable Pydantic contracts, separated structural/domain/business validation, three legal-transition tables, and fail-closed deterministic recovery policy.
- Implemented the protocol-backed in-memory trace repository, append-only events/artifacts, four editable fixtures, deterministic workflow orchestrator, and stateful mock ERP.
- Implemented the shared extraction-provider protocol, explicit `SCRIPTED`/`LIVE` modes, exact-fixture scripted adapter, and live OpenAI Responses API structured-extraction adapter.
- Implemented the five-entry tagged local runbook, deterministic exact-tag/lexical retrieval, exactly four scoped read-only tools, append-only tool-call history, causal evidence validation, and one three-turn/six-call investigator with scripted and live model paths.
- Implemented a deterministic recovery coordinator that constructs policy input from stored workflow/report facts, persists append-only decisions, and executes only a policy-authorized same-input ERP retry.
- Implemented append-only recovery execution lifecycle records, repository-level idempotency claims, current-state policy re-evaluation, a policy-provided backoff seam, and terminal `RECOVERED`/`RETRY_EXHAUSTED` outcomes without rewriting the failed workflow.
- Added minimal OpenAI dependency/environment declarations and a credential-gated live smoke entry point.
- Added 147 focused unit and integration-style tests; the latest full run passed in 1.88 seconds with no network or API key.
- No FastAPI endpoint, UI, deployment configuration, or final README work exists yet.

## Approved Architecture

- One FastAPI application with a thin static browser UI.
- Editable scenario fixtures supply request text and explicit mock ERP behavior.
- In-memory append-only trace repository behind an interface.
- Live OpenAI Responses API extraction is the primary custom-input path; scripted extraction supports exact fixture text only and never falls back or heuristically parses edits.
- Pipeline: extraction → structural/type validation → deterministic domain validation → deterministic business-rule validation → mock ERP.
- One investigator, three-turn/six-tool-call budget, and four read-only tools: `get_run_overview`, `get_run_events`, `get_stage_artifact`, `search_runbook`.
- Local tagged/lexical runbook retrieval.
- Deterministic policy owns recovery authorization; only one idempotent ERP retry may execute.
- ERP-unavailable scenario contains non-causal warnings/recovered errors before the terminal 503.

## Terminology and Core Enums

- Policy decisions: `ALLOW`, `BLOCK`, `REQUIRE_REVIEW`.
- Recovery actions: `NO_ACTION`, `RETRY_SAME_INPUT`, `REQUEST_INPUT_CORRECTION`, `REQUEST_HUMAN_REVIEW`.
- Workflow states: `CREATED`, `EXTRACTING`, `STRUCTURE_VALIDATING`, `DOMAIN_VALIDATING`, `BUSINESS_VALIDATING`, `ERP_CALLING`, `SUCCEEDED`, `FAILED`.
- Investigation states: `NOT_REQUIRED`, `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`.
- Recovery states: `NONE`, `ALLOW`, `BLOCK`, `REQUIRE_REVIEW`, `RETRYING`, `RECOVERED`, `RETRY_EXHAUSTED`.
- Event outcomes: `CONTINUED`, `RECOVERED`, `TERMINAL`, `SUCCESS`.
- Extraction-provider modes: `SCRIPTED`, `LIVE`.
- Evidence roles: `TERMINAL_CAUSE`, `SUPPORTING`, `NON_CAUSAL_CONTEXT`.
- Core canonical errors: `ORDER_STRUCTURE_INVALID`, `CUSTOMER_NUMBER_MISSING`, `PRODUCT_CODE_MISSING`, `QUANTITY_MISSING`, `QUANTITY_NON_POSITIVE`, `ERP_UNAVAILABLE`.

The deterministic workflow owns canonical errors. The investigator diagnoses and recommends but does not authorize or execute recovery.

## Next Implementation Task

After explicit approval, implement Phase 6 only: assemble the FastAPI routes and thin static demo UI around the completed workflow, investigation, policy, and controlled-recovery services. Do not begin deployment or final README work unless separately approved.

## Phase 1 Implementation Notes

- Added `PRODUCT_CODE_MISSING` and `QUANTITY_MISSING` alongside the planned core codes so every required field has an explicit deterministic domain error.
- All three missing required-input errors return `REQUIRE_REVIEW` for correction or human-review recommendations and `BLOCK` for conflicting actions.
- `PolicyInput` permits absent diagnosed fields only so malformed or unavailable investigation output can be represented without invented values; policy returns `BLOCK` with `INVALID_INVESTIGATION`.
- Policy checks both diagnosed code and diagnosed category against the deterministic canonical mapping before considering an action.
- These are contract refinements, not changes to the approved responsibility or recovery boundaries.

## Phase 2 Implementation Notes

- Workflow runs retain the submitted text unchanged, preset metadata, explicit ERP behavior, orthogonal states, canonical deterministic failure facts, idempotency key, attempt count, and timestamps.
- Repository event and artifact histories are append-only; collection reads return tuples and artifact reads are deep copies.
- Phase 2 initially used an injected extraction callable; Phase 3 replaced it with the explicit extraction-provider protocol. The orchestrator reuses every Phase 1 validation boundary and never branches on `preset_id`.
- Failed runs retain their complete trace and enter investigation state `PENDING`; successful runs retain no failure facts.
- `FAIL_ONCE_503` records the optional-field warning only when validated delivery instructions are absent, then records the recovered cache failure, successful fallback, and terminal ERP 503 in order. The fixture retains the full noisy sequence; a direct adapter-level second attempt succeeds, but no recovery execution path exists.
- Phase 2 introduced no architectural deviation from the approved plan.

## Phase 3 Implementation Notes

- `ExtractionProvider.extract(order_request_text)` is the production-facing boundary; the orchestrator passes submitted text unchanged and always invokes deterministic structural validation on the returned object.
- `ScriptedExtractionProvider` matches only the four exact fixture request texts, returns defensive JSON-compatible dictionaries, and raises `UnsupportedScriptedInputError` for edited or custom text.
- `OpenAIExtractionProvider` uses the official Python SDK's Responses API `responses.parse` method with a strict four-field Pydantic response schema, `store=False`, a 256-token output cap, and a bounded per-request timeout.
- The default live model is `gpt-5.4-nano`; `TRACEGUARD_OPENAI_MODEL` overrides it and `OPENAI_API_KEY` is required without fallback.
- Provider configuration, timeout, request, refusal, and malformed-output failures use sanitized exceptions. Workflow logic collapses all provider failures to deterministic `EXTRACTION_MODEL_ERROR` without retaining raw provider details.
- Provider mode is retained as run metadata. Moving this cross-cutting enum to the domain enum module resolved an initial package import cycle without changing the approved responsibility boundaries.
- The credential-gated smoke entry point was executed locally and skipped cleanly because no API key was present; no real live call has yet been verified.

## Phase 4 Implementation Notes

- The runbook contains five stable entries covering extraction failure, structural failure, missing required input, non-positive quantity, and ERP unavailability. Ranking uses exact supplied error-code/tag match, then normalized token overlap, then stable entry ID.
- The registry exposes only `get_run_overview`, `get_run_events`, `get_stage_artifact`, and `search_runbook`. Pydantic argument schemas, current-run UUID checks, bounded JSON results, and repository read methods enforce the boundary.
- `get_run_overview` omits canonical error code/category and root cause. Initial model context contains the run ID, role, hard budgets, and untrusted-data warning but no trace or canonical run failure.
- Evidence items now carry `TERMINAL_CAUSE`, `SUPPORTING`, or `NON_CAUSAL_CONTEXT`. Validation requires causal terminal evidence, target-run ownership, prior retrieval through `get_run_events`, and prior retrieval of cited runbook IDs. It deliberately does not compare diagnosis to the hidden canonical workflow error.
- Tool-call records are append-only and include sequence, validated/sanitized arguments, success/failure, and bounded results. Investigation reports and sanitized failures are additive; workflow events, artifacts, canonical failure facts, ERP attempts, and recovery state remain unchanged.
- `ScriptedInvestigatorModel` is explicitly deterministic/non-AI but executes the real tools and derives reports from returned events, artifacts, and runbook results without using `preset_id`.
- `OpenAIInvestigatorModel` uses the official Responses API `responses.parse` tool loop with strict function schemas, structured `InvestigationReport`, `store=False`, disabled parallel calls, a bounded timeout, and stateless replay of response items plus function outputs.
- Runs retain separate extraction and investigation provider-mode metadata. `TRACEGUARD_OPENAI_INVESTIGATOR_MODEL` overrides the shared model setting when present.
- The live investigator smoke entry point skipped cleanly because no API key was available; the external live investigator remains unverified locally.

## Phase 5 Implementation Notes

- `RecoveryCoordinator.recover(run_id)` accepts no caller-supplied action or canonical facts. It loads the failed run and completed stored report, builds `PolicyInput`, and delegates authorization to the existing `evaluate_recovery_policy()` function.
- Policy decision records are append-only and retain report ID, decision, allowed action, reason codes, and constraints. Recovery execution history is also append-only: an atomic `STARTED` claim for the run/idempotency key precedes any side effect, followed by `SUCCEEDED`, `FAILED`, or `BLOCKED`.
- The coordinator validates authorization both before claiming execution and again after the policy backoff immediately before the side effect. The final guard reloads the run/report, verifies the current stored `ALLOW` decision/action/key/constraints and active claim, re-evaluates policy with the latest attempt count, and fails closed if state changed.
- Retry ordering is `ALLOW` -> atomic `STARTED` claim -> policy backoff -> final authorization guard -> `RETRYING` -> ERP submit. A stale post-backoff authorization completes the claim as `BLOCKED` and uses the legal `ALLOW` -> `BLOCK` transition without an ERP call.
- The retry reconstructs a strict `ValidatedOrder` from the successful business-validation artifact. It does not rerun extraction, validation, or investigation, and it never edits submitted input.
- The authorized `FAIL_ONCE_503` retry honors the policy's one-second backoff and succeeds as total ERP attempt 2. Duplicate calls return the recorded execution and cannot create attempt 3.
- Retry failure transitions only recovery state to `RETRY_EXHAUSTED`; workflow state, canonical failure, original events, investigation report, and tool history remain intact.
- Phase 5 deliberately added no recovery tool to the investigator. Its registry remains exactly four read-only tools.
- The implementation plan's earlier phrase controlled ERP retry endpoint was clarified to domain path; HTTP assembly remains Phase 6 as required by the approved sequencing.

## Constraints That Must Not Be Violated

- Use `REQUIRE_REVIEW` consistently for human correction or review.
- Presets are editable convenience fixtures, not hidden workflow logic.
- Pass custom text unchanged to the live provider; arbitrary custom extraction requires that provider.
- Reject unsupported custom input in scripted mode rather than ignoring edits or fabricating parsing.
- Keep structural/type, domain-required-field, and business-rule validation distinct.
- Do not expose the canonical workflow error or full trace in the investigator's initial context or overview tool.
- Keep investigator tools read-only, allowlisted, bounded, and scoped to the current run.
- Make continued/recovered noise distinguishable from terminal evidence.
- Require terminal evidence in the investigation report.
- Require cited event and runbook evidence to have been retrieved through actual successful tool calls.
- Default deterministic policy to `BLOCK` for invalid, conflicting, or unknown conditions.
- Preserve failed traces; corrected input creates a new run.
- Do not add multiple agents, React, database persistence, vector RAG, or general autonomous remediation.
- Update the retrospective only with real events.

## Unresolved Questions

None. Provider model name and API key are runtime environment settings, not architecture decisions.
