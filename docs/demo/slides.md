# Final presentation

The company requires a final presentation but does not prescribe a PowerPoint file format.
The complete ten-slide deck is available as:

- [PDF](SmartHireAI_Final_Presentation.pdf), for offline presentation and submission.
- [Self-contained HTML deck](SmartHireAI_Final_Presentation.html), for browser presentation with
  Left/Right, Home/End and Previous/Next controls. Speaker notes include the source references.
- [Five-minute live demo script](script.md), with the original synthetic screenshot fallback.

## Slide order and suggested timing

| Slide | Subject | Seconds |
| --- | --- | --- |
| 1 | Project and PLM staffing use case | 15 |
| 2 | The six company modules | 20 |
| 3 | The approved migration requirement | 30 |
| 4 | Coverage, Staffing fit and exact worked scores | 35 |
| 5 | Evidence path and scoring boundary | 30 |
| 6 | Attacked resume and X-ray | 40 |
| 7 | Correction and immutable history | 40 |
| 8 | Dated verification evidence and its limits | 30 |
| 9 | Six deliverables and repository entry points | 20 |
| 10 | Current limits and next validation | 40 |

Total: five minutes. For a live demo, use slides as framing and keep the detailed workflow in
`script.md`. The screenshot excerpts were recorded on 9 November 2026. They show the demo's
functional path before the final animation pass. They do not demonstrate the current animation.

Slide 8 explicitly shows the 9 November baseline. It is not a claim about the final submission
revision. Use current recorded checks separately when discussing the latest revision.

## Regeneration

The HTML embeds the repository's font and original synthetic demo screenshots, so it needs no
network connection. Copy and style live in `build_presentation.py`. The HTML source remains editable.
The PDF contains selectable text and the same ten slides.

With the repository's existing virtual environment and installed Playwright Chromium:

```powershell
& .\.venv\Scripts\python.exe docs/demo/build_presentation.py --render
```

If this machine's Chromium lives under `.tools/playwright`, set
`$env:PLAYWRIGHT_BROWSERS_PATH = (Resolve-Path '.tools/playwright').Path` first. For a standard
Playwright installation no browser-path override is needed. Regeneration writes the final HTML
and PDF in this directory and slide previews under `.cache/submission-audit/presentation/`.
Inspect every slide after changes.
