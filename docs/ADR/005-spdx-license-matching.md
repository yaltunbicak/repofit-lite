# ADR-005: SPDX License Matching with license-expression

## Status
Accepted

## Context
License policy matching used `startswith()` prefix comparison, which collapsed legally distinct licenses (e.g., `AGPL-3.0-only` vs `AGPL-3.0-or-later`). GitHub also returns deprecated SPDX identifiers.

## Decision
Use `license-expression` library (nexB) for:
- Exact case-insensitive SPDX matching after normalization
- Automatic resolution of deprecated identifiers (e.g., `AGPL-3.0` -> `AGPL-3.0-only`)
- Compound expression parsing (e.g., `GPL-2.0 OR MIT`)

## Consequences
- **Pro:** Correct SPDX semantics per specification
- **Pro:** GitHub's deprecated IDs handled automatically
- **Pro:** PEP 639 reference implementation
- **Con:** New runtime dependency (~120KB + boolean.py)

## Alternatives Considered
- **Manual normalization map**: Rejected — incomplete, maintenance burden
- **Prefix matching with special cases**: Rejected — fundamentally wrong per SPDX spec
