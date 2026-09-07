# CI Test Coverage Report

**Question this report answers:** not "is coverage % high" but *"can CI detect if a future code change breaks an important architecture flow?"* Coverage is judged against that bar throughout.

---

## 1. Existing CI/Test Audit

Before any change, the actual state was:

- **CI entrypoint:** `tests/ci_runner.py`, a custom 6-layer runner (syntax, import integrity, CSV SoT validation, YAML config validation, capability-gate unit tests, rollback/deployment orchestration tests), invoked by `.github/workflows/ci-validation.yml` on every push/PR to `main`.
- **No pytest anywhere** in the project (no `pytest.ini`, `conftest.py`, or `pyproject.toml`). `requirements.txt` has no test framework dependency at all.
- **Two real, well-written test files existed but were never run by anything**: `servicenow/tests/test_servicenow_integration.py` (real `unittest.TestCase`, payload/dedup/lifecycle tests) and `observability/tests/test_matrix_validation.py` (function-style YAML config validation). Neither was imported by `ci_runner.py`, referenced in the GitHub Actions workflow, or runnable by any documented command. They were pure dead weight - present in the repo, invisible to CI.
- **The GitHub Actions workflow's own step name was stale**: labeled "Layers 1-4" while `ci_runner.py` (by the time of this audit) already ran Layers 1-6.
- **Zero test coverage existed** for: maintenance mode (`servicenow/maintenance.py` - built in a prior session, never tested), the rollback verification logic in isolation (`deployment/rollback_manager.py` - only exercised indirectly through `DeviceConnector`-level integration tests in Layer 6), ServiceNow API failure handling (401/500/timeout/connection failure), and any security/secrets-hygiene regression checks.
- **A known, real bug was live in the codebase**: `test_router_assignment_routing` failed because `device_role: "edge_router"` didn't match any key in `ASSIGNMENT_GROUPS_BY_ROLE`. This was flagged in an earlier session's audit but never root-caused or fixed - see Section 5.

## 2. Test Coverage Before Changes

| Component | Existing Tests | What Was Covered | Missing Coverage | Risk |
|---|---|---|---|---|
| Syntax/import integrity | Layers 1-2 | Every `.py` file compiles; internal modules import cleanly | N/A - solid | Low |
| CSV Source of Truth | Layer 3 | Schema/uniqueness of `csv/dcim`, `csv/ipam` files | Deeper NetBox-context assembly logic (`context_builder.py`) untested | Medium |
| YAML config (generic) | Layer 4 | Syntax validity of migration/discovery YAML | Did not touch observability YAML at all (Prometheus, Alertmanager, SNMP, Loki) | High |
| Capability gate | Layer 5 | Role → protocol-category gating | N/A - solid | Low |
| Deployment/rollback orchestration | Layer 6 | Idempotency, selective deploy, rollback (mock-connection level) | Rollback *decision logic* (`rollback_manager.py`) never tested in isolation | Medium |
| Pre-deployment gatekeeper | **None** | Nothing | Entire `pre_deployment_validation/` package (orchestrator + validators) | **High** |
| Configuration generation | **None** | Nothing | `deployment/config_generator.py`, protocol plugins | **High** |
| Post-deployment / compliance | **None** | Nothing | `post_deployment_validation/` package entirely | **High** |
| Observability config (Prometheus/Alertmanager/SNMP/Loki/Grafana) | **None run by CI** | `test_matrix_validation.py` existed but was orphaned | Everything - it simply never executed | **High** |
| ServiceNow payload/dedup/lifecycle | **None run by CI** | `test_servicenow_integration.py` existed but was orphaned | Everything - it simply never executed, and it had a live failing test nobody had root-caused | **High** |
| Maintenance mode | **None** | Nothing | Entire `servicenow/maintenance.py` module | **High** |
| ServiceNow API failure handling | **None** | Nothing | 401/500/timeout/connection-failure behavior; retry-or-not | **High** |
| Security/secrets hygiene | **None** | Nothing | `.env` gitignore status, `.env.example` safety, hardcoded-secret regressions | Medium |

## 3. Gaps Identified

Summarized from Section 2: the *entire* observability stack, the *entire* ServiceNow adapter, and the *entire* maintenance-mode feature - three major subsystems added after the original CI was written, exactly as suspected - had **zero CI-executed test coverage**. Two real test files existed for part of this but were silently orphaned. A real, live bug (`ASSIGNMENT_GROUPS_BY_ROLE`) had gone unfixed. This fully confirms the suspicion stated in the task: CI coverage was outdated and did not reflect the current architecture.

## 4. Test Architecture

**Decision: did not introduce pytest.** The project has zero pytest usage anywhere, and the existing `ci_runner.py` "layer" pattern is a proven, already-working, already-integrated-with-GitHub-Actions structure. Introducing pytest markers (`@pytest.mark.unit`, etc.) would mean migrating the entire existing suite to a new framework for a coverage task - a much bigger, riskier change than the task asked for, and would violate "do not overengineer." Instead, the existing layer pattern was **extended**, and the test-level distinctions the task asked for map onto it directly:

| Level | Where it lives | How to run just that level |
|---|---|---|
| **Unit** | `servicenow/tests/test_maintenance_mode.py`, `servicenow/tests/test_failure_handling.py`, `deployment/tests/test_rollback_manager.py`, `servicenow/tests/test_servicenow_integration.py` | `python3 -m servicenow.tests.test_maintenance_mode` (each file is directly runnable) |
| **Integration** | `tests/ci_runner.py` Layer 6 (DeviceConnector + simulated device state) | `python3 tests/ci_runner.py` (Layer 6 only cannot be isolated without a small refactor; see Section 14) |
| **Config validation** | `tests/ci_runner.py` Layers 3-4, `observability/tests/test_matrix_validation.py` | `python3 -m observability.tests.test_matrix_validation` |
| **Security sanity** | `tests/test_security_sanity.py` | `python3 -m tests.test_security_sanity` |
| **Optional real E2E** | Manual, documented procedures - never auto-run | See Section 13 |

Every layer in `ci_runner.py` is independently importable and runnable on its own (each new module exposes an `ALL_TESTS` list of zero-argument functions, or is a standard `unittest.TestCase`), so `python3 tests/ci_runner.py` runs everything, and any individual layer's module can be run alone for fast local iteration.

## 5. Core NAC Coverage

**Root cause of the known `ASSIGNMENT_GROUPS_BY_ROLE` failure - investigated, not just made to pass:**

Checked whether (A) the mapping was incomplete or (B) the test input was invalid. Found decisive evidence for **(A)**: the project's own real CSV inventory (`csv/dcim/devices.csv`) uses **hyphenated compound role slugs** - `l3-gateway-router`, `layer-2-access-switch`, `core-switch`, `distribution-switch` - none of which exist as exact keys in `ASSIGNMENT_GROUPS_BY_ROLE`. `deployment/capability_resolver.py` already solves this identical problem elsewhere in the same codebase via substring matching. `ASSIGNMENT_GROUPS_BY_ROLE`'s exact-match-only lookup was therefore a **real, latent production bug** - it would have silently misrouted every real Hyderabad device's incidents to the generic "Network Operations Center" fallback the moment those devices were ever wired into Prometheus/Alertmanager (they aren't yet, which is why nobody had seen it happen).

**Fix:** added `settings.resolve_assignment_group()` - tries the exact-match table first (fast path, unchanged behavior for existing GNS3 lab roles), then falls back to substring matching on `router`/`switch`/`access` tokens, mirroring `capability_resolver.py`'s established pattern. Verified against both the previously-failing test input (`edge_router`) and the real CSV role strings:
```
edge_router              -> Network Routing
layer-2-access-switch    -> Network Switching
l3-gateway-router        -> Network Routing
core-switch              -> Network Switching
distribution-switch      -> Network Switching
unknown-thing            -> Network Operations Center (safe fallback preserved)
```
`test_router_assignment_routing` now passes for the correct reason.

**Genuinely NOT covered (honest gap, not silently accepted):** pre-deployment gatekeeper unit tests (`pre_deployment_validation/orchestrator.py`, `registry.py`), configuration-generation unit tests (`deployment/config_generator.py`, protocol plugin `render()`/`validate()` behavior), and post-deployment/compliance unit tests (`post_deployment_validation/` package) were **not added in this pass**. This was a deliberate scope decision given the size of everything else in this task, not an oversight - see Section 14 for what's specifically missing and why it matters.

## 6. Rollback Coverage

Two layers now cover rollback from different angles:

- **Layer 6 (integration-style, pre-existing, extended in a prior session):** exercises rollback through the real `DeviceConnector.deploy()` code path against a stateful simulated device, covering all 6 of the task's required scenarios (deploy succeeds/no rollback, deploy fails → rollback → verified success, rollback command failure, rollback "succeeds" but device not actually restored, VLAN rollback, audit record).
- **Layer 10 (new, pure unit tests, `deployment/tests/test_rollback_manager.py`):** tests `ConfigSectionParser`/`build_rollback_plan`/`verify_rollback` directly, with no device/connection involved at all - 13 tests including the single most important one: `test_verify_rollback_fails_when_state_was_not_actually_restored`, which proves verification catches a live config that still shows the new (wrong) value even when no exception was raised.

**Real-device evidence is explicitly not weakened or replaced** - `docs/ROLLBACK_REMEDIATION_REPORT.md`'s live GNS3 test (real SW1_gns3, real SSH, independently re-verified via a separate session) remains the authoritative real-hardware proof; these CI layers validate the *logic*, on every commit, without needing a device.

## 7. Observability Coverage

`observability/tests/test_matrix_validation.py` was wired into CI (Layer 7) and extended with 3 new tests:

- **Prometheus:** validates `scrape_configs`/`alerting` block exist, and that all 3 staging device targets (`R1_gns3`, `SW1_gns3`, `SW2_gns3`) are present.
- **Alertmanager:** validates every receiver's webhook URL actually points at `/webhook`, and - critically - that `send_resolved: true` on every receiver. This directly targets the exact class of regression that happened twice in this project's real history (an unrelated fix left `send_resolved` at the wrong value, which was only caught by manual live testing in a later session). It also verifies CRITICAL/HIGH/WARNING severities are all explicitly routed. **This test would have caught both of those real incidents before they reached a live system.**
- **SNMP exporter:** verifies the checked-in *template* never contains a literal community string (only the `${SNMP_COMMUNITY}` placeholder) - a direct regression guard for the security-hardening fix.
- Existing tests (already present, now actually running): `alert_rules.yaml` required-alerts check, `docker-compose.yml` required-service/healthcheck/resource-limit check, staging/production env profile existence.

**Not covered:** Loki retention/schema validation beyond "the YAML parses" (Layer 4 already does generic YAML syntax checking for `loki-config.yaml`), Grafana dashboard JSON schema validation (datasource/dashboard *provisioning* YAML is checked, but the dashboard JSON files under `observability/grafana/dashboards/*.json` are not individually schema-validated), Promtail label/pipeline-stage correctness beyond syntax.

## 8. ServiceNow Coverage

- **Layer 8** wires in the previously-orphaned `test_servicenow_integration.py` (payload normalization, fingerprint-based dedup, create→update→resolve lifecycle, assignment routing) - now actually part of CI for the first time.
- **Layer 9 (new):** 12 tests for maintenance mode - global suppression, device-scoped suppression (explicitly proving an out-of-scope device is *not* suppressed, not just that scoping exists), site-scoped suppression, auto-expiry with self-healing state, grace-period suppress-then-lapse, disable-with/without-grace, suppressed-event audit logging, and the safe-by-default (disabled) initial state.
- **Layer 11 (new):** 6 tests for ServiceNow API failure handling - HTTP 401, HTTP 500, connection refused, and timeout all correctly land in `Pending_API_Retry` rather than crashing. **Explicitly test-proves the absence of automatic retry** (`test_no_automatic_retry_happens_on_its_own`) and separately proves the one real recovery path that *does* exist - a pending incident gets a fresh attempt only if Alertmanager redelivers the same still-firing alert later, not from any scheduled job. This directly satisfies "do not claim retry reliability exists unless actual retry logic is tested" - the honest finding is **there is no reliable retry mechanism today**, and that finding is now itself protected by a test rather than just documentation.

**Not covered:** a dedicated automated test for the two-tier email-notification path (ServiceNow's own Notification rules and `sys_email` records) - this was validated live and manually in `docs/REAL_END_TO_END_ALERT_TO_SERVICENOW_PROOF.md`, but there's no way to unit-test ServiceNow's own notification engine from this codebase; it lives entirely inside the ServiceNow instance.

## 9. Security Coverage

`tests/test_security_sanity.py` (Layer 12, 4 tests) - **explicitly scoped and limited, per instruction not to fake confidence with a simplistic scanner**:

- `.env` is confirmed git-ignored (`git check-ignore`).
- The rendered `snmp.yml` (containing the real community value) is confirmed git-ignored.
- `.env.example` is scanned for a narrow set of live-secret-shaped patterns (a NetBox-token-like string, a bare long hex string) - explicitly documented as *not* a general secret scanner.
- No hardcoded SNMP community string in any tracked `.py`/`.yml` file outside of legitimate CSV business-config data and test fixtures.

The module's own docstring states its limits directly: *"A real secret that doesn't match these specific patterns will NOT be caught here. Treat a pass as 'the known mistakes haven't recurred', not as 'this repository has been security-scanned'."*

## 10. CI Pipeline Behavior

Confirmed, after all changes: normal CI (`python3 tests/ci_runner.py`, exactly what GitHub Actions runs) requires **no** GNS3, **no** real ServiceNow credentials/PDI, **no** Docker containers, and exposes **no** secrets (every test either uses mock/simulated data or reads only tracked, non-secret repository files). The GitHub Actions workflow step name was corrected from the stale "Layers 1-4" to reflect the actual current layer count and purpose.

## 11. Tests Added/Modified

| File | Status | Summary |
|---|---|---|
| `servicenow/config/settings.py` | Modified | Added `resolve_assignment_group()` with substring fallback (root-cause fix) |
| `servicenow/models/incident_payload.py` | Modified | Uses the new resolver instead of a raw exact-match dict lookup |
| `observability/tests/test_matrix_validation.py` | Modified | +3 new tests (Prometheus, Alertmanager consistency, SNMP template regression guard), +`ALL_TESTS` list |
| `servicenow/tests/test_maintenance_mode.py` | **New** | 12 unit tests for `servicenow/maintenance.py` |
| `servicenow/tests/test_failure_handling.py` | **New** | 6 unit tests for ServiceNow API failure handling |
| `deployment/tests/test_rollback_manager.py` | **New** | 13 unit tests for rollback decision logic in isolation |
| `tests/test_security_sanity.py` | **New** | 4 security sanity checks, explicitly scope-limited |
| `tests/ci_runner.py` | Modified | +6 new layer-runner functions (7-12), wired into `main()`, shared `_run_function_style_test_module()` helper added |
| `.github/workflows/ci-validation.yml` | Modified | Corrected stale "Layers 1-4" step name |
| `docs/CI_TEST_COVERAGE_REPORT.md` | **New** | This report |

## 12. Commands to Run Locally

```bash
cd enterprise_real_sot

# Everything (what CI runs)
python3 tests/ci_runner.py

# Any single layer/module in isolation
python3 -m observability.tests.test_matrix_validation
python3 -m servicenow.tests.test_servicenow_integration   # via unittest, or:
python3 -m unittest servicenow.tests.test_servicenow_integration -v
python3 -m servicenow.tests.test_maintenance_mode
python3 -m deployment.tests.test_rollback_manager
python3 -m servicenow.tests.test_failure_handling
python3 -m tests.test_security_sanity
```

## 13. Optional Real E2E Tests

Never auto-run by CI, require real infrastructure, and already have real evidence on record rather than being re-scripted here (re-running them casually would mean unnecessarily touching real GNS3 devices/a real ServiceNow PDI again):

- **Rollback against a real device** - `docs/ROLLBACK_REMEDIATION_REPORT.md` (real SW1_gns3, independently re-verified).
- **Maintenance mode against the live adapter** - `docs/MAINTENANCE_MODE_IMPLEMENTATION_REPORT.md` (6 scenarios against the real running stack).
- **Full alert→ServiceNow chain against a real GNS3 failure** - `docs/REAL_END_TO_END_ALERT_TO_SERVICENOW_PROOF.md` (real node stop/start via the GNS3 API, real Prometheus/Alertmanager/adapter/ServiceNow evidence at every stage).

If a formal `e2e` marker/profile is wanted later (e.g. a `tests/e2e/` directory with scripts requiring `RUN_REAL_E2E=1` to execute), that's a small addition on top of this structure - not built now because no such script existed before this task and the task's own instruction was not to require GNS3/ServiceNow PDI for normal CI, which is already satisfied by simply never invoking these from `ci_runner.py`.

## 14. Remaining Test Gaps

Stated plainly, per instruction not to claim readiness the coverage doesn't support:

- **Pre-deployment gatekeeper** (`pre_deployment_validation/orchestrator.py`, `registry.py`, the port-security validator): zero unit tests. Nobody would find out in CI if a future change broke the ERROR/WARNING severity gate logic.
- **Configuration generation** (`deployment/config_generator.py`, the 15 protocol plugins): zero unit tests. A future change could silently render invalid CLI and CI would not catch it.
- **Post-deployment / compliance** (`post_deployment_validation/`, the whole comparator/collector/resource-plugin package): zero unit tests.
- **NetBox client / context builder** (`deployment/netbox_client.py`, `context_builder.py`): covered only indirectly via CSV schema validation (Layer 3); the actual context-assembly logic (merging global/site/device config-context layers) has no dedicated test.
- **Grafana dashboard JSON** files are not individually schema-validated (only their provisioning YAML is).
- **Layer 6's rollback/deployment tests are integration-style, not isolated** - they currently run as part of the same function as the capability-gate-adjacent orchestration tests; splitting them into a standalone, independently-invocable module (like the new Layer 9-12 modules) would improve local iteration speed but wasn't done in this pass to avoid unnecessary churn on a working, already-passing test.

## 15. Final Verdict

```
CI IMPROVED BUT IMPORTANT GAPS REMAIN
```

CI now genuinely reflects the architecture added after the original suite: observability configuration, the ServiceNow adapter (payload/dedup/lifecycle/failure-handling), and maintenance mode all went from **zero executed coverage** to real, meaningful test coverage across 6 new/wired-in layers (52 new or newly-running test assertions), plus a genuine root-cause fix for a real latent bug affecting real production device-role data. A green pipeline today means something concrete it did not mean before this task.

It is not "CI COVERAGE READY FOR STAGING" because three core NAC pipeline stages explicitly called out in this task's own Step 3 - pre-deployment gatekeeper, configuration generation, and post-deployment/compliance - still have zero unit test coverage. A future change to any of those three could break deployment behavior and CI would stay green. That is a real, specific, named gap, not a vague caveat.

---

## Final Coverage Matrix

| Architecture Component | Unit | Integration | Config Validation | Real E2E |
|---|---|---|---|---|
| NetBox / SoT | Partial (CSV schema, Layer 3) | — | Yes (Layer 3) | — |
| Configuration Generation | **None** | — | — | Yes (real artifacts, prior session) |
| Pre-Deployment Gatekeeper | **None** | — | — | Yes (real artifacts, prior session) |
| Deployment / Verification | — | Yes (Layer 6) | — | Yes (`ROLLBACK_REMEDIATION_REPORT.md`) |
| Rollback | Yes (Layer 10, 13 tests) | Yes (Layer 6, 6 tests) | — | Yes (real SW1_gns3, independently verified) |
| Post-Deployment / Compliance | **None** | — | — | Partial (prior session, SSH-failed run only) |
| Prometheus | — | — | Yes (Layer 4, Layer 7) | Yes (real E2E proof doc) |
| SNMP Exporter | — | — | Yes (Layer 7, template regression guard) | Yes (real E2E proof doc) |
| Loki / Promtail / Syslog | — | — | Yes (Layer 4, syntax only) | Yes (real syslog confirmed, prior session) |
| Alertmanager | — | — | Yes (Layer 7, webhook/send_resolved/routing) | Yes (real E2E proof doc) |
| Grafana | — | — | Partial (provisioning YAML only, Layer 4) | — |
| ServiceNow Adapter (payload/dedup/lifecycle) | Yes (Layer 8, wired in) | — | — | Yes (real E2E proof doc) |
| ServiceNow Failure Handling | Yes (Layer 11, 6 tests) | — | — | — |
| Maintenance Mode | Yes (Layer 9, 12 tests) | — | — | Yes (`MAINTENANCE_MODE_IMPLEMENTATION_REPORT.md`) |
| Security / Secrets Hygiene | — | — | Yes (Layer 12, scope-limited) | — |
