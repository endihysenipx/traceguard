# TraceGuard Requirements

## Problem

AI-powered business workflows can fail during probabilistic extraction, deterministic validation, or external integration. Engineers then have to correlate traces, stage outputs, and operational guidance before deciding whether a retry is useful or safe. TraceGuard demonstrates a small, inspectable workflow in which a tool-using AI investigator diagnoses a failed run, while deterministic code retains ownership of canonical errors and recovery authority.

## Target User

The primary user is an engineer or workflow operator investigating a failed AI-assisted order workflow. The assessment reviewer is a secondary user who must be able to understand the architecture, reproduce the four scenarios, inspect the agent's evidence gathering, and see the safety boundary clearly.

## Functional Requirements

### Order input and scenarios

- Provide four convenience presets: successful order, missing customer number, invalid quantity, and ERP unavailable.
- A preset must populate an editable unstructured order-request textarea and an explicit mock ERP behavior.
- Presets are input fixtures and trace metadata, not hidden workflow logic.
- The submitted textarea content must be passed unchanged to the configured extraction provider.
- Arbitrary edited or custom input requires the live LLM provider.
- The scripted provider must support only recognized deterministic fixtures and must reject unsupported custom input clearly.

### Workflow and validation

- Execute these stages in order: LLM extraction, structural/type validation, deterministic domain validation, deterministic business-rule validation, and mock ERP submission.
- Parse the model result into `ExtractedOrderCandidate`. Business fields may be optional or missing at this boundary.
- Use Pydantic only to validate response structure and field types at the structural/type boundary.
- Use deterministic domain validation to check required fields and produce canonical errors such as `CUSTOMER_NUMBER_MISSING`.
- Use deterministic business-rule validation to evaluate present, typed values and produce canonical errors such as `QUANTITY_NON_POSITIVE`.
- Record every accepted state transition and relevant stage result as an ordered trace event.
- The deterministic workflow owns the canonical failure category and error code. The investigator cannot replace them.

### Scenarios

- A successful order must complete extraction, all validation stages, and the mock ERP call without investigation.
- Missing customer data must pass structural/type validation, fail deterministic domain validation, and lead to `REQUIRE_REVIEW` when the investigator recommends correction or human review.
- A negative quantity must pass structural/type and domain validation, fail deterministic business-rule validation, and lead to `BLOCK`.
- ERP unavailability must produce a terminal HTTP 503 event and may lead to `ALLOW` for one bounded retry when all deterministic conditions are satisfied.
- The ERP-unavailable trace must also contain non-causal noise, including a harmless optional-field warning and a recovered cache failure/fallback, before the terminal ERP failure.
- Non-causal events must carry outcome metadata that distinguishes `CONTINUED` or `RECOVERED` events from `TERMINAL` evidence.

### Investigation

- Permit investigation only for failed workflow runs.
- Start the investigator primarily with the `run_id`; do not place the full trace or canonical error in its initial context.
- Allow the investigator to select from exactly four read-only tools: `get_run_overview`, `get_run_events`, `get_stage_artifact`, and `search_runbook`.
- Bound an investigation to at most three model turns and six total tool calls.
- Record tool calls and results in a form visible to the user, with sensitive or excessive content removed.
- Require a schema-valid `InvestigationReport` with root cause, cited evidence, recommendation, confidence, uncertainties, and runbook references.
- Require at least one evidence item to cite the terminal failure. Recovered or continued events may be cited only as non-causal context.
- Treat malformed output, exhausted budgets, unknown tools, invalid arguments, timeouts, and cross-run access attempts as safe investigation failures.

### Recovery

- Evaluate every recommendation through deterministic recovery policy.
- Return only `ALLOW`, `BLOCK`, or `REQUIRE_REVIEW`.
- Never let the investigator execute a recovery action or choose authoritative retry limits.
- Allow only `RETRY_SAME_INPUT` for canonical `ERP_UNAVAILABLE` when the report is valid, the run has an idempotency key, and the attempt limit has not been reached.
- Limit ERP execution to two total attempts, with a one-second backoff before the retry.
- Re-evaluate policy immediately before retry execution.
- Return the stored retry result for a repeated idempotency key rather than calling the mock ERP again.
- A corrected request creates a new run; the failed run and its trace remain immutable.

### User interface

- Serve one thin browser interface from FastAPI.
- Show the editable request, active provider, selected mock ERP behavior, workflow trace, stage artifacts, investigator tool history, structured report, policy decision, and retry result.
- Show a retry control only when deterministic policy returns `ALLOW`.
- Label `REQUIRE_REVIEW` as human review or correction, not authorization to execute an action.

## Non-Functional Requirements

- Keep the system runnable as one local Python process with a small dependency set.
- Keep AI, deterministic workflow, policy, and adapter boundaries understandable from the code structure.
- Default to blocking when evidence, output, state, or policy input is invalid or unknown.
- Keep deterministic tests independent of network access and model variability.
- Make scripted and live provider modes visually and operationally distinguishable.
- Sanitize stored provider errors, tool outputs, and external-call details; never expose secrets.
- Enforce valid state transitions, bounded payload sizes, tool allowlists, timeouts, and agent budgets.
- Preserve previous trace events rather than rewriting history during investigation or recovery.
- Favor explicit enums and Pydantic contracts over unstructured dictionaries at system boundaries.

## Success Criteria

- All four presets can be demonstrated from one browser page.
- The textarea remains editable, and arbitrary custom input is genuinely extracted by the live provider.
- Each scenario reaches the expected validation stage and canonical deterministic error.
- Failed runs are investigated through observable tool calls rather than a full-context prompt.
- The noisy ERP scenario is diagnosed as `ERP_UNAVAILABLE`, with terminal ERP evidence cited and recovered warnings not treated as causal.
- Policy returns `REQUIRE_REVIEW` for any missing required input when correction or human review is recommended, `BLOCK` for invalid quantity, and `ALLOW` for an eligible ERP retry.
- The allowed retry succeeds once, and duplicate retry requests do not duplicate the ERP side effect.
- Malformed investigator output and adversarial trace content fail safely.
- The default automated suite passes without an API key; an opt-in live smoke test covers real extraction and tool use.

## Assessment Constraints

- Target a focused two-to-three-hour assessment build, not production completeness.
- Preserve plans, handoffs, decisions, and the live retrospective under `planning/`.
- Prefer one investigator and one service over architecture added for appearance.
- Do not add authentication, real ERP integration, production persistence, distributed infrastructure, or vector retrieval.
- Update the retrospective only with events that actually occur during implementation.
