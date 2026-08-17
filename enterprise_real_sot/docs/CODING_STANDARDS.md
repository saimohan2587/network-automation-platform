# Coding Standards

## Scope and Principles

Use these standards for new code, especially Deployment Layer additions. Preserve the completed Import Layer as-is. Code must be clear, deterministic, testable, and organised around one responsibility per module.

## Naming and Layout

- Use lowercase `snake_case` for Python modules, packages, functions, methods, variables, and parameters: `device_selector.py`, `build_device_context`, `site_slug`.
- Use `PascalCase` for classes and exceptions: `NetBoxClient`, `ContextBuilder`, `NetBoxAPIError`.
- Use `UPPER_SNAKE_CASE` for constants and environment-backed configuration: `HTTP_TIMEOUT`, `MAX_WORKER_THREADS`.
- Use descriptive nouns for data: `device_context`, `selection_criteria`, `tagged_vlan_ids`. Avoid ambiguous names such as `data`, `result`, or `item` except in short, tightly scoped expressions.
- Name folders by their bounded responsibility in lowercase: `deployment/`, `python/importers/`, `src/parser/`, `tests/`.
- Add a module only to the package responsible for its behaviour. Do not create catch-all utility modules for unrelated logic.

## Python Conventions

- Target the repository's existing typed style for new Deployment Layer code: use `typing` annotations for public functions, methods, and meaningful local collections.
- Use docstrings for public classes, exceptions, and functions where behaviour or contracts are not obvious from the signature.
- Keep functions focused. Split a function when it combines selection, data access, transformation, rendering, and transport.
- Prefer pure transformations for context normalization and configuration rendering; isolate NetBox and device I/O at module boundaries.
- Use `pathlib` or existing project path conventions consistently within a module. Do not introduce a second path-resolution scheme without a need.

## Imports

Order imports in three groups, separated by blank lines:

1. Python standard library.
2. Third-party packages.
3. Project imports.

Within each group, keep imports alphabetical where practical. Import from the owning module rather than duplicating its logic.

## Logging and Errors

- Obtain loggers through `deployment.logger.get_logger` for Deployment Layer modules; retain the Import Layer's existing `NetBoxImporter` logging convention without changing it.
- Log useful operational context, such as a device name, site, endpoint, selector, or protocol. Never log credentials, API tokens, passwords, shared secrets, or complete sensitive configuration contexts.
- Raise domain-specific exceptions at API and transport boundaries; preserve the original exception with `raise ... from error`.
- Do not silently catch broad exceptions. If recovery is intentional, log the reason and return a documented fallback value.
- Treat a partial device deployment as a visible failure state. Do not report success until the connector verifies its defined outcome.

## Configuration and Data Access

- Read runtime inventory, addressing, roles, sites, platforms, tags, custom fields, interfaces, and configuration context from NetBox.
- Never hardcode device names, protocol names, roles, sites, interfaces, VLAN identifiers, platform slugs, or connection targets.
- Read environment-specific connection settings from configuration or environment variables, never from literals embedded in deployment logic.
- Keep CSV access strictly inside the existing Import Layer. Deployment code must never import CSV readers or read paths below `csv/`.

## Modularity and Reuse

- Apply the Single Responsibility Principle: a selector selects, a context builder assembles context, a generator renders configuration, a plugin owns one protocol's rendering, and a connector communicates with a device.
- Reuse shared client, logging, merge, validation, and data-normalisation helpers instead of copying them into each protocol module.
- Prefer composition over a large inheritance tree. A deployment orchestrator should coordinate explicit collaborators.
- Add abstractions only when at least two real consumers need the same contract. Do not create placeholders, speculative plugin hierarchies, or generic wrappers without a concrete use.
- Keep protocol modules independent. A protocol plugin may use the common device context but must not depend on another protocol plugin's internal state.

## Validation and Tests

- Validate required NetBox fields before generation and report which device and field caused the failure.
- Unit-test pure selectors, merge behaviour, context normalization, and configuration generation with realistic NetBox payloads.
- Mock NetBox and device transports in unit tests; reserve real API/device calls for explicit integration tests.
- Ensure changes preserve deterministic output for the same NetBox context.
