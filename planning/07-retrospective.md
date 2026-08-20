# Live Retrospective

## Where the Coding Agent Helped

- During planning-artifact consistency verification, the coding agent identified three residual references to the retired approval terminology and corrected them to `REQUIRE_REVIEW` before implementation began.
- The coding agent implemented the deterministic domain core with separated validation boundaries, exhaustive state-transition checks, and recovery-policy branch coverage. After an initial 52-test pass, it tightened the invalid-investigation contract and completed the phase with 53 passing unit tests.
- The coding agent implemented the Phase 2 trace repository, editable fixtures, workflow orchestrator, and stateful noisy mock ERP without adding later-phase components. The full 77-test suite passed on the first Phase 2 run.
- The coding agent implemented the exact-fixture and live OpenAI extraction providers, preserved the deterministic validation boundary, and completed Phase 3 with 96 passing network-free tests.
- The coding agent implemented the tagged runbook, four scoped diagnostic tools, additive tool history, scripted and live bounded investigator paths, and causal evidence enforcement. Phase 4 completed with 132 passing network-free tests.
- The coding agent implemented deterministic recovery authorization, observable policy/execution histories, a repository-enforced idempotency claim, and the single bounded ERP retry. Phase 5 completed with 146 passing network-free tests while preserving the original failed workflow evidence.
- The coding agent assembled the single-process FastAPI application, closed API authority boundaries, aggregate inspection responses, and one framework-free browser page. Phase 6 reached 168 passing network-free tests and all four scripted scenarios passed through the running local HTTP service.
- During Phase 7, the coding agent compared documentation to implemented behavior and corrected three stale architecture statements: recovery records are separate from workflow events, every missing required field has a specific canonical error, and malformed investigator output fails safely without an automatic model retry. It also produced the reproducible assessor-facing README and completed the tracked-file hygiene review.

## Where the Coding Agent Failed or Made Poor Assumptions

- Adding explicit `PRODUCT_CODE_MISSING` and `QUANTITY_MISSING` canonical errors was useful, but the coding agent initially left their recovery-policy consequences inconsistent with `CUSTOMER_NUMBER_MISSING`.
- The mock ERP initially generated the optional-field warning solely from simulation mode and ignored the actual validated order, which could create false trace evidence for edited or custom inputs.
- The coding agent initially made all Pydantic tool-argument models globally strict, which rejected valid JSON string representations of UUIDs and enum values. Focused tests exposed the mismatch, and the schemas were corrected while retaining extra-field rejection and explicit enum/limit validation.
- A Phase 4 test initially used pytest's reserved `request` fixture name as a parametrized argument, causing collection to fail until the argument was renamed.
- The Phase 5 recovery coordinator initially performed its final current-state authorization check before the policy backoff, leaving a window where the ERP attempt count could change before the actual side effect.
- The first Phase 6 route-inspection helper assumed every FastAPI route object had HTTP methods; the mounted static-files route did not, so that diagnostic command raised `AttributeError`. Application import was valid and the full test suite remained unaffected.
- Scripted and fake-client investigation tests passed, but the genuine LIVE investigator smoke failed with `MODEL_TURN_LIMIT`. The live adapter had set `parallel_tool_calls=False`, which was incompatible with gathering the required independent evidence within the approved three-turn strategy.

## Human Corrections and Overrides

- Human review identified the semantic inconsistency and required all missing required-input failures to use the same `REQUIRE_REVIEW` behavior for correction or human-review recommendations.
- Human review required diagnostic events to remain grounded in actual run data because the investigator will later use those events as evidence.
- Human review identified the stale-authorization window and required a second current-state/policy guard after backoff immediately before ERP submission, with `ALLOW` transitioning safely to `BLOCK` if authorization became stale.
- Human review connected the genuine LIVE turn-limit failure to disabled parallel function calls and required efficient bounded multi-call turns without changing the three-turn or six-call host limits.
- Human review aligned the investigator's independent default with the successfully verified `gpt-5.4-mini` path while retaining `gpt-5.4-nano` as the separate extraction default.

## Debugging Episodes

- The normal workspace patch helper could not launch because the Windows sandbox setup executable was missing. The agent verified the failure, used the Codex patch engine outside the broken sandbox with explicit approval, and kept all changes within the approved domain-core and planning files.
- Generated Python cache artifacts were accidentally tracked. They were removed from Git tracking and covered by a root `.gitignore`.
- An optional Ruff check was attempted after the Phase 2 tests, but Ruff was not installed. The agent did not add an unplanned dependency and retained the passing full test suite as the required verification.
- The first Phase 3 test run exposed a circular import because `ProviderMode` was initially placed in the workflow package while the workflow orchestrator imported the extraction protocol. The agent moved the cross-cutting enum to the dependency-neutral domain enum module and the complete suite then passed.
- A combined Phase 4 patch exceeded the Windows command-length limit before applying changes. The agent split it into smaller atomic patches and continued without partial repository edits.
- The Phase 5 patch workaround initially used Base64 helpers unavailable in the tool runtime (`btoa`, then `TextEncoder`). Both orchestration calls failed before changing files; the agent switched to the established character-based encoder and continued successfully.
- The local Phase 6 server started successfully, but the in-app browser runtime could not initialize because its module import was blocked. The agent used the approved fallback of live localhost page/API requests and reported the visual-verification limitation rather than claiming browser interaction.
- The LIVE investigator adapter was corrected to request parallel tool calls and guide efficient evidence batching. Fake-client tests verify two-call turns, replay of multiple results, completion within three model turns, and rejection of more than six requested calls before execution. Real post-fix testing first rejected one report as `REPORT_NOT_GROUNDED`, then completed successfully with `gpt-5.4-mini`, four real read-only calls, and the intended 2 + 2 + report flow.

## Scope Changes

- The Phase 5 planning phrase controlled ERP retry endpoint was corrected to controlled ERP retry domain path so FastAPI assembly remains in Phase 6, consistent with the approved phase boundary.

## Current Weaknesses

- Genuine external testing verified both LIVE extraction and the corrected LIVE investigator. Model variability remains: one real investigation failed grounding and a later run completed, so individual invocations are never assumed to succeed and continue to fail closed.
- Recovery idempotency and records are intentionally process-local. A `STARTED` claim fails safe after interruption, but durable crash reconciliation and distributed locking remain outside this in-memory assessment scope.
- Phase 6's page and complete scripted flow were verified through the running local HTTP service, but visual and interactive browser QA remains outstanding because the available browser runtime could not connect.

## Future Improvements
