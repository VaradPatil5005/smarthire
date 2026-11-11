# ADR 0002: Shared-schema tenancy

Status: accepted, 2026-11-08.

## Decision

Every tenant row has an organisation key and is read through `for_org`. Organisation comes from `request.membership`. Cross-organisation lookups return 404. This settles D-004.

## Why

It is simple enough to test completely within the schedule, using a registry of every route.

## Cost

A forgotten filter is a breach, so the isolation suite walks every route and fails on an unregistered one. Schema-per-tenant would isolate more strongly.
