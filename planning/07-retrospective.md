# Live Retrospective

## Where the Coding Agent Helped

- During planning-artifact consistency verification, the coding agent identified three residual references to the retired approval terminology and corrected them to `REQUIRE_REVIEW` before implementation began.
- The coding agent implemented the deterministic domain core with separated validation boundaries, exhaustive state-transition checks, and recovery-policy branch coverage. After an initial 52-test pass, it tightened the invalid-investigation contract and completed the phase with 53 passing unit tests.
- The coding agent implemented the Phase 2 trace repository, editable fixtures, workflow orchestrator, and stateful noisy mock ERP without adding later-phase components. The full 77-test suite passed on the first Phase 2 run.
- The coding agent implemented the exact-fixture and live OpenAI extraction providers, preserved the deterministic validation boundary, and completed Phase 3 with 96 passing network-free tests.

## Where the Coding Agent Failed or Made Poor Assumptions

- Adding explicit `PRODUCT_CODE_MISSING` and `QUANTITY_MISSING` canonical errors was useful, but the coding agent initially left their recovery-policy consequences inconsistent with `CUSTOMER_NUMBER_MISSING`.
- The mock ERP initially generated the optional-field warning solely from simulation mode and ignored the actual validated order, which could create false trace evidence for edited or custom inputs.

## Human Corrections and Overrides

- Human review identified the semantic inconsistency and required all missing required-input failures to use the same `REQUIRE_REVIEW` behavior for correction or human-review recommendations.
- Human review required diagnostic events to remain grounded in actual run data because the investigator will later use those events as evidence.

## Debugging Episodes

- The normal workspace patch helper could not launch because the Windows sandbox setup executable was missing. The agent verified the failure, used the Codex patch engine outside the broken sandbox with explicit approval, and kept all changes within the approved domain-core and planning files.
- Generated Python cache artifacts were accidentally tracked. They were removed from Git tracking and covered by a root `.gitignore`.
- An optional Ruff check was attempted after the Phase 2 tests, but Ruff was not installed. The agent did not add an unplanned dependency and retained the passing full test suite as the required verification.
- The first Phase 3 test run exposed a circular import because `ProviderMode` was initially placed in the workflow package while the workflow orchestrator imported the extraction protocol. The agent moved the cross-cutting enum to the dependency-neutral domain enum module and the complete suite then passed.

## Scope Changes

## Current Weaknesses

- No `OPENAI_API_KEY` was available during Phase 3, so the opt-in smoke entry point skipped cleanly and the real external extraction path has not yet been exercised locally.

## Future Improvements
