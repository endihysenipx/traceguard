# Agent Handoff

## Current State

- Architecture and scope are approved.
- Deterministic domain-core phase is complete.
- Implemented core enums and canonical errors, immutable Pydantic contracts, separated structural/domain/business validation, three legal-transition tables, and fail-closed deterministic recovery policy.
- Added 60 focused unit tests; the latest full run passed in 0.16 seconds.
- No workflow repository/orchestrator, LLM provider, investigator loop, tools, runbook retrieval, mock ERP, FastAPI endpoint, UI, integration test, or deployment configuration exists yet.

## Approved Architecture

- One FastAPI application with a thin static browser UI.
- Editable scenario fixtures supply request text and explicit mock ERP behavior.
- In-memory append-only trace repository behind an interface.
- Live LLM as the primary extraction/investigation path; scripted provider supports exact fixtures only.
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
- Core canonical errors: `ORDER_STRUCTURE_INVALID`, `CUSTOMER_NUMBER_MISSING`, `PRODUCT_CODE_MISSING`, `QUANTITY_MISSING`, `QUANTITY_NON_POSITIVE`, `ERP_UNAVAILABLE`.

The deterministic workflow owns canonical errors. The investigator diagnoses and recommends but does not authorize or execute recovery.

## Next Implementation Task

After explicit approval, implement Phase 2 only: the in-memory trace repository, append-only event contracts, four editable fixture definitions, workflow orchestration, and stateful mock ERP with the intentionally noisy fail-once-503 trace. Do not begin the LLM, investigator, retrieval, API, or UI layers as part of that task.

## Phase 1 Implementation Notes

- Added `PRODUCT_CODE_MISSING` and `QUANTITY_MISSING` alongside the planned core codes so every required field has an explicit deterministic domain error.
- All three missing required-input errors return `REQUIRE_REVIEW` for correction or human-review recommendations and `BLOCK` for conflicting actions.
- `PolicyInput` permits absent diagnosed fields only so malformed or unavailable investigation output can be represented without invented values; policy returns `BLOCK` with `INVALID_INVESTIGATION`.
- Policy checks both diagnosed code and diagnosed category against the deterministic canonical mapping before considering an action.
- These are contract refinements, not changes to the approved responsibility or recovery boundaries.

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
- Default deterministic policy to `BLOCK` for invalid, conflicting, or unknown conditions.
- Preserve failed traces; corrected input creates a new run.
- Do not add multiple agents, React, database persistence, vector RAG, or general autonomous remediation.
- Update the retrospective only with real events.

## Unresolved Questions

None. Provider model name and API key are runtime environment settings, not architecture decisions.
