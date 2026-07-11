---
schema_version: 2
spec_version: 0.1.0
workflow_version: 3.1.0
body_sha256: "<generated from the Markdown body>"
status: draft
created_at: "<ISO-8601 with timezone>"
updated_at: "<ISO-8601 with timezone>"
authors:
  - type: human
    name: "<name>"
reviewers: []
administrator_acceptance:
  status: pending
  accepted_by: null
  accepted_spec_version: null
  accepted_body_sha256: null
  accepted_at: null
---

# Specification: <title>

## Background

Explain why the project or change exists.

## Goals

- <goal>

## Non-Goals

- <explicit exclusion>

## Users And Scenarios

- User:
- Scenario:

## Scope

### Required

- <requirement>

### Deferred

- <deferred item>

## Functional Requirements

- <requirement with a stable ID when useful>

## Non-Functional Requirements

- Performance:
- Security:
- Accessibility:
- Compatibility:
- Maintainability:

## Data, Permissions, And External Services

- Data:
- Roles and permissions:
- External services:

## Acceptance Criteria

- <observable pass condition>

## Risks And Trade-Offs

- <risk or trade-off>

## Open Questions

- <question>

## Review Metadata

When a human or agent reviews this version, append a YAML `reviewers` entry with
`type`, identity fields, `decision`, `reviewed_spec_version`,
`reviewed_body_sha256`, and `reviewed_at`. For an agent, also record `provider`,
`product`, and the exact `model` when known; use `unknown` rather than guessing.

Reviewer approval is not administrator acceptance or external-action authority.
Administrator acceptance must bind both `accepted_spec_version` and
`accepted_body_sha256`. Any body change requires a new `spec_version`; previous
reviews and acceptance become historical and do not cover the new version/hash.
