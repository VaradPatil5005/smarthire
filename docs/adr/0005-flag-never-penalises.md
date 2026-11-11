# ADR 0005: Flags exclude spans and never subtract

Status: accepted, 2026-11-08.

## Decision

A hidden-text flag excludes the span and opens review. It never lowers a score, changes a group or rejects a candidate.

## Why

Honest documents can trip detectors, for example through OCR layers or dark banners.

## Cost

A cheater keeps their real score until a human reads the X-ray panel. The human decides.
