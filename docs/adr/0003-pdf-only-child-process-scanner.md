# ADR 0003: PDF only, scanned in a child process

Status: accepted, 2026-11-08.

## Decision

v1 accepts PDF only (D-003). Parsing runs in a child process with a scrubbed environment and a time limit, returning JSON; only the parent touches the database (D-011).

## Why

A parser bug should not reach secrets or the database, and the web request never parses a file.

## Cost

Windows has no rlimit, so memory is not capped there. There is no network sandbox on a developer machine; deployment must add one.
