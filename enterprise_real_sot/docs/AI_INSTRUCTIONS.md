# AI Coding Assistant Instructions

## Mandatory Reading

Before modifying code, read every Markdown document under `docs/`, including this file. Then inspect the relevant implementation and tests before proposing or applying a change.

## Architectural Rules

- Preserve the established architecture. Do not redesign it unless the user explicitly requests an architectural redesign.
- Never modify, replace, or redesign the completed Import Layer in `python/importers/`, its `python/importers/run_import.py` entry point, or the CSV-driven import workflow unless the user explicitly authorizes that exact work.
- Treat NetBox as the runtime source of truth for all Deployment Layer behaviour.
- Never make Deployment Layer code read files from `csv/` or rely on CSV records at runtime.
- Keep Import Layer and Deployment Layer separate. Use NetBox APIs and the `deployment/` runtime components as the boundary.

## Implementation Rules

- Implement one cohesive module or change at a time. Complete it, validate it, and keep the diff focused before proceeding to the next module.
- Keep modules independent and assign one primary responsibility to each: NetBox access, selection, context building, rendering, one protocol, or transport.
- Prefer reusable functions and existing project helpers over copied logic.
- Do not create unnecessary abstractions. Introduce an interface, base class, or framework only when a concrete implementation needs it.
- Do not create placeholders, empty stubs, `TODO` implementations, fake success responses, or speculative modules.
- Follow `CODING_STANDARDS.md` for names, imports, logging, error handling, validation, and test expectations.
- Do not hardcode device names, protocol names, roles, sites, platforms, interfaces, VLANs, or credentials. Read runtime data from NetBox and settings from appropriate configuration.
- Do not expose credentials, NetBox tokens, passwords, TACACS keys, SNMP communities, or other secrets in code, logs, tests, generated documentation, or examples.

## Deployment Work Rules

- Build deployment behaviour around the existing `NetBoxClient`, `DeviceSelector`, and `ContextBuilder` unless the requested change explicitly requires a compatible extension.
- Use the unified context shape produced by `ContextBuilder`: `device_info`, `config`, and `interfaces`.
- Keep configuration generators deterministic and side-effect free.
- Keep protocol plugins independent: they consume context and render their own feature; they do not select devices, read CSV, or open transports.
- Keep device connectors responsible only for communication and execution reporting.

## Change Discipline

- Inspect repository state before editing. Preserve unrelated user changes.
- Modify only files needed for the requested task.
- Add or update tests for behaviour changes where test infrastructure exists.
- Report what changed, how it was verified, and any remaining limitations. Do not claim a deployment stage is implemented when it is only documented or scaffolded.





## Repository Validation Rule

Before implementing any module:

1. Read all documentation under docs/.
2. Verify that the repository structure matches ARCHITECTURE.md.
3. If a structural mismatch is found (folders, package locations, imports), correct the structure before implementing new code.
4. Explain every structural change before making it.