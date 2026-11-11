# ADR 0001: Evidence-locked scoring

Status: accepted, 2026-11-08.

## Decision

Scores come only from the approved rubric and reviewer-accepted visible evidence, through one pure function. No TF-IDF, embedding or LLM output reaches a score.

## Why

Hidden text and instructions then have no path into a score, so safety comes from the architecture rather than from detecting each trick.

## Cost

Reviewers must accept evidence before it counts, so a new résumé scores low until someone reviews it. Visible false claims are not detected.
