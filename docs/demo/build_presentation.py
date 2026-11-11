"""Build the offline submission deck from repository text and synthetic demo screenshots.

Uses only the standard library for HTML. Pass --render to export its PDF with the
project's existing Playwright development dependency and installed Chromium.
"""

# Embedded slide copy and CSS retain their authored line breaks.
# ruff: noqa: E501

import argparse
import base64
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = ROOT / "docs" / "demo"


def data_uri(path, media_type):
    return f"data:{media_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def screenshot(filename, caption, offset=0):
    uri = data_uri(DESTINATION / "screenshots" / filename, "image/png")
    return (
        '<figure><div class="capture">'
        f'<img src="{uri}" alt="{caption}" style="margin-top:-{offset}px">'
        f"</div><figcaption>{caption}</figcaption></figure>"
    )


def build_html():
    font = data_uri(
        ROOT / "static" / "fonts" / "plus-jakarta-sans-latin-wght-normal.woff2",
        "font/woff2",
    )
    slides = [
        (
            "SmartHireAI",
            '<p class="eyebrow">We.PLM internship submission</p>'
            '<h1>SmartHireAI</h1><p class="lead">Project requirements.<br>'
            "Consultant evidence.<br>A shortlist a reviewer can explain.</p>"
            '<p class="quiet cover-note">Varad · 11 November 2026<br>'
            "Python / Django / PostgreSQL<br>All demonstration data is synthetic.</p>",
            "Introduce the consultancy use case. The project supports internal bench consultants "
            "and external applicants. Describe spaCy phrase rules honestly as the extraction baseline.",
        ),
        (
            "The company brief",
            '<h2>The company brief</h2><p class="intro">Six modules, with a visible end-to-end path.</p>'
            '<table class="modules"><thead><tr><th>Module</th><th>What the evaluator can try</th></tr>'
            "</thead><tbody><tr><td>User authentication</td><td>Role homes and organisation access</td></tr>"
            "<tr><td>Candidate management</td><td>Invitation, profile, skills and PDF upload</td></tr>"
            "<tr><td>Project requirements</td><td>Weighted skills and approved rubric versions</td></tr>"
            "<tr><td>Skill matching</td><td>Aliases, visible evidence and reviewer decisions</td></tr>"
            "<tr><td>Candidate ranking</td><td>Review groups, ties and reproducible results</td></tr>"
            "<tr><td>Dashboard and reports</td><td>Bench utilisation and filtered CSV/XLSX</td></tr>"
            "</tbody></table>",
            "The original company DOCX lists these six core modules. All have implementations. "
            "Candidate registration is invitation-based. Staff invitation issuance has no UI yet. "
            "Source: docs/source/assignment.md, actual company DOCX, docs/manual/verification-2026-11-11.md.",
        ),
        (
            "A PLM staffing decision",
            '<h2>A PLM staffing decision</h2><p class="intro">One requirement compares internal '
            "consultants and external applicants.</p>"
            '<div class="split"><div><p>3DEXPERIENCE migration</p><ul>'
            "<li>ENOVIA configuration: required, weight 5</li>"
            "<li>Migration validation: required, weight 3</li>"
            "<li>Python automation: preferred, weight 2</li></ul>"
            '<p class="quiet">A manager approves the rubric before matching.</p></div>'
            + screenshot("1-requirement.png", "Recorded synthetic project and rubric, 9 November")
            + "</div>",
            "Live demo: manager, Projects, 3DEXPERIENCE migration. Approve and lock v1. "
            "The displayed requirement is fictional. Source: docs/demo/script.md and "
            "apps/demo/management/commands/seed_demo.py. Screenshot is the recorded 9 November demo.",
        ),
        (
            "Coverage and Staffing fit",
            '<h2>Coverage and Staffing fit</h2><p class="intro">Merit and availability remain '
            "separate, so the reason behind a rank stays clear.</p>"
            '<div class="score-explanation"><p><strong>Coverage</strong><br>Weighted criteria '
            "supported by accepted evidence, adjusted for required duration.</p>"
            "<p><strong>Staffing fit</strong><br>Capacity and start-date fit, using the stored run date.</p></div>"
            "<table><thead><tr><th>Worked example</th><th>Credited weight / 10</th>"
            "<th>Coverage</th></tr></thead><tbody>"
            "<tr><td>A: ENOVIA + self-reported migration</td><td>6.5</td><td>65.00</td></tr>"
            "<tr><td>B: ENOVIA + Python</td><td>7.0</td><td>70.00</td></tr>"
            "<tr><td>B: accepted visible migration evidence added</td><td>10.0</td>"
            "<td>100.00</td></tr></tbody></table>"
            '<p class="quiet">Coverage describes this project\'s criteria. It is not a probability '
            "of hiring success.</p>",
            "Show A's evidence drawer. Accepted project evidence earns 1.0. A confirmed form claim "
            "earns 0.5. Unknown and provisional matches earn zero. Credit counts each skill once. "
            "Source and exact calculation: docs/architecture/scoring.md sections 1, 2, 3 and 6.",
        ),
        (
            "The evidence path",
            '<h2>The evidence path</h2><p class="intro">The scorer receives structured records.</p>'
            '<ol class="path"><li><strong>Upload and quarantine</strong><span>Private PDF storage, '
            "bounded input, scanner child process</span></li>"
            "<li><strong>Visible-text extraction</strong><span>Hidden spans stay excluded and available "
            "for staff review</span></li><li><strong>Provisional skill suggestions</strong><span>spaCy "
            "phrase rules and controlled aliases</span></li>"
            "<li><strong>Evidence eligibility</strong><span>Reviewer-accepted visible passage, or "
            "a candidate-confirmed form claim</span></li>"
            "<li><strong>One scoring function</strong><span>Approved rubric, accepted evidence and "
            "versioned run inputs</span></li></ol>",
            "No LLM reads instructions and assigns a score. The application performs actions through "
            "ordinary validated Django services. Hidden flags never subtract points or automatically "
            "reject a candidate. Sources: README.md, docs/architecture/scoring.md, ingestion and matching services.",
        ),
        (
            "The attacked resume",
            '<h2>The attacked resume</h2><p class="intro">Hidden migration keywords add no credit. '
            "Candidate B stays at 70.00.</p>"
            '<div class="split xray"><div><p>The X-ray exposes the excluded text.</p>'
            "<p>A reviewer can inspect the file without treating a flag as proof of cheating.</p>"
            '<p class="quiet">Visible false claims still require an interview or skills test.</p></div>'
            + screenshot("3-xray.png", "Recorded X-ray excerpt of a synthetic attack, 9 November")
            + "</div>",
            "Upload fixtures/pdf/demo_candidate_b_attacked.pdf and open X-ray. Show the hidden "
            "migration text. Run matching and confirm B remains at 70. Source: docs/demo/script.md, "
            "tests/adversarial/test_attack_twins.py. The screenshot shows the prior recorded demo, "
            "not the final motion changes.",
        ),
        (
            "Correction and history",
            '<h2>Correction and history</h2><p class="intro">A reviewer accepts new visible evidence. '
            "A new run changes the score.</p>"
            '<div class="split"><div><p class="big-value">70.00 <span>then</span> 100.00</p>'
            "<p>The corrected migration passage supplies the missing required evidence.</p>"
            '<p class="quiet">The old run preserves its score and inputs. Screen, API and export '
            "use stored results.</p></div>"
            + screenshot(
                "4-corrected-100.png", "Recorded corrected shortlist excerpt, 9 November", 160
            )
            + "</div>",
            "Upload demo_candidate_b_corrected.pdf. Accept Migration validation with a reason, rerun "
            "and show B at 100. Then open the earlier run at 70. Export the same shortlist filters. "
            "Sources: docs/demo/script.md, docs/architecture/scoring.md section 7.",
        ),
        (
            "Verification evidence",
            '<h2>Verification evidence</h2><p class="intro">Recorded baseline: 9 November 2026, '
            "Windows, Python 3.12.6, PostgreSQL 16.14.</p>"
            "<table><thead><tr><th>Check</th><th>Recorded result</th></tr></thead><tbody>"
            "<tr><td>Full non-browser suite</td><td>878 passed, coverage 95%</td></tr>"
            "<tr><td>Attack twin comparisons</td><td>0 promotions across 18 pairs, 2 review policies</td></tr>"
            "<tr><td>Benign scanner examples</td><td>0 flags across 9 documents</td></tr>"
            "<tr><td>Isolation suite</td><td>394 passed</td></tr>"
            "<tr><td>Browser suite</td><td>2 passed</td></tr></tbody></table>"
            '<p class="quiet">These results cover named fixtures. They are not a universal guarantee. '
            "Current submission checks are recorded separately.</p>",
            "Do not describe the historical baseline as the latest final run. The submission audit "
            "adds fixes and checks. Use its actual result for a current count when presenting. "
            "Source: docs/manual/test-register.md, Summary and Metrics with denominators. "
            "Extraction quality and reviewer time are distinct from test pass rates.",
        ),
        (
            "Repository handover",
            '<h2>Repository handover</h2><p class="intro">Each company deliverable has an entry point.</p>'
            "<table><thead><tr><th>Deliverable</th><th>Entry point</th></tr></thead><tbody>"
            "<tr><td>Source code</td><td>README setup, apps/, config/, templates/, static/</td></tr>"
            "<tr><td>Database schema</td><td>docs/architecture/er.md and migrations</td></tr>"
            "<tr><td>API documentation</td><td>/api/docs/ and docs/contracts/openapi.yaml</td></tr>"
            "<tr><td>Test cases</td><td>App tests, tests/ and test register</td></tr>"
            "<tr><td>User manual</td><td>Candidate and recruiter guides</td></tr>"
            "<tr><td>Final presentation</td><td>This PDF, offline deck and five-minute script</td></tr>"
            "</tbody></table>",
            "The project uses Django templates with Bootstrap and HTMX, DRF for APIs, PostgreSQL "
            "for the assessed database and django-q2 for jobs. Secrets and private uploads stay out "
            "of the submitted source. README has both PowerShell and Git Bash setup. "
            "Sources: README.md, Makefile, pyproject.toml, requirements.in, docs/manual/submission-checklist.md.",
        ),
        (
            "Limits and next validation",
            '<h2>Limits and next validation</h2><div class="closing"><div>'
            "<h3>Current limits</h3><ul><li>Controlled phrase matching, with no trained model or LLM</li>"
            "<li>PDF only, with manual skill entry as fallback</li>"
            "<li>Invitation issuance has no staff UI</li>"
            "<li>No interview scheduler or email notifications</li>"
            "<li>No real-project suitability or time-saved study</li></ul></div><div>"
            "<h3>Next validation</h3><p>A mentor labels skills and shortlist suitability for a held-out set.</p>"
            "<p>A project lead compares manual staffing with the prototype in a timed shadow review.</p>"
            '<p class="quiet">Measure precision, recall, Precision@3, missed suitable people and '
            "reviewer time before broader use.</p></div></div>",
            "Finish with a specific validation plan rather than claiming AI accuracy. Additional "
            "production work includes privacy review, retention/deletion, host isolation and shared "
            "throttling. The prototype demonstrates the six core modules and evidence controls. "
            "Sources: docs/manual/test-register.md Not measured, README.md Known limits, "
            "docs/manual/verification-2026-11-11.md. Do not promise a score-rule change.",
        ),
    ]
    css = """
@font-face{font-family:Jakarta;src:url(FONT_URI) format('woff2');font-weight:200 800;font-display:block}
*{box-sizing:border-box}html,body{margin:0;background:#171717;color:#111;font-family:Jakarta,Arial,sans-serif}
body{display:grid;place-items:center;min-height:100vh}.slide{width:1280px;height:720px;background:#f6f4f1;
padding:56px 64px 50px;display:none;position:relative;overflow:hidden}.slide.active{display:block}
.slide:first-child{background:#101010;color:#f6f4f1}.slide:focus{outline:none}h1{font-size:94px;letter-spacing:-5px;
margin:44px 0 24px;line-height:1}h2{font-size:44px;letter-spacing:-1.8px;line-height:1.2;margin:0 0 20px}
h3{font-size:25px;margin:0 0 22px}p{font-size:25px;line-height:1.5;margin:0 0 24px}.intro{color:#5a5956;
font-size:24px;margin-bottom:36px}.lead{font-size:40px;line-height:1.35;letter-spacing:-1px}.eyebrow{font-size:18px;
letter-spacing:3px;color:#c0beb9}.quiet{font-size:18px;line-height:1.55;color:#625f59}.cover-note{position:absolute;
right:64px;bottom:54px;text-align:right;color:#bbb9b4}.split{display:grid;grid-template-columns:400px 1fr;gap:46px;
align-items:start}.split>div:first-child{padding-top:18px}.split p{font-size:23px}.split ul{padding-left:26px;
font-size:23px;line-height:1.6}.split li{margin-bottom:18px}figure{margin:0;min-width:0}.capture{height:422px;
overflow:hidden;background:#fff;border:1px solid #dedbd5}.capture img{width:100%;height:auto;display:block}
figcaption{font-size:14px;color:#625f59;line-height:1.4;margin-top:10px}table{width:100%;border-collapse:collapse;
font-size:22px;margin-bottom:24px}th{font-size:16px;text-align:left;color:#625f59;font-weight:600;padding:0 16px 16px 0;
border-bottom:2px solid #111}td{padding:17px 18px 17px 0;border-bottom:1px solid #d9d6d0;line-height:1.3}
td:first-child{width:44%}.modules td{padding-top:15px;padding-bottom:15px}.modules td:first-child{width:34%}
.score-explanation{display:grid;grid-template-columns:1fr 1fr;gap:64px;margin-bottom:20px}.score-explanation p{
font-size:21px;line-height:1.5}.score-explanation strong{font-size:25px}.path{margin:30px 0 0;padding-left:40px;
counter-reset:steps}.path li{font-size:24px;padding-left:18px;margin-bottom:24px}.path span{display:block;
font-size:19px;color:#625f59;margin-top:5px}.big-value{font-size:42px!important;font-weight:700;letter-spacing:-1px}
.big-value span{font-size:18px;font-weight:400;color:#625f59}.closing{display:grid;grid-template-columns:1fr 1fr;
gap:72px;margin-top:48px}.closing ul{font-size:23px;line-height:1.5;padding-left:28px;margin:0}.closing li{
margin-bottom:19px}.closing p{font-size:23px}.slide-no{position:absolute;bottom:20px;right:30px;font-size:13px;color:#827e76}
nav{position:fixed;bottom:10px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:15px;
padding:8px 14px;background:#fff;color:#111;border-radius:30px;box-shadow:0 2px 15px #0002;font-size:13px}
button{font:inherit;border:1px solid #ddd;background:transparent;padding:7px 15px;border-radius:20px;cursor:pointer}
button:hover{background:#efede9}button:focus-visible{outline:3px solid #147c5a;outline-offset:3px}
button:disabled{opacity:.4;cursor:default}#speaker-notes{position:fixed;inset:24px;overflow:auto;background:white;
padding:36px;z-index:10;border:2px solid #111}#speaker-notes h3{margin:24px 0 8px}#speaker-notes p{font-size:18px}
#speaker-notes[hidden]{display:none}@media(max-width:1279px){body{display:block;min-width:1280px}nav{left:640px}}
@page{size:13.333333in 7.5in;margin:0}@media print{html,body{background:#fff;display:block;min-height:0}
.slide,.slide.active{display:block!important;break-after:page;page-break-after:always;width:1280px;height:720px;
print-color-adjust:exact;-webkit-print-color-adjust:exact}.slide:last-of-type{break-after:auto;page-break-after:auto}
nav,#speaker-notes{display:none!important}}
""".replace("FONT_URI", font)
    pages = "".join(
        f'<section class="slide{" active" if index == 0 else ""}" '
        f'aria-label="Slide {index + 1}: {title}" tabindex="-1">{content}'
        f'<span class="slide-no">{index + 1:02d} / {len(slides)}</span></section>'
        for index, (title, content, _) in enumerate(slides)
    )
    notes = "".join(
        f"<h3>{index + 1}. {title}</h3><p>{note}</p>"
        for index, (title, _, note) in enumerate(slides)
    )
    script = """
const slides=[...document.querySelectorAll('.slide')]; let current=0;
const previous=document.querySelector('#previous'),next=document.querySelector('#next');
const notes=document.querySelector('#speaker-notes'),notesButton=document.querySelector('#notes');
function show(index){current=Math.max(0,Math.min(slides.length-1,index));
slides.forEach((slide,i)=>{slide.classList.toggle('active',i===current);
slide.setAttribute('aria-hidden',String(i!==current));});
document.querySelector('#position').textContent=`${current+1} / ${slides.length}`;
previous.disabled=current===0;next.disabled=current===slides.length-1;}
previous.addEventListener('click',()=>show(current-1));next.addEventListener('click',()=>show(current+1));
notesButton.addEventListener('click',()=>{notes.hidden=!notes.hidden;
notesButton.setAttribute('aria-expanded',String(!notes.hidden));});
document.addEventListener('keydown',event=>{if(event.key==='Escape'){notes.hidden=true;
notesButton.setAttribute('aria-expanded','false');return;}if(!notes.hidden)return;
if(['ArrowRight','PageDown','ArrowLeft','PageUp','Home','End'].includes(event.key)){event.preventDefault();
if(['ArrowRight','PageDown'].includes(event.key))show(current+1);
if(['ArrowLeft','PageUp'].includes(event.key))show(current-1);
if(event.key==='Home')show(0);if(event.key==='End')show(slides.length-1);}});show(0);
"""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>SmartHireAI - Final Presentation</title><style>"
        + css
        + "</style></head><body>"
        + pages
        + '<nav aria-label="Presentation controls"><button id="previous" type="button">Previous</button>'
        '<span id="position" aria-live="polite"></span><button id="next" type="button">Next</button>'
        '<button id="notes" type="button" aria-expanded="false" aria-controls="speaker-notes">'
        'Speaker notes</button></nav><aside id="speaker-notes" hidden>'
        "<p>Speaker notes and source references. Press Escape to close.</p>"
        + notes
        + "</aside><script>"
        + script
        + "</script></body></html>"
    )


def render(html_path):
    import playwright

    # The bundled Node driver avoids asyncio socketpair restrictions in the Windows sandbox.
    driver = Path(playwright.__file__).parent / "driver"
    executable = driver / ("node.exe" if (driver / "node.exe").exists() else "node")
    subprocess.run(  # noqa: S603  # Fixed local renderer and bundled executable, no shell.
        [
            str(executable),
            str(DESTINATION / "render_presentation.cjs"),
            str(html_path),
            str(driver / "package"),
        ],
        check=True,
        cwd=ROOT,
        timeout=90,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", action="store_true", help="Export PDF using installed Chromium")
    arguments = parser.parse_args()
    html_path = DESTINATION / "SmartHireAI_Final_Presentation.html"
    html_path.write_text(build_html(), encoding="utf-8")
    if arguments.render:
        render(html_path)
    print(html_path)


if __name__ == "__main__":
    main()
