# Security Hardening Report — .env, Secrets, Credentials, RBAC

**Scope:** `.env`/secrets architecture, hardcoded credentials, SNMP community handling, ServiceNow credential security, RBAC/least-privilege model, Docker security, Git secret exposure.
**Method:** Full audit first (grep across the whole repo for credential-shaped patterns, manual inspection of every hit), fixes implemented only for what the audit found, then live regression testing against the running stack. No real credential value is printed anywhere in this report or in terminal output produced for it.

---

## 1. Security Findings Before Fix

| Finding | File | Risk | Severity | Recommended Fix |
|---|---|---|---|---|
| SNMP v2c community string hardcoded directly in a checked-in config file | `observability/snmp_exporter/snmp.yml:7` | Anyone with repo/file read access sees the live monitoring credential; can't rotate without editing tracked config | Medium | Move to `.env`, template the file at render time |
| ServiceNow `caller_id` sys_id hardcoded in application code | `servicenow/models/incident_payload.py:104` | Ties every incident to one fixed identity; can't point at a dedicated service account without a code change | Low-Medium | Source from `settings`/env var |
| Grafana admin username/password hardcoded in Docker Compose | `observability/docker-compose.yml` (`environment:` block, `grafana` service) | Default admin/admin baked into version-controllable infrastructure config | Medium | Source via `env_file` from `.env` |
| `.env` file world-readable (`644`) | `enterprise_real_sot/.env` | Any local user on the host (not just the owner) could read live NetBox/SSH/ServiceNow secrets | Medium (local, staging) | `chmod 600` |
| `.env.example` incomplete relative to what the code actually consumes | `enterprise_real_sot/.env.example` | Anyone bootstrapping the project can't tell ServiceNow, SNMP, Grafana, maintenance-mode, or webhook vars exist at all | Low | Add all real variable *names* with safe placeholders |
| Documentation claims a NetBox token was "previously present in commit history" and "must be treated as compromised" | `docs/SECURITY_AND_ENV_CONFIG.md:117` | Not corroborated by actual Git history (see Section 9) — either stale/aspirational documentation, or refers to history no longer present, both of which are governance concerns | Informational | Confirm with repo owner and correct the doc either way (not silently resolved here) |
| `deployment/protocols/vtp.py` renders a VTP domain password into device CLI from `vtp_settings` | `deployment/protocols/vtp.py:90-92` | Not a credential-storage bug — this is business config (VTP domain auth) sourced from NetBox config-context data, not hardcoded in source. Flagged for completeness, not remediated. | Informational | No code change; ensure the NetBox config-context value itself is protected the same way other config-context data is |

**Findings ruled out (checked, not actual issues):**
- No `logger.*` call anywhere in `servicenow/` or `deployment/` includes a password, token, or secret value directly (verified by grep across both packages — zero hits).
- `.env` itself has never been committed to Git, at any point in this repo's 13-commit history (`git log --all --oneline -- enterprise_real_sot/.env` returns nothing), and is correctly matched by `.gitignore`.
- `tests/ci_runner.py`'s literal `"snmp-server community NOC-ReadOnly RO"` strings are synthetic mock fixtures for unit tests, not a real credential leak.

## 2. Files Changed

| File | Change |
|---|---|
| `.env` | Added `SERVICENOW_CALLER_ID_SYS_ID`, `SNMP_COMMUNITY`, `GRAFANA_ADMIN_USER`/`GRAFANA_ADMIN_PASSWORD`, `WEBHOOK_HOST`/`PORT`, `SERVICENOW_TIMEOUT`, `SERVICENOW_ADAPTER_URL`, `MAINTENANCE_DEFAULT_DURATION`, `DEVICE_STARTUP_GRACE_PERIOD` — all preserving their existing effective values, so staging behavior is unchanged. Permissions changed `644 → 600`. |
| `.env.example` | Mirrors every real variable name above with safe placeholders only (no real secrets) — now a complete, accurate bootstrap template. |
| `.gitignore` | Added `observability/snmp_exporter/snmp.yml` (the rendered file, which now contains the real community string) — the new `.template` file is left trackable. |
| `servicenow/config/settings.py` | Added `SERVICENOW_CALLER_ID_SYS_ID = os.getenv(...)`, defaulting to the previous hardcoded value for backward compatibility. |
| `servicenow/models/incident_payload.py` | `caller_id` now reads `settings.SERVICENOW_CALLER_ID_SYS_ID` instead of a literal sys_id. |
| `observability/snmp_exporter/snmp.yml.template` | **New.** Checked-in template with `community: ${SNMP_COMMUNITY}` placeholder. |
| `observability/generate_snmp_config.py` | **New.** Host-side renderer: reads `SNMP_COMMUNITY` from `.env`, writes the real `snmp.yml` (git-ignored). Needed because `prom/snmp-exporter` is a static-config binary with no native env-var support and no shell in its image for an entrypoint-substitution approach. |
| `observability/docker-compose.yml` | `grafana` service: removed hardcoded `GF_SECURITY_ADMIN_USER=admin` / `GF_SECURITY_ADMIN_PASSWORD=admin`; added `env_file: - ../.env` (same pattern already used by `servicenow_adapter`) so Grafana picks up `GF_SECURITY_ADMIN_USER`/`GF_SECURITY_ADMIN_PASSWORD` directly from `.env` at container start. |
| `docs/SECURITY_HARDENING_REPORT.md` | This report. |

No changes were made to NetBox, config generation, pre/post-deployment validation, or the rollback implementation.

## 3. .env Architecture

- Real secrets live only in `enterprise_real_sot/.env`, now `600` (owner read/write only), confirmed never committed and correctly `.gitignore`d.
- `.env.example` is now a complete, accurate, secrets-free bootstrap template — every variable the code actually reads has an entry, with either an empty value, an obvious placeholder (`your_ssh_password_here`), or a genuinely non-sensitive default (`SSH_USERNAME=admin` as a username, `SERVICENOW_MOCK_MODE=true` as a safe-by-default staging posture).
- The one exception to "secrets only in `.env`" is the SNMP community: because the consuming binary (`snmp_exporter`) can't read environment variables itself, the real value is rendered into a git-ignored file (`snmp.yml`) from a git-tracked placeholder template (`snmp.yml.template`), with `.env` as the single source of truth for the actual value. This is documented explicitly so it isn't mistaken for an oversight.

## 4. Secrets Management

Design confirmed sound and unchanged: `deployment/credentials.py` resolves SSH credentials purely from environment variables (device-specific → role-profile → default), explicitly never from NetBox or hardcoded values (`credentials.py:26`'s own docstring, verified true by inspection). No secrets-manager/Vault integration exists — acceptable for the current single-operator lab scale, called out as a production gap in Section 11.

## 5. SNMP Security

- **Staging (current)**: SNMPv2c with a shared read-only community string, now sourced from `.env` via the template-render mechanism described above rather than hardcoded in the tracked config file. This is appropriate for an isolated GNS3 lab and was not changed structurally (the actual community *value* is identical to before — verified by SHA-256 hash comparison during regression testing, not just visual inspection).
- **Production (recommendation, not implemented)**: SNMPv2c community strings are not meaningfully secret — they're sent in cleartext on the wire and are visible to anyone who can capture SNMP traffic, regardless of how carefully the config file storing them is protected. For a real production fleet, migrate to **SNMPv3** with per-device (or per-group) authentication and privacy keys (`authPriv` mode), which provides real confidentiality and integrity, not just access-control-on-a-file. This was **not implemented** here because none of the current GNS3 IOSv lab devices are confirmed to support it cleanly and forcing that migration was explicitly out of scope ("do not force migration... if unsupported").

## 6. ServiceNow Credential Security

- Username/password load from `os.getenv` only (`servicenow/config/settings.py`), never hardcoded, never logged (verified: zero hits searching for password/token/secret in any `logger.*` call across `servicenow/`).
- `caller_id` sys_id — previously the one hardcoded identity value — is now environment-configurable (`SERVICENOW_CALLER_ID_SYS_ID`), verified live: a real incident (`INC0010075`) was created and resolved successfully through the changed code path during regression testing.
- **Current account**: the configured ServiceNow account (`SERVICENOW_USERNAME=admin`) is a full administrator on the PDI instance, used directly by the REST integration. This is a real finding, not remediated here because doing so requires action inside the ServiceNow instance itself (creating a scoped service account with a Table API role restricted to `incident` create/update, which is outside what this codebase can do unilaterally) — see Section 11.
  - **Staging/PDI**: using the built-in `admin` account is a normal, low-risk default for a personal developer instance with no other users.
  - **Production**: a dedicated service account (e.g. `svc-nac-integration`) with a role scoped to `incident` table create/update only (not full admin) is the correct target. This is a recommendation for the repo owner to action in the ServiceNow instance, not something invented or fabricated here.

## 7. RBAC / Least-Privilege Model

| Component | What It Needs | What It Must NOT Access | Currently Implemented? |
|---|---|---|---|
| Prometheus | Read-only SNMP scrape via `snmp_exporter`; read its own rule files | No write access to any device, NetBox, or ServiceNow | Yes — Prometheus has no credentials for anything but its own scrape targets |
| Grafana | Read-only query access to Prometheus + Loki datasources | No write access to Prometheus/Loki data, no device credentials | Yes (datasources are read-only by nature of the Prometheus/Loki query API); admin console credential hygiene fixed in this task (Section 2) |
| Alertmanager | Read alert state from Prometheus; POST to the ServiceNow webhook only | No device or ServiceNow credentials of its own (it doesn't authenticate to the webhook - the webhook has no incoming auth, see Section 11) | Partially — Alertmanager itself holds no secrets, but the webhook it posts to is unauthenticated (gap, see Section 11) |
| Loki / Promtail | Receive syslog via the relay; store/query logs | No device credentials, no write path back to devices | Yes |
| SNMP Exporter | Read-only SNMP (`GET`/`WALK`) against monitored devices using the RO community | Must never be configured with a read-write community | Yes — `snmp.yml` only ever defines the `public_v2` **RO** auth; no RW community exists anywhere in this config |
| ServiceNow Adapter | Table API create/update on `incident`; read on `sys_user_group`/`sysevent_email_action` (used during this engagement's diagnostics, not by the running adapter code itself) | Should not need standing admin rights - see Section 6 for the staging-vs-production account distinction | Partial — functionally it only ever calls incident create/update/resolve; the *account* it authenticates as is over-privileged (staging-acceptable, production gap) |
| NetBox | Read access for observability/config-generation; write access is used deliberately by `deployment/` and `device_migration/` to push discovered inventory and config-context | Should not be reachable by Prometheus/Alertmanager/ServiceNow adapter at all - and isn't (no NetBox credential exists in any of those three) | Yes, by absence — none of the observability/ServiceNow components hold a NetBox token |

This table intentionally does not propose enterprise RBAC features (SSO, per-role Grafana teams, ServiceNow ACL scripting) that cannot be realistically operated in a 3-device Docker/GNS3 lab — those are listed as production-track items in Section 11, not implemented as theater here.

## 8. Docker Security Review

Inspected `observability/docker-compose.yml` for privileged containers, root users, unnecessary port exposure, broad mounts, and writable sensitive volumes.

| Issue | Service | Risk | Action Taken |
|---|---|---|---|
| Hardcoded admin credentials in `environment:` | `grafana` | Credential visible in tracked config | **Fixed** (Section 2) |
| Runs as `user: "0:0"` (root) | `loki` | Broader-than-necessary container privilege | **Not changed** — Loki commonly requires root on first run to take ownership of its data directory; changing this without testing against the existing `loki_data` volume risks a permissions failure on next start. Documented as an accepted, understood risk rather than silently left unexamined. |
| All service ports bound to `0.0.0.0` (all interfaces), not `127.0.0.1` | Prometheus (9090), Grafana (3000), Alertmanager (9093), Loki (3100), snmp_exporter (9116), ServiceNow adapter (8000), Promtail (9080) | On a shared or network-exposed host, these UIs/APIs would be reachable from other machines on the LAN | **Not changed** — this is a personal single-user lab host; binding to `127.0.0.1` would be the correct production hardening step but risks breaking the user's own access pattern (e.g. viewing Grafana from another device on the LAN) without explicit confirmation of intent. Recommended for production, not silently applied here. |
| No `privileged: true` anywhere | — | — | Confirmed clean — no service in this compose file requests elevated container privileges. |
| `../servicenow:/app/servicenow:ro` bind mount | `servicenow_adapter` | Correctly read-only for code; only `storage/` is writable (via a separate named volume) | Confirmed already-correct (discovered and relied on earlier in this engagement) — no change needed. |
| Webhook adapter accepts unauthenticated POSTs on `/webhook` and `/maintenance/*` | `servicenow_adapter` | Anyone who can reach port 8000 can create/suppress incidents or toggle maintenance mode | **Not fixed in this pass** — flagged as a real gap in Section 11; adding auth changes the Alertmanager receiver config and the `maintenance_mode.py` CLI simultaneously and was judged too large a change to make safely alongside everything else in this task without dedicated testing. |

## 9. Git Secret Exposure Check

- `git status`: no secret-bearing files staged or modified beyond what's listed in Section 2 (`.env`, which is git-ignored and was never staged).
- `git ls-files | grep -i env`: only `enterprise_real_sot/.env.example` is tracked — never the real `.env`.
- `git log --all --oneline -- enterprise_real_sot/.env`: **empty**. `.env` has never existed in this repository's Git history, at any commit.
- Full-history search (`git log --all -p`) for the NetBox token prefix and the SNMP community string: the community string (`NOC-ReadOnly`) does appear in history, but only inside **generated Cisco IOS CLI output** committed as test fixtures/artifacts (e.g. `"snmp-server community NOC-ReadOnly RO"` in test files) — this is business configuration data that legitimately gets pushed to devices, not a leaked application credential in the password/token sense.
- **`docs/SECURITY_AND_ENV_CONFIG.md:117`'s claim that a NetBox token was "previously present in commit history" and "must be treated as compromised" is not corroborated by the actual history examined here.** Per this task's explicit instruction not to silently rewrite Git history and to report rather than resolve unilaterally: **this discrepancy is reported, not resolved.** Two possibilities, both worth the repo owner's attention: (a) the documentation is stale/aspirational and should be corrected, or (b) it refers to history that existed before this repository's current history was established (e.g. a prior repo that was squashed/recreated) — if (b), the NetBox token in question should be rotated regardless of what this repo's own history shows, since the compromise (if real) would have happened outside what's inspectable here.

## 10. Tests Performed (all live, against the running stack — no mocks for infrastructure)

| Test | Result |
|---|---|
| Docker Compose stack brings up cleanly after all changes (`docker compose up -d`) | All 8 containers reached `healthy` |
| Prometheus SNMP targets scrape using the newly-templated community string | Confirmed via `snmp_exporter`'s raw `/snmp` probe; targets showed a network-level timeout, independently confirmed via `ping` to be the GNS3 lab itself being unreachable (not a config regression) |
| Rendered `snmp.yml` community value is byte-identical to the original hardcoded value | Verified by **SHA-256 hash comparison** (not visual inspection) — hashes matched exactly |
| Grafana admin login works with credentials now sourced from `.env` via `env_file` | `curl -u admin:admin http://localhost:3000/api/org` → `HTTP 200` |
| ServiceNow adapter loads credentials and starts correctly | `GET /health` → `{"status": "healthy", ..., "mock_mode": false}` |
| No secret values appear in any container's logs | Checked `snmp_exporter`, `grafana`, and `servicenow_adapter` logs for the real community string, Grafana password, and ServiceNow password/token — zero hits in all three |
| ServiceNow incident creation still works after the `caller_id` change | Real incident `INC0010075` created and resolved via the live REST API |
| Full CI regression suite (`tests/ci_runner.py`, all 6 layers, including the rollback fix from a prior task) | **PASSED** end-to-end, no regressions |

## 11. Remaining Production Gaps

- ServiceNow account is `admin` (full administrator), not a scoped least-privilege service account — action required inside the ServiceNow instance itself (Section 6).
- SNMPv2c remains in use for staging; SNMPv3 is the correct production target but was not implemented (Section 5).
- `servicenow_adapter`'s `/webhook` and `/maintenance/*` endpoints have no authentication — anyone able to reach port 8000 can act on them. A shared-secret header or mTLS would close this; not implemented in this pass (Section 8).
- All observability ports are bound to all interfaces (`0.0.0.0`); production should bind to `127.0.0.1` and/or sit behind a reverse proxy or VPN (Section 8).
- Loki's container runs as root; a production deployment should investigate whether a non-root UID can be used with proper volume ownership set up in advance.
- No secrets-manager (Vault, AWS Secrets Manager, etc.) integration exists; `.env` remains the entire secret store. Reasonable at current single-operator scale, a real gap beyond it.
- The `docs/SECURITY_AND_ENV_CONFIG.md` token-compromise claim (Section 9) needs the repo owner's judgment call — confirm and rotate, or correct the documentation.

## 12. Final Verdict

```
SECURE FOR STAGING
```

Every finding that could be fixed without breaking the working GNS3 staging environment was fixed and verified live (not just implemented and assumed): no hardcoded credentials remain in tracked source/config files, `.env` is permission-hardened and confirmed never committed, `.env.example` is now complete and safe, and the full CI + live regression suite passes with zero secret leakage found in any container log.

This verdict is explicitly **for staging**, not production — Section 11 lists concrete, unimplemented gaps (service-account least-privilege, SNMPv3, webhook authentication, network exposure, secrets-manager integration) that must be addressed before this posture could be called production-secure. None of those were silently skipped; each was evaluated and deliberately deferred with a stated reason, per this task's instruction not to overengineer what the current 3-device lab doesn't need yet.
