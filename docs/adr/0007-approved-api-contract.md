# ADR 0007: Serve the reviewed API contract

Date: 2026-11-10

Status: Accepted for the internship submission; endpoint behaviour is unchanged.

## Context

The initial drf-spectacular output discovered all 36 API paths, but APIViews whose
`serializer_class` is `None` were documented as returning no body. Their implementations
actually return JSON, including rubric versions, scan status, match runs, evidence and
reports. A route inventory alone is insufficient for the assignment's API documentation
deliverable.

## Decision

`docs/contracts/openapi.yaml` is the reviewed description of the existing API. It retains
the same 36 paths and 49 HTTP operations, and documents actual request bodies, success
statuses, response shapes, multipart files, filters, session authentication and CSRF.
Profile and project serializer-derived schemas are retained; APIView responses are
described explicitly. The schema also explains candidate-only status masking, object
scoping and role checks.

The lead supplies `ApprovedSchemaGenerator` in `apps/core/schema.py`; the backend owner
configures drf-spectacular to use it. `/api/schema/` and `/api/docs/` then consume this
same reviewed contract instead of emitting incomplete introspection output. Static
documentation does not change any endpoint's permissions, validation or response data.

Tests must validate the OpenAPI document and compare its path/method inventory with the
live URL configuration. A behaviour change also requires the endpoint owner and
architect to update its schemas and examples. Contract validation proves structural
validity and route parity; it does not prove every possible response matches every
schema, so source review and request/response tests remain necessary.

## Consequences

- Evaluators can inspect typed matching, import, scanning and reporting examples in
  the same Swagger UI already shipped with the project.
- No endpoint, scoring rule, authentication mechanism or dependency is added.
- Authentication uses the HTML login form; a token-login API is not implied.
- Errors describe the implemented detail/field-message variants without inventing an
  error-envelope migration.
- The contract is maintained explicitly. Regenerating over it with default
  introspection would lose reviewed APIView schemas and is not the authoring workflow.
- Endpoint-level schema assertions should grow alongside behaviour changes. Existing
  route parity tests alone cannot detect field-level documentation drift.
