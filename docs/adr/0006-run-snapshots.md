# ADR 0006: Runs store their inputs

Status: accepted, 2026-11-08.

## Decision

A MatchRun pins versions and run date and stores the exact function inputs per profile. Publishing happens in one transaction, and idempotency is unique per organisation.

## Why

Any old score can be reproduced after profiles, rubrics or dictionaries change, and a failed run never replaces a good shortlist.

## Cost

Snapshots duplicate data and hold evidence records, so retention must cover them.
