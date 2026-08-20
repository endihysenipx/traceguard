# TraceGuard Scope

## MVP Scope

| Included item | Why it is included |
|---|---|
| Four editable scenario presets | They provide reproducible demonstrations while allowing the request text to be inspected and changed. |
| Live LLM extraction | It proves that unstructured custom input is interpreted through a real probabilistic boundary. |
| Fixture-limited scripted provider | It makes deterministic tests and credential-free preset demos possible without pretending to support arbitrary extraction. |
| Explicit structural, domain, and business validation stages | They demonstrate where probabilistic interpretation ends and deterministic rules begin. |
| Mock ERP with success and fail-once-503 behavior | It creates a realistic external integration boundary without external infrastructure. |
| Append-only in-memory run and event storage behind an interface | It supports inspection and testing while keeping persistence deliberately small. |
| One bounded investigator with four read-only tools | It demonstrates genuine tool selection without unnecessary multi-agent coordination. |
| Tagged local runbook with lexical retrieval | It supplies operational knowledge with transparent, testable ranking. |
| Structured investigation report | It makes model output validateable and safe to consume. |
| Deterministic `ALLOW` / `BLOCK` / `REQUIRE_REVIEW` policy | It keeps execution authority outside the LLM. |
| One idempotent ERP retry | It proves controlled recovery rather than stopping at a recommendation. |
| Intentionally noisy ERP trace | It tests whether the investigator separates terminal evidence from warnings and recovered errors. |
| Thin static browser UI served by FastAPI | It makes the architecture easy to demonstrate without a separate frontend toolchain. |
| Deterministic tests plus one opt-in live smoke test | They balance repeatability with evidence that the real AI path works. |

## Provider Scope

- The real LLM is the primary AI path for extraction and investigation.
- The live provider receives the exact submitted request text and supports arbitrary custom input within the extraction schema.
- The scripted provider recognizes only the approved deterministic fixtures.
- If fixture text is edited while scripted mode is active, the application must reject the run with a clear message that custom input requires the live provider.
- The scripted provider must never silently ignore edits, infer arbitrary input, or be presented as live AI behavior.

## Explicitly Excluded Scope

| Excluded item | Reason for exclusion |
|---|---|
| React or another frontend framework | A second build system does not strengthen the core investigation and safety story. |
| Authentication, roles, and multi-user tenancy | Important in production, but unrelated to the assessment's central claim. |
| Full human-review workflow | `REQUIRE_REVIEW` is displayed as a terminal policy outcome; corrected input starts a new run. |
| Real ERP, email, OCR, and webhooks | Mock boundaries are sufficient to demonstrate failure classification and safe retry. |
| Database, migrations, queues, and workers | In-memory state is adequate for a single-process assessment demo. |
| JSON-file persistence | Correct locking, atomic updates, and corruption recovery would add incidental complexity. |
| Microservices and multiple agents | They would increase orchestration cost without adding meaningful capability. |
| Embeddings, vector database, or hosted RAG | The small controlled runbook is better served by exact-tag and lexical matching. |
| Arbitrary tools, network access, shell access, or write tools for the investigator | They would expand the attack surface and are not needed for diagnosis. |
| General autonomous remediation | Only a single bounded ERP retry is authorized by deterministic code. |
| Resuming or mutating a failed run with corrected input | Creating a new run preserves audit history and avoids ambiguous state. |
| Custom workflow design, streaming responses, or token dashboards | These do not prove the core architecture within the time constraint. |
| Production deployment, observability stack, and cloud infrastructure | Local reproducibility is the appropriate assessment target. |
| Broad runbook corpus and formal model evaluation platform | A small test set is sufficient for the MVP; broader evaluation is a future improvement. |

## Scope Guard

An item should be added only if it directly improves one of four claims: trace inspectability, meaningful AI reasoning, deterministic safety, or reviewer-facing demonstrability. Infrastructure sophistication alone is not a reason to expand scope.
