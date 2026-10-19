"""Single-page HTML dashboard for the course tracker.

One self-contained file: fonts inlined as data URIs, no network, no server, no
build step. Opens straight from disk.

Design brief, in priority order:

  1. Answer "what do I have to do next" in the first screen, not in a table
     the reader has to scan. That is the Action panel.
  2. Make time legible. A deadline is only useful if the reader can feel how
     close it is, so countdowns are tabular, colour-coded by urgency, and
     refresh themselves from data-due attributes.
  3. Let a course collapse. Nine courses with no assignments should not cost
     nine screenfuls. <details> does this natively and stays keyboard-usable.
  4. Never claim more than the data supports. A course with no assignments is
     "nothing found at the last check", not "no assignments".
"""

from __future__ import annotations

import base64
import hashlib
import html
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# ---- fonts ---------------------------------------------------------------
# Fonts ship inside the package so a pip install carries them. An earlier
# version looked in a sibling directory and found nothing, which meant the
# dashboard silently fell back to Tahoma - Persian set in a face that was never
# designed for Arabic script. The "named but not embedded" failure is invisible
# in a screenshot unless you know to look, so there is a test for it.
FONT_DIRS = (
    Path(__file__).resolve().parent / "fonts",
    Path(__file__).resolve().parent.parent.parent / "assets" / "fonts",
)
# Ordered by preference. Variable fonts first: one file covers every weight.
FONT_PREFERENCE = (
    ("Estedad", ("Estedad-VF.ttf",), "100 900"),
    ("Vazirmatn", ("Vazirmatn-Regular.ttf", "Vazirmatn-Bold.ttf"), None),
)
_font_cache: str | None = None


def font_css() -> str:
    global _font_cache
    if _font_cache is not None:
        return _font_cache
    rules: list[str] = []
    for family, filenames, weight_range in FONT_PREFERENCE:
        found = []
        for name in filenames:
            for folder in FONT_DIRS:
                path = folder / name
                if path.is_file():
                    found.append((name, path))
                    break
        if not found:
            continue
        if weight_range and len(filenames) == 1:
            blob = base64.b64encode(found[0][1].read_bytes()).decode("ascii")
            rules.append(
                "@font-face{{font-family:'{f}';font-style:normal;font-weight:{w};"
                "font-display:swap;src:url(data:font/ttf;base64,{b}) format('truetype');}}".format(
                    f=family, w=weight_range, b=blob
                )
            )
        else:
            # Static faces: infer the weight from the filename.
            for name, path in found:
                weight = 700 if "Bold" in name else 400
                blob = base64.b64encode(path.read_bytes()).decode("ascii")
                rules.append(
                    "@font-face{{font-family:'{f}';font-style:normal;font-weight:{w};"
                    "font-display:swap;src:url(data:font/ttf;base64,{b}) format('truetype');}}".format(
                        f=family, w=weight, b=blob
                    )
                )
    _font_cache = "\n".join(rules)
    return _font_cache


# ---- design tokens -------------------------------------------------------

CSS = """
:root{
  --radius-pill:99px; --icon-size-large:46px;
  --white:#fff; --accent-strong:#176d60; --focus-border:#59a896; --accent-border-soft:#b3d4ca;
  --measure-12:12px; --measure-10:10px; --measure-11:11px; --measure-14:14px; --measure-8:8px; --measure-2:2px; --measure-9:9px; --measure-13:13px; --measure-15:15px; --measure-16:16px; --measure-5:5px; --measure-18:18px; --measure-6:6px; --measure-20:20px; --measure-17:17px; --measure-10_5:10.5px; --measure-7:7px; --measure-4:4px; --measure-11_5:11.5px; --measure-22:22px; --measure-21:21px;
  --ink:#101418; --ink-2:#3d4650; --muted:#77808b; --faint:#a4acb6;
  --line:#e7e3db; --line-2:#f0ede6; --bg:#f6f4ef; --card:var(--white);
  --accent:#1f4e79; --accent-soft:#e8f0f8;
  --overdue:#c0271d; --overdue-soft:#fdecea;
  --soon:#b26a00;    --soon-soft:#fff4e0;
  --done:#12703c;    --done-soft:#e7f5ec;
  --draft:#5a5590;   --draft-soft:#eeedf8;
  --shadow:0 1px var(--measure-2) rgba(16,20,24,.05), 0 var(--measure-6) var(--measure-20) calc(0px - var(--measure-8)) rgba(16,20,24,.10);
  --shadow-hi:0 var(--measure-2) var(--measure-4) rgba(16,20,24,.06), 0 var(--measure-14) 34px calc(0px - var(--measure-10)) rgba(16,20,24,.16);
  --r:var(--measure-14); --r-sm:var(--measure-9);
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact;scroll-behavior:smooth}
body{
  direction:rtl;text-align:right;color:var(--ink);background:var(--bg);
  font-family:'Estedad','Vazirmatn',Tahoma,sans-serif;
  font-size:14.5px;line-height:1.9;font-weight:400;
  margin:0;padding:30px var(--measure-20) 72px;
  font-feature-settings:'ss01';
  text-rendering:optimizeLegibility;
}
.wrap{max-width:1120px;margin:0 auto}
.num{font-variant-numeric:tabular-nums;font-feature-settings:'tnum'}

/* ---------- header ---------- */
.top{display:flex;align-items:flex-start;gap:var(--measure-16);margin-bottom:26px}
.top .id{
  width:var(--icon-size-large);height:var(--icon-size-large);flex:0 0 var(--icon-size-large);border-radius:var(--measure-12);
  background:linear-gradient(145deg,var(--accent),#2f6da4);color:var(--white);
  display:flex;align-items:center;justify-content:center;
  font-size:19px;font-weight:800;letter-spacing:-.02em;
}
.top h1{font-size:23px;font-weight:800;margin:0;line-height:1.4;letter-spacing:-.01em}
.top .meta{color:var(--muted);font-size:12.5px;margin-top:3px}
.top .meta b{color:var(--ink-2);font-weight:600}

/* ---------- action panel: the point of the page ---------- */
.act{
  background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  box-shadow:var(--shadow);overflow:hidden;margin-bottom:var(--measure-22);
}
.act>header{
  display:flex;align-items:center;gap:var(--measure-12);padding:var(--measure-15) var(--measure-20);
  border-bottom:1px solid var(--line-2);background:#fcfbf9;
}
.act .icon{
  width:34px;height:34px;flex:0 0 34px;border-radius:var(--measure-10);display:flex;
  align-items:center;justify-content:center;font-size:var(--measure-17);font-weight:800;
}
.act.calm .icon{background:var(--accent-soft);color:var(--accent)}
.act.warn .icon{background:var(--soon-soft);color:var(--soon)}
.act.bad  .icon{background:var(--overdue-soft);color:var(--overdue)}
.act>header h2{font-size:16.5px;font-weight:800;margin:0;border:0;padding:0}
.act>header .n{margin-inline-start:auto;color:var(--muted);font-size:12.5px;font-weight:600}
.act ul{list-style:none;margin:0;padding:var(--measure-6) var(--measure-8)}
.act li{
  display:flex;align-items:center;gap:var(--measure-14);padding:var(--measure-11) var(--measure-12);border-radius:var(--measure-10);
  flex-wrap:wrap;
}
.act li+li{border-top:1px solid var(--line-2)}
.act li:hover{background:#fbfaf7}
.act .t{font-weight:650;flex:1;min-width:240px}
.act .t small{display:block;color:var(--muted);font-weight:400;font-size:var(--measure-12);margin-top:1px}
.act .when{
  font-weight:800;font-size:var(--measure-14);padding:var(--measure-4) var(--measure-11);border-radius:var(--radius-pill);white-space:nowrap;
}
.act .when.hot{background:var(--overdue);color:var(--white)}
.act .when.soon{background:var(--soon-soft);color:var(--soon)}
.act .when.calm{background:var(--accent-soft);color:var(--accent)}
.act .go{
  font-size:12.5px;font-weight:600;color:var(--accent);text-decoration:none;
  border:1px solid var(--line);border-radius:var(--measure-8);padding:var(--measure-5) var(--measure-11);white-space:nowrap;
  transition:background .12s,border-color .12s;
}
.act .go:hover{background:var(--accent-soft);border-color:#c3d7e8}
.act .empty{padding:var(--measure-20);color:var(--muted);font-size:13.5px}
.skip-link{position:absolute;inset-inline-start:-9999px;top:var(--measure-8);z-index:10;padding:var(--measure-8) var(--measure-12);background:var(--card);color:var(--ink);border:var(--measure-2) solid var(--accent);border-radius:var(--measure-8)}
.skip-link:focus{inset-inline-start:var(--measure-8)}
.late-deadline{display:block;color:var(--soon);font-size:var(--measure-11);margin-top:3px}

/* ---------- timeline ---------- */
.tl{
  background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  box-shadow:var(--shadow);padding:var(--measure-17) var(--measure-20) var(--measure-18);margin-bottom:var(--measure-22);
  overflow-x:auto;
}
.tl h2{font-size:14.5px;font-weight:800;margin:0 0 var(--measure-2);border:0;padding:0;color:var(--ink)}
.tl .sub{color:var(--muted);font-size:var(--measure-12);margin:0 0 var(--measure-14)}
.rail{position:relative;min-width:520px;min-height:158px;padding-top:var(--measure-8)}
.rail .line{
  position:absolute;inset-inline:0;top:var(--measure-14);height:3px;border-radius:var(--radius-pill);
  background:linear-gradient(to left,var(--accent-soft),var(--line));
}
.rail .tick{
  position:absolute;top:var(--measure-10);width:var(--measure-11);height:var(--measure-11);border-radius:50%;
  background:var(--card);border:3px solid var(--accent);
  transform:translateX(50%);margin-inline-start:calc(0px - var(--measure-5));
}
.rail .tick.late{border-color:var(--overdue);background:var(--overdue)}
.rail .mark{
  position:absolute;top:28px;transform:translateX(50%);margin-inline-start:-70px;
  width:140px;text-align:center;
}
.rail .mark b{
  display:block;font-size:var(--measure-11_5);font-weight:700;color:var(--ink-2);line-height:1.4;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
.rail .mark small{
  display:block;color:var(--muted);font-size:var(--measure-10_5);font-weight:400;line-height:1.5;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:var(--measure-2);
}
.rail .mark.late b{color:var(--overdue)}
.rail .more{
  display:block;font-style:normal;font-size:var(--measure-10_5);color:var(--faint);
  font-weight:600;margin-top:var(--measure-2);
}
.tl .none{color:var(--muted);font-size:var(--measure-13);padding:var(--measure-6) 0}

/* ---------- stats ---------- */
.tiles{display:flex;gap:var(--measure-13);flex-wrap:wrap;margin-bottom:26px}
.tile{
  flex:1 1 150px;background:var(--card);border:1px solid var(--line);
  border-radius:var(--r);padding:var(--measure-15) var(--measure-17);box-shadow:var(--shadow);
  display:flex;align-items:center;gap:var(--measure-14);
}
.tile .ring{flex:0 0 var(--icon-size-large)}
.tile .glyph{
  flex:0 0 var(--icon-size-large);width:var(--icon-size-large);height:var(--icon-size-large);border-radius:50%;display:flex;
  align-items:center;justify-content:center;font-size:19px;font-weight:800;
  background:#f4f1ea;
}
.tile .v{font-size:25px;font-weight:800;line-height:1.15;letter-spacing:-.02em}
.tile .l{font-size:var(--measure-12);color:var(--muted);font-weight:600}
.tile.bad .v{color:var(--overdue)} .tile.warn .v{color:var(--soon)}
.tile.good .v{color:var(--done)}

/* ---------- courses ---------- */
h2.sec{
  font-size:var(--measure-15);font-weight:800;color:var(--ink);margin:0 0 var(--measure-12);padding:0;
  border:0;display:flex;align-items:center;gap:var(--measure-9);
}
h2.sec .count{
  font-size:var(--measure-11_5);font-weight:700;color:var(--muted);background:var(--card);
  border:1px solid var(--line);border-radius:var(--radius-pill);padding:1px var(--measure-9);
}
.course{
  background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  box-shadow:var(--shadow);margin-bottom:var(--measure-11);overflow:hidden;
  transition:box-shadow .15s,border-color .15s;
}
.course[open]{box-shadow:var(--shadow-hi);border-color:#d8d2c6}
.course>summary{
  cursor:pointer;list-style:none;padding:var(--measure-15) var(--measure-18);display:flex;align-items:center;
  gap:var(--measure-18);
}
.course>summary::-webkit-details-marker{display:none}
.course>summary:hover{background:#fcfbf9}
.course>summary:focus-visible{outline:var(--measure-2) solid var(--accent);outline-offset:calc(0px - var(--measure-2))}
.cring{flex:0 0 44px}
.cmain{flex:1;min-width:0}
.cmain .n{font-weight:750;font-size:15.5px;line-height:1.5}
.cmain .t{color:var(--muted);font-size:var(--measure-12)}
.cmain .tags{display:flex;gap:var(--measure-6);flex-wrap:wrap;margin-top:var(--measure-6)}
.tag{
  font-size:var(--measure-11);font-weight:700;border-radius:var(--radius-pill);padding:1px var(--measure-9);
  background:var(--line-2);color:var(--ink-2);
}
.tag.bad{background:var(--overdue-soft);color:var(--overdue)}
.tag.soon{background:var(--soon-soft);color:var(--soon)}
.tag.ok{background:var(--done-soft);color:var(--done)}
.tag.q{background:var(--draft-soft);color:var(--draft)}
.cnum{color:var(--muted);font-size:var(--measure-12);font-weight:700;white-space:nowrap}
.cnext{
  font-size:var(--measure-12);font-weight:700;white-space:nowrap;padding:3px var(--measure-10);border-radius:var(--radius-pill);
  background:var(--line-2);color:var(--ink-2);
}
.cnext.hot{background:var(--overdue-soft);color:var(--overdue)}
.cnext.soon{background:var(--soon-soft);color:var(--soon)}
.chev{
  flex:0 0 auto;color:var(--faint);transition:transform .18s;margin-inline-start:var(--measure-2);
}
.course[open] .chev{transform:rotate(90deg)}
.work-item{
  background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  box-shadow:var(--shadow);padding:var(--measure-14) var(--measure-18);margin-bottom:var(--measure-10);
}
.work-item .n{font-weight:750;font-size:var(--measure-15)}
.work-item .meta{color:var(--muted);font-size:var(--measure-12);margin-top:var(--measure-4)}
.platform-panel{
  background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  box-shadow:var(--shadow);padding:var(--measure-15) var(--measure-18);margin-bottom:var(--measure-18);
}
.platform-item{
  border-top:1px solid var(--line-2);padding:var(--measure-10) var(--measure-2);
}
.platform-item .n{font-weight:750;font-size:var(--measure-14)}
.platform-item .meta{color:var(--muted);font-size:var(--measure-12);margin-top:3px;overflow-wrap:anywhere}
.platform-freshness{border-top:1px solid var(--line-2);margin-top:var(--measure-6);padding-top:var(--measure-5)}

/* ---------- assignment table ---------- */
.cbody{border-top:1px solid var(--line-2);background:#fdfcfa}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:right;padding:var(--measure-9) var(--measure-14);border-bottom:1px solid var(--line-2);
      vertical-align:top}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:#faf8f4}
th{color:var(--muted);font-weight:700;font-size:var(--measure-11_5);background:#f7f5f0;
   position:sticky;top:0}
.pill{
  display:inline-flex;align-items:center;gap:var(--measure-6);font-size:var(--measure-11_5);font-weight:700;
  border-radius:var(--radius-pill);padding:var(--measure-2) var(--measure-10);white-space:nowrap;
}
.pill::before{content:'';width:var(--measure-6);height:var(--measure-6);border-radius:50%;background:currentColor}
.p-overdue{background:var(--overdue-soft);color:var(--overdue)}
.p-closed{background:var(--overdue-soft);color:var(--overdue)}
.p-draft{background:var(--draft-soft);color:var(--draft)}
.p-open{background:var(--accent-soft);color:var(--accent)}
.p-submitted{background:var(--done-soft);color:var(--done)}
.p-graded{background:var(--done-soft);color:var(--done)}
.p-unknown{background:var(--line-2);color:var(--muted)}
.due{font-weight:700;white-space:nowrap}
.due.hot{color:var(--overdue)} .due.soon{color:var(--soon)}
.raw{color:var(--muted);font-size:var(--measure-11_5);display:block;font-weight:400}
.grade{font-weight:750}
.mats{font-size:var(--measure-11);color:var(--muted);margin-top:3px}
.mats b{
  display:inline-block;background:var(--line-2);border-radius:var(--measure-5);padding:0 var(--measure-6);
  margin:var(--measure-2) 0 0 var(--measure-4);font-weight:600;
}
.noteslink{font-size:var(--measure-11_5);color:var(--accent);text-decoration:none}

/* ---------- banners ---------- */
.note{
  border-radius:var(--r-sm);padding:var(--measure-12) var(--measure-16);margin:0 0 var(--measure-20);font-size:13.5px;
  border:1px solid var(--line);background:#fffdf5;color:var(--ink-2);
}
.note b{color:var(--ink)}
.note code{
  font-family:Consolas,monospace;font-size:var(--measure-12);background:#f1eee6;padding:1px var(--measure-5);
  border-radius:var(--measure-4);direction:ltr;display:inline-block;
}

.empty{
  text-align:center;padding:56px var(--measure-20);color:var(--muted);
  background:var(--card);border:1px dashed var(--line);border-radius:var(--r);
}
.empty .big{font-size:34px;margin-bottom:var(--measure-10)}
.empty code{
  font-family:Consolas,monospace;font-size:12.5px;background:var(--line-2);
  padding:var(--measure-2) var(--measure-8);border-radius:var(--measure-6);direction:ltr;display:inline-block;margin-top:var(--measure-8);
}
.foot{
  margin-top:34px;padding-top:var(--measure-14);border-top:1px solid var(--line);
  color:var(--faint);font-size:var(--measure-12);display:flex;gap:var(--measure-14);flex-wrap:wrap;
}
.foot code{font-family:Consolas,monospace;direction:ltr;display:inline-block}

@media (max-width:640px){
  body{padding:var(--measure-18) var(--measure-13) 50px;font-size:var(--measure-14)}
  .top h1{font-size:var(--measure-20)}
  .tile{flex:1 1 100%}
  .cnum,.cnext{display:none}
  .act .when{order:3}
}
@media print{
  body{background:var(--white);padding:0}
  .course{break-inside:avoid;box-shadow:none}
  .course[open] .cbody{display:block}
  .chev{display:none}
  .act li:hover,.course>summary:hover{background:none}
}
"""

REVISION_CSS = """
:root{
  --ink:#172526; --ink-2:#425455; --muted:#718282; --faint:#9aa8a7;
  --line:#dfe8e6; --line-2:#edf2f0; --bg:#f3f7f6; --card:var(--white);
  --accent:#12685b; --accent-soft:#e2f2ee; --overdue:#b33b32;
  --overdue-soft:#fbe9e7; --soon:#9a620b; --soon-soft:#fff2d9;
  --done:#24734e; --done-soft:#e7f4ec; --draft:#625b9a; --draft-soft:#efedfa;
  --shadow:0 1px var(--measure-2) rgba(16,46,43,.04),0 var(--measure-8) 24px calc(0px - var(--measure-13)) rgba(16,46,43,.22);
  --shadow-hi:0 var(--measure-10) 32px calc(0px - var(--measure-16)) rgba(16,46,43,.24); --r:var(--measure-18); --r-sm:var(--measure-11);
}
body{background:radial-gradient(ellipse at 88% 0,#e5f2ef 0,transparent 420px),var(--bg);padding-top:24px}
.wrap{max-width:1180px}
.top{align-items:center;gap:var(--measure-17);margin-bottom:var(--measure-14);padding:var(--measure-21) 24px;border:1px solid #d6e6e1;border-radius:var(--measure-22);background:linear-gradient(112deg,var(--white) 0%,#fafffe 58%,#e8f5f1 100%);box-shadow:var(--shadow)}
.top .id{width:54px;height:54px;flex-basis:54px;border-radius:var(--measure-17);background:linear-gradient(145deg,#0e6a5b,#3c9b86);font-size:var(--measure-21);box-shadow:0 var(--measure-8) var(--measure-18) calc(0px - var(--measure-8)) rgba(18,104,91,.6)}
.top h1{font-size:25px;letter-spacing:-.035em}.top .meta{font-size:var(--measure-12);margin-top:var(--measure-5)}
.eyebrow{margin:0 0 var(--measure-2);color:var(--accent);font-size:var(--measure-11);font-weight:800}
.section-nav{display:flex;gap:var(--measure-8);flex-wrap:wrap;margin:0 0 var(--measure-20)}
.section-nav a{color:var(--ink-2);text-decoration:none;font-size:var(--measure-12);font-weight:700;padding:var(--measure-7) var(--measure-12);border:1px solid var(--line);border-radius:var(--radius-pill);background:var(--white)}
.section-nav a:hover,.section-nav a:focus-visible{color:var(--accent);border-color:#a9cfc4;background:var(--accent-soft)}
.section-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:var(--measure-18);margin-bottom:var(--measure-14)}
.section-heading .sec{margin-bottom:3px}.section-description{color:var(--muted);font-size:var(--measure-12);margin:0}
.platform-panel,.work-panel{background:rgba(255,255,255,.94);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow);padding:var(--measure-21) var(--measure-22);margin:0 0 var(--measure-20)}
.assignment-search{flex:0 1 300px}.assignment-search input{width:100%;border:1px solid var(--line);border-radius:var(--measure-12);background:#f8fbfa;color:var(--ink);font:inherit;font-size:var(--measure-12);padding:var(--measure-9) var(--measure-12);outline:none}
.assignment-search input:focus{border-color:var(--focus-border);box-shadow:0 0 0 3px rgba(18,104,91,.1)}
.assignment-filters{display:flex;align-items:center;gap:var(--measure-7);flex-wrap:wrap;margin:var(--measure-14) 0 var(--measure-10)}
.assignment-filters button{color:var(--ink-2);background:#f6f9f8;border:1px solid var(--line);border-radius:var(--radius-pill);padding:var(--measure-6) var(--measure-11);font:inherit;font-size:var(--measure-11);font-weight:700;cursor:pointer;transition:.15s ease}
.assignment-filters button:hover{border-color:var(--accent-border-soft);color:var(--accent)}.assignment-filters button[aria-pressed=true]{background:var(--accent-strong);border-color:var(--accent-strong);color:var(--white)}
.filter-count{margin-inline-start:auto;color:var(--muted);font-size:var(--measure-11);font-weight:700}
.assignment-list{display:grid;gap:var(--measure-10)}.assignment-card{background:var(--white);border:1px solid var(--line);border-radius:var(--measure-15);overflow:hidden;transition:border-color .15s,box-shadow .15s,transform .15s}
.assignment-card:hover{border-color:#b5d6cc;box-shadow:var(--shadow-hi);transform:translateY(-1px)}.assignment-card[hidden]{display:none}
.assignment-head{display:grid;grid-template-columns:minmax(0,1fr) minmax(170px,230px);gap:var(--measure-15);padding:var(--measure-15) var(--measure-17) var(--measure-12)}
.assignment-title-group{min-width:0}.assignment-title-group h3{margin:var(--measure-5) 0 var(--measure-2);font-size:var(--measure-15);line-height:1.6;font-weight:800}
.assignment-title-group h3 a{color:var(--ink);text-decoration:none}.assignment-title-group h3 a:hover{color:var(--accent)}
.platform-badge{display:inline-flex;align-items:center;border-radius:var(--radius-pill);background:var(--accent-soft);color:var(--accent);font-size:var(--measure-10);font-weight:800;padding:var(--measure-2) var(--measure-9)}
.assignment-course{color:var(--muted);font-size:var(--measure-11_5);margin:0}
.deadline-box{display:grid;align-content:center;gap:var(--measure-2);padding:var(--measure-9) var(--measure-12);border-radius:var(--measure-12);background:#f5f8f7;border:1px solid var(--line-2);font-size:var(--measure-11);color:var(--muted)}
.assignment-date{font-size:var(--measure-12);font-weight:750;color:var(--ink-2)}.countdown{font-size:var(--measure-11);font-weight:800;color:var(--accent)}
.countdown.hot{color:var(--overdue)}.countdown.soon{color:var(--soon)}.no-deadline{font-size:var(--measure-11);color:var(--muted)}
.status-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--measure-9);padding:var(--measure-12) var(--measure-17);border-top:1px solid var(--line-2);border-bottom:1px solid var(--line-2);background:#fbfdfc}
.status-grid>div{display:grid;align-content:start;gap:var(--measure-4);min-width:0}.status-grid small{color:var(--muted);font-size:var(--measure-10);font-weight:650}
.state-pill,.work-pill{display:inline-flex;align-items:center;justify-self:start;max-width:100%;border-radius:var(--radius-pill);padding:3px var(--measure-9);font-size:var(--measure-10_5);font-weight:800;line-height:1.6}
.state-todo,.work-needs_completion{background:var(--soon-soft);color:var(--soon)}.state-done,.work-ready_for_student_review{background:var(--done-soft);color:var(--done)}
.state-overdue{background:var(--overdue-soft);color:var(--overdue)}.state-unknown,.work-not_started{background:#eef1f0;color:#596867}
.state-value{font-size:var(--measure-11);font-weight:700;color:var(--ink-2);overflow-wrap:anywhere}.work-ready_to_start{background:#eaf0fb;color:#435f9d}
.work-in_progress{background:#e6f1fb;color:#286692}.work-under_verification{background:var(--draft-soft);color:var(--draft)}
.assignment-note,.assignment-relation{margin:var(--measure-9) var(--measure-17) 0;color:#765a25;font-size:var(--measure-11)}.assignment-relation{color:var(--muted)}
.assignment-foot{display:flex;align-items:center;justify-content:space-between;gap:var(--measure-12);padding:var(--measure-10) var(--measure-17) var(--measure-13);color:var(--muted);font-size:var(--measure-10)}
.assignment-open{color:var(--accent);font-weight:800;text-decoration:none;font-size:var(--measure-11);white-space:nowrap}.assignment-open:hover{text-decoration:underline}
.no-matches{padding:26px var(--measure-12);text-align:center;color:var(--muted);font-size:var(--measure-12)}
.platform-classes{border-top:1px solid var(--line);margin-top:var(--measure-14);padding-top:var(--measure-12)}.platform-classes>summary{display:flex;gap:var(--measure-8);align-items:center;cursor:pointer;list-style:none;color:var(--ink-2);font-weight:750;font-size:var(--measure-12)}
.platform-classes>summary::-webkit-details-marker{display:none}.platform-classes>summary:after{content:'⌄';color:var(--muted);margin-inline-start:auto}.platform-classes[open]>summary:after{content:'⌃'}
.platform-class-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:var(--measure-8);margin-top:var(--measure-12)}
.platform-class{padding:var(--measure-10) var(--measure-12);border:1px solid var(--line-2);border-radius:var(--measure-12);background:#fbfdfc;color:var(--muted);font-size:var(--measure-10_5)}
.platform-class-name{color:var(--ink);font-weight:750;font-size:var(--measure-12);margin-bottom:var(--measure-2)}
.platform-freshness{display:flex;align-items:center;gap:var(--measure-10) var(--measure-16);flex-wrap:wrap;border-top:1px solid var(--line-2);margin-top:var(--measure-13);padding-top:var(--measure-12);font-size:var(--measure-10)}
.source-status{font-weight:800;color:var(--done)}.source-unavailable,.source-partial,.source-challenge_required,.source-needs_credentials{color:var(--soon)}.source-time{color:var(--muted)}
.work-panel .sec{margin-bottom:var(--measure-12)}.work-card{background:var(--white);border:1px solid var(--line);border-radius:var(--measure-14);padding:var(--measure-14) var(--measure-16);margin-top:var(--measure-9)}
.work-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--measure-12)}.work-card .n{font-size:var(--measure-14);font-weight:800}
.work-card .meta{color:var(--muted);font-size:var(--measure-11);margin-top:3px}.work-card .work-details{display:grid;gap:var(--measure-5);margin-top:var(--measure-10)}
.work-card .work-detail{font-size:var(--measure-11);color:var(--ink-2);margin:0;overflow-wrap:anywhere}.work-card a{color:var(--accent);text-decoration:none;font-weight:700}.work-card a:hover{text-decoration:underline}
.work-warning{color:var(--overdue)!important}.section-nav,.act,.tl,.tiles,.course,.work-panel,.platform-panel{scroll-margin-top:var(--measure-16)}
.visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:720px){
  body{padding:var(--measure-14) var(--measure-12) 42px}.top{padding:var(--measure-17) var(--measure-15);border-radius:var(--measure-17);align-items:flex-start}.top .id{width:44px;height:44px;flex-basis:44px;border-radius:var(--measure-14)}.top h1{font-size:var(--measure-20)}
  .section-heading{align-items:stretch;flex-direction:column;gap:var(--measure-10)}.assignment-search{flex-basis:auto}.platform-panel,.work-panel{padding:var(--measure-16) var(--measure-13);border-radius:var(--measure-15)}
  .assignment-head{grid-template-columns:1fr;gap:var(--measure-10);padding:var(--measure-13)}.deadline-box{grid-template-columns:auto 1fr auto;align-items:center}.status-grid{padding:var(--measure-11) var(--measure-13);gap:var(--measure-7)}
  .status-grid small{font-size:var(--measure-9)}.state-pill,.work-pill{font-size:9.5px;padding:3px var(--measure-7)}.assignment-foot{padding-inline:var(--measure-13)}
}
@media(max-width:440px){
  .top{gap:var(--measure-11)}.top .meta{font-size:var(--measure-10_5)}.status-grid{grid-template-columns:1fr 1fr}.status-grid>div:last-child{grid-column:1/-1}
  .filter-count{width:100%;margin:3px 0 0}.assignment-foot{align-items:flex-start;flex-direction:column}
}
@media print{
  body{background:var(--white)}.section-nav,.assignment-filters,.assignment-search,.assignment-open{display:none}
  .platform-panel,.work-panel,.assignment-card{box-shadow:none;break-inside:avoid}.platform-classes:not([open]) .platform-class-grid{display:grid}
}
"""

RESOURCE_CSS = """
.resource-page{max-width:1180px;margin:0 auto}
.resource-back{display:inline-flex;align-items:center;gap:var(--measure-7);margin:0 0 var(--measure-13);color:var(--accent);font-size:var(--measure-11);font-weight:800;text-decoration:none}
.resource-back:hover{text-decoration:underline}
.resource-hero{position:relative;display:grid;grid-template-columns:minmax(0,1fr) 210px;gap:24px;align-items:center;overflow:hidden;margin-bottom:var(--measure-16);padding:28px 30px;border:1px solid #cfe4dd;border-radius:24px;background:linear-gradient(110deg,var(--white) 0%,#f8fffc 55%,#dcefe9 100%);box-shadow:var(--shadow)}
.resource-hero:after{content:'';position:absolute;inset:auto -42px -128px auto;width:280px;height:280px;border:1px solid rgba(18,104,91,.12);border-radius:50%;box-shadow:0 0 0 28px rgba(18,104,91,.035),0 0 0 58px rgba(18,104,91,.025)}
.resource-hero-copy,.resource-hero-art{position:relative;z-index:1}
.resource-hero .eyebrow{font-size:var(--measure-11);letter-spacing:.02em}
.resource-hero h1{margin:var(--measure-4) 0 var(--measure-5);font-size:28px;line-height:1.4;font-weight:850;letter-spacing:-.04em}
.resource-hero p{max-width:680px;margin:0;color:var(--muted);font-size:12.5px}
.resource-hero .resource-howto{margin-top:var(--measure-15);padding:var(--measure-9) var(--measure-12);border:1px solid #dcebe6;border-radius:var(--measure-12);background:rgba(255,255,255,.72);color:var(--ink-2)}
.resource-hero .resource-howto b{color:var(--accent)}
.resource-hero-art{display:grid;place-items:center;height:150px;color:var(--accent)}
.resource-hero-art svg{width:170px;height:150px;overflow:visible}
.resource-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--measure-11);margin-bottom:var(--measure-18)}
.resource-stat{display:flex;align-items:center;gap:var(--measure-12);min-height:77px;padding:var(--measure-13) var(--measure-16);border:1px solid var(--line);border-radius:var(--measure-16);background:rgba(255,255,255,.9);box-shadow:var(--shadow)}
.resource-stat-icon{display:grid;place-items:center;width:39px;height:39px;flex:0 0 39px;border-radius:var(--measure-13);background:var(--accent-soft);color:var(--accent);font-size:var(--measure-16);font-weight:850}
.resource-stat strong{display:block;font-size:var(--measure-20);line-height:1.25;font-weight:850}
.resource-stat span:last-child{color:var(--muted);font-size:var(--measure-10_5);font-weight:650}
.resource-shelf{padding:var(--measure-21) var(--measure-22);border:1px solid var(--line);border-radius:var(--measure-20);background:rgba(255,255,255,.94);box-shadow:var(--shadow)}
.resource-shelf-head{display:flex;align-items:flex-end;justify-content:space-between;gap:var(--measure-16);margin-bottom:var(--measure-13)}
.resource-shelf-head h2{margin:0;font-size:var(--measure-17);font-weight:850}
.resource-shelf-head p{margin:var(--measure-2) 0 0;color:var(--muted);font-size:var(--measure-11)}
.resource-controls{display:grid;grid-template-columns:minmax(200px,300px) 1fr;gap:var(--measure-12);align-items:center;margin-bottom:var(--measure-14)}
.resource-search{position:relative}.resource-search:before{content:'⌕';position:absolute;right:var(--measure-12);top:3px;color:var(--muted);font-size:var(--measure-22)}
.resource-search input{width:100%;padding:var(--measure-9) 37px var(--measure-9) var(--measure-12);border:1px solid var(--line);border-radius:var(--measure-12);outline:none;background:#f8fbfa;color:var(--ink);font:inherit;font-size:var(--measure-11_5)}
.resource-search input:focus{border-color:var(--focus-border);box-shadow:0 0 0 3px rgba(18,104,91,.1)}
.resource-filters{display:flex;align-items:center;gap:var(--measure-6);flex-wrap:wrap}
.resource-filters button{padding:var(--measure-6) var(--measure-10);border:1px solid var(--line);border-radius:var(--radius-pill);background:#f8faf9;color:var(--ink-2);font:inherit;font-size:var(--measure-10_5);font-weight:750;cursor:pointer;transition:.15s ease}
.resource-filters button:hover{border-color:var(--accent-border-soft);color:var(--accent)}
.resource-filters button[aria-pressed=true]{border-color:var(--accent-strong);background:var(--accent-strong);color:var(--white)}
.resource-result-count{margin-inline-start:auto;color:var(--muted);font-size:var(--measure-10_5);font-weight:750;white-space:nowrap}
.resource-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,330px),1fr));gap:var(--measure-12)}
.resource-card{position:relative;display:flex;flex-direction:column;min-width:0;padding:var(--measure-16);border:1px solid var(--line);border-radius:var(--measure-16);background:linear-gradient(160deg,var(--white) 0%,var(--white) 66%,#f8fbfa 100%);transition:border-color .16s,box-shadow .16s,transform .16s}
.resource-card:hover{transform:translateY(calc(0px - var(--measure-2)));border-color:#b8d8ce;box-shadow:var(--shadow-hi)}
.resource-card[hidden]{display:none}
.resource-card-top{display:flex;align-items:center;gap:var(--measure-10);margin-bottom:var(--measure-12)}
.resource-mark{display:grid;place-items:center;width:43px;height:43px;flex:0 0 43px;border-radius:var(--measure-14);background:var(--accent-soft);color:var(--accent);font-size:var(--measure-10);font-weight:900;letter-spacing:.03em}
.resource-mark.web{background:#edf2fb;color:#4b6297}.resource-mark.video{background:#fff0e8;color:#a4552e}.resource-mark.folder{background:#fff5dd;color:#8a651d}
.resource-classification{min-width:0;flex:1}.resource-classification strong{display:block;color:var(--ink-2);font-size:var(--measure-10_5);font-weight:800}.resource-classification span{display:block;color:var(--muted);font-size:9.5px}
.resource-version{align-self:flex-start;padding:3px var(--measure-8);border:1px solid var(--line-2);border-radius:var(--radius-pill);background:#fbfdfc;color:var(--muted);font-size:9.5px;font-weight:750}
.resource-card h3{margin:0;color:var(--ink);font-size:var(--measure-15);line-height:1.65;font-weight:850;overflow-wrap:anywhere}
.resource-origin{margin:var(--measure-4) 0 var(--measure-12);color:var(--muted);font-size:var(--measure-10_5);overflow-wrap:anywhere}
.resource-binding-list{display:grid;gap:var(--measure-7);margin-top:auto;padding-top:var(--measure-11);border-top:1px solid var(--line-2)}
.resource-binding{display:flex;align-items:flex-start;gap:var(--measure-8);color:var(--ink-2);font-size:var(--measure-10_5);line-height:1.65}
.resource-binding-icon{color:var(--accent);font-weight:900}
.resource-binding b{font-weight:800}
.resource-binding small{display:block;color:var(--muted);font-size:9.5px}
.resource-card-foot{display:flex;align-items:center;justify-content:space-between;gap:var(--measure-10);flex-wrap:wrap;margin-top:var(--measure-12);padding-top:var(--measure-10);border-top:1px solid var(--line-2);color:var(--muted);font-size:9.5px}
.resource-card-foot a{display:inline-flex;align-items:center;gap:var(--measure-5);color:var(--accent);font-size:var(--measure-10_5);font-weight:850;text-decoration:none}
.resource-card-foot a:hover{text-decoration:underline}
.resource-empty{grid-column:1/-1;display:grid;justify-items:center;gap:var(--measure-5);min-height:190px;align-content:center;padding:24px;border:1px dashed #bed8d0;border-radius:var(--measure-16);background:linear-gradient(145deg,#fbfefd,#f3f9f6);text-align:center}
.resource-empty-icon{display:grid;place-items:center;width:48px;height:48px;margin-bottom:var(--measure-4);border-radius:var(--measure-16);background:var(--accent-soft);color:var(--accent);font-size:var(--measure-21)}
.resource-empty strong{font-size:var(--measure-14);font-weight:850}.resource-empty p{max-width:440px;margin:0;color:var(--muted);font-size:var(--measure-11)}
.resource-no-matches{padding:25px;text-align:center;color:var(--muted);font-size:var(--measure-11_5)}
.resource-footnote{display:flex;align-items:flex-start;gap:var(--measure-9);margin:var(--measure-12) var(--measure-2) 0;color:var(--muted);font-size:var(--measure-10)}
.resource-footnote b{color:var(--ink-2)}
.resource-course-panel{padding:0;border:0;background:transparent;box-shadow:none;margin:24px 0 26px;scroll-margin-top:var(--measure-18)}
.resource-course-panel-head{display:flex;align-items:center;justify-content:space-between;gap:var(--measure-20);margin-bottom:var(--measure-17);padding:0 var(--measure-2)}
.resource-course-panel-head .eyebrow{display:flex;align-items:center;gap:var(--measure-7);margin-bottom:var(--measure-5);font-size:var(--measure-10);letter-spacing:.06em}
.resource-course-panel-head .eyebrow:before{content:'';width:var(--measure-7);height:var(--measure-7);border-radius:50%;background:#2d927d;box-shadow:0 0 0 var(--measure-4) #dff1eb}
.resource-course-panel-head h2{margin:0;color:#172c2b;font-size:23px;line-height:1.35;font-weight:900;letter-spacing:-.035em}
.resource-course-panel-head p{margin:var(--measure-5) 0 0;color:#687a79;font-size:var(--measure-12)}
.resource-course-panel-actions{display:flex;align-items:center;gap:var(--measure-10);flex-wrap:wrap}
.resource-course-panel-actions .count{font-size:var(--measure-11);font-weight:750;color:#435956;padding:var(--measure-8) var(--measure-12);border:1px solid #dce8e4;border-radius:var(--measure-12);background:var(--white);box-shadow:0 var(--measure-4) var(--measure-15) calc(0px - var(--measure-12)) rgba(18,73,63,.4)}
.resource-course-panel-actions a{display:inline-flex;align-items:center;gap:var(--measure-8);padding:var(--measure-9) var(--measure-14);border:1px solid #175e53;border-radius:var(--measure-12);background:#175e53;color:var(--white);font-size:var(--measure-11);font-weight:850;text-decoration:none;white-space:nowrap;box-shadow:0 var(--measure-6) var(--measure-15) calc(0px - var(--measure-9)) rgba(18,104,91,.6);transition:transform .15s,background .15s}
.resource-course-panel-actions a:hover{transform:translateY(-1px);background:#104f46}
.resource-course-groups{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:var(--measure-15)}
.resource-course-group{position:relative;min-width:0;overflow:hidden;border:1px solid #dce8e4;border-radius:var(--measure-20);background:var(--white);box-shadow:0 var(--measure-8) 26px -19px rgba(22,64,58,.42);transition:border-color .18s,box-shadow .18s,transform .18s}
.resource-course-group:hover{transform:translateY(calc(0px - var(--measure-2)));border-color:#b8d6cd;box-shadow:0 var(--measure-15) 32px -23px rgba(22,64,58,.48)}
.resource-course-head{position:relative;display:flex;align-items:center;gap:var(--measure-13);padding:var(--measure-17) 19px;background:linear-gradient(105deg,#edf7f3 0%,#f7fbf9 65%,var(--white) 100%)}
.resource-course-head:after{content:'';position:absolute;inset-inline-start:0;top:0;bottom:0;width:3px;background:linear-gradient(#1d7667,#87c1b1)}
.resource-course-icon{display:grid;place-items:center;width:var(--icon-size-large);height:var(--icon-size-large);flex:0 0 var(--icon-size-large);border:1px solid #d4e8e1;border-radius:var(--measure-15);background:var(--white);color:var(--accent-strong);font-size:var(--measure-18);font-weight:900;box-shadow:0 var(--measure-4) var(--measure-10) calc(0px - var(--measure-7)) rgba(18,104,91,.45)}
.resource-course-name{min-width:0;flex:1}
.resource-course-name h3{margin:0;color:#1a302f;font-size:var(--measure-15);line-height:1.5;font-weight:900;overflow-wrap:anywhere}
.resource-course-name span{display:block;margin-top:3px;color:#6a7d7a;font-size:var(--measure-10_5)}
.resource-course-count{padding:var(--measure-6) var(--measure-10);border:1px solid #dce8e4;border-radius:var(--measure-10);background:rgba(255,255,255,.86);color:#46625c;font-size:var(--measure-10);font-weight:850;white-space:nowrap}
.resource-course-list{display:grid;padding:var(--measure-2) var(--measure-13) var(--measure-5)}
.resource-course-item{display:grid;grid-template-columns:44px minmax(0,1fr) auto;gap:var(--measure-12);align-items:center;min-width:0;padding:var(--measure-14) var(--measure-7);border:0;border-bottom:1px solid #edf2f0;border-radius:0;background:transparent}
.resource-course-item:last-child{border-bottom:0}
.resource-course-item .resource-mark{width:42px;height:42px;flex-basis:42px;border:1px solid #d9e9e3;border-radius:var(--measure-13);background:linear-gradient(145deg,#f6fbf9,#eaf5f1);font-size:var(--measure-9);box-shadow:inset 0 1px var(--white)}
.resource-course-item .resource-mark.web{border-color:#dce4f2;background:linear-gradient(145deg,#f8faff,#ebeff8)}
.resource-course-item .resource-mark.video{border-color:#f1dfd4;background:linear-gradient(145deg,#fff9f5,#fbeee5)}
.resource-course-item .resource-mark.folder{border-color:#eee4c8;background:linear-gradient(145deg,#fffdf6,#faf3df)}
.resource-course-item-main{min-width:0}
.resource-course-item-main h4{margin:0;color:#1c302e;font-size:var(--measure-13);line-height:1.6;font-weight:850;overflow-wrap:anywhere}
.resource-course-item-main p{margin:3px 0 0;color:#768681;font-size:var(--measure-10_5);line-height:1.55}
.resource-course-targets{display:flex;gap:var(--measure-6);flex-wrap:wrap;margin-top:var(--measure-8)}
.resource-course-target{display:inline-flex;align-items:center;gap:var(--measure-5);padding:var(--measure-4) var(--measure-8);border:1px solid #e5eeeb;border-radius:var(--measure-8);background:#f6faf8;color:#4c6560;font-size:var(--measure-10);line-height:1.5}
.resource-course-item>a{align-self:center;display:inline-flex;align-items:center;gap:var(--measure-5);padding:var(--measure-7) var(--measure-10);border:1px solid #dbe8e4;border-radius:var(--measure-10);background:var(--white);color:var(--accent-strong);font-size:var(--measure-10);font-weight:850;text-decoration:none;white-space:nowrap;transition:background .15s,border-color .15s}
.resource-course-item>a:after{content:'↗';font-size:var(--measure-11)}
.resource-course-item>a:hover{border-color:#b5d7cc;background:#f1faf6}
.resource-course-empty{display:grid;justify-items:center;gap:var(--measure-7);padding:30px var(--measure-18);border:1px dashed #b8d8cd;border-radius:var(--measure-18);background:linear-gradient(135deg,#f8fcfa,#eef7f3);text-align:center}
.resource-course-empty strong{color:#23453f;font-size:var(--measure-14);font-weight:850}
.resource-course-empty p{max-width:480px;margin:0;color:#657a74;font-size:var(--measure-11_5)}
.resource-section-nav{color:var(--accent)!important;border-color:#cce2da!important;background:#f6fcf9!important}
.resource-page .foot{margin-top:var(--measure-18)}
@media(max-width:720px){
 .resource-hero{grid-template-columns:minmax(0,1fr) 105px;gap:var(--measure-8);padding:var(--measure-21) var(--measure-18);border-radius:var(--measure-18)}
 .resource-hero h1{font-size:var(--measure-22)}.resource-hero-art{height:105px}.resource-hero-art svg{width:110px;height:100px}
 .resource-stats{gap:var(--measure-7)}.resource-stat{min-height:68px;padding:var(--measure-9);gap:var(--measure-8)}.resource-stat-icon{width:32px;height:32px;flex-basis:32px;border-radius:var(--measure-11);font-size:var(--measure-13)}.resource-stat strong{font-size:var(--measure-17)}.resource-stat span:last-child{font-size:var(--measure-9)}
 .resource-shelf{padding:var(--measure-16) var(--measure-13)}.resource-shelf-head{align-items:flex-start;flex-direction:column;gap:3px}.resource-controls{grid-template-columns:1fr;gap:var(--measure-8)}.resource-result-count{margin-inline-start:auto}
 .resource-course-panel{margin:19px 0 var(--measure-22)}.resource-course-panel-head{align-items:flex-start;flex-direction:column;gap:var(--measure-11)}.resource-course-panel-head h2{font-size:var(--measure-21)}.resource-course-panel-actions{width:100%;justify-content:space-between}
 .resource-course-group{border-radius:var(--measure-16)}.resource-course-head{padding:var(--measure-14)}.resource-course-item{grid-template-columns:40px minmax(0,1fr) auto;gap:var(--measure-9);padding:var(--measure-12) 3px}.resource-course-item .resource-mark{width:38px;height:38px;flex-basis:38px}
}
@media(max-width:440px){
 .resource-hero{grid-template-columns:1fr;padding:19px var(--measure-16)}.resource-hero-art{display:none}.resource-hero h1{font-size:var(--measure-21)}.resource-hero .resource-howto{font-size:var(--measure-10_5)}
 .resource-stats{grid-template-columns:1fr}.resource-stat{min-height:58px}.resource-filters{gap:var(--measure-5)}.resource-filters button{font-size:9.5px;padding:var(--measure-5) var(--measure-8)}
 .resource-card{padding:var(--measure-13)}.resource-course-item{grid-template-columns:38px minmax(0,1fr)}.resource-course-item>a{grid-column:2;justify-self:start;margin-top:1px}
}
@media print{.resource-back,.resource-controls,.resource-hero-art,.resource-card-foot a{display:none}.resource-card,.resource-stat{box-shadow:none;break-inside:avoid}}
"""

JS = """
function tick(){
  var now = Date.now()/1000;
  document.querySelectorAll('[data-due]').forEach(function(el){
    var due = parseInt(el.getAttribute('data-due'),10);
    if(!due){ el.textContent = '—'; return; }
    var d = due - now;
    var txt, cls = el.className.replace(/\\b(hot|soon)\\b/g,'').trim();
    if(d < 0){
      var od = Math.floor(-d/86400);
      txt = od>=1 ? ('گذشته '+od+' روز') : 'گذشته: کمتر از ۱ روز';
      cls = (cls+' hot').trim();
    } else {
      var dd = Math.floor(d/86400);
      txt = dd>=1 ? (dd+' روز مانده') : (Math.max(Math.floor(d/3600),0)+' ساعت مانده');
      if(dd<=3) cls = (cls+' soon').trim();
    }
    el.textContent = txt;
    el.className = cls;
  });
  var c = document.getElementById('clock');
  if(c){
    var n = new Date();
    function p(x){ return x<10 ? '0'+x : ''+x; }
    c.textContent = n.getFullYear()+'-'+p(n.getMonth()+1)+'-'+p(n.getDate())
                  + ' ' + p(n.getHours()) + ':' + p(n.getMinutes());
  }
}
document.addEventListener('DOMContentLoaded', tick);
setInterval(tick, 30000);

function formatLocalDates(){
  document.querySelectorAll('[data-local-date]').forEach(function(node){
    var raw = node.getAttribute('data-local-date');
    var date = new Date(raw);
    if(!raw || raw === 'نامشخص' || Number.isNaN(date.getTime())) return;
    try{
      var full = node.classList.contains('assignment-date');
      var formatter = new Intl.DateTimeFormat('fa-IR-u-ca-persian', {
        timeZone:'Asia/Tehran', dateStyle:full ? 'full' : 'medium', timeStyle:'short'
      });
      node.textContent = formatter.format(date);
    }catch(_){ node.textContent = raw; }
  });
}

function setupAssignmentFilters(){
  var cards = Array.prototype.slice.call(document.querySelectorAll('.assignment-card'));
  var buttons = Array.prototype.slice.call(document.querySelectorAll('[data-assignment-filter]'));
  var search = document.getElementById('assignment-search');
  var counter = document.getElementById('assignment-count');
  var empty = document.querySelector('.no-matches');
  var selected = 'all';
  function apply(){
    var query = search ? search.value.trim().toLocaleLowerCase('fa') : '';
    var now = Date.now()/1000;
    var shown = 0;
    cards.forEach(function(card){
      var haystack = (card.getAttribute('data-title')+' '+card.getAttribute('data-course')).toLocaleLowerCase('fa');
      var due = Number(card.getAttribute('data-due-epoch'));
      var state = card.getAttribute('data-submission');
      var pass = !query || haystack.indexOf(query) >= 0;
      if(selected === 'soon') pass = pass && Number.isFinite(due) && due <= now+7*86400 && due >= now-7*86400;
      if(selected === 'check') pass = pass && state === 'check';
      if(selected === 'submitted') pass = pass && state === 'submitted';
      card.hidden = !pass;
      if(pass) shown++;
    });
    if(counter) counter.textContent = new Intl.NumberFormat('fa-IR').format(shown)+' مورد';
    if(empty) empty.hidden = shown !== 0;
  }
  buttons.forEach(function(button){
    button.addEventListener('click', function(){
      selected = button.getAttribute('data-assignment-filter');
      buttons.forEach(function(other){ other.setAttribute('aria-pressed', other === button ? 'true' : 'false'); });
      apply();
    });
  });
  if(search) search.addEventListener('input', apply);
  apply();
}
document.addEventListener('DOMContentLoaded', function(){ formatLocalDates(); setupAssignmentFilters(); });
"""

# ---- helpers -------------------------------------------------------------

BUCKET_FA = {
    "overdue": "گذشته از مهلت", "closed": "مهلت بسته شده", "draft": "پیش‌نویس",
    "open": "باز — ارسال نشده", "submitted": "ارسال شده", "graded": "نمره داده شده",
    "unknown": "نامشخص — دستی چک شود",
}


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


def ring(pct: int, color: str, size: int = 44) -> str:
    """SVG donut. Inline so the file stays self-contained."""
    r = (size - 7) / 2
    c = 2 * 3.141592653589793 * r
    off = c * (1 - max(0, min(100, pct)) / 100)
    return (
        "<svg class='ring' width='{s}' height='{s}' viewBox='0 0 {s} {s}' "
        "role='img' aria-label='{p} درصد انجام‌شده'>"
        "<circle cx='{h}' cy='{h}' r='{r}' fill='none' stroke='#eae6dd' stroke-width='4'/>"
        "<circle cx='{h}' cy='{h}' r='{r}' fill='none' stroke='{col}' stroke-width='4' "
        "stroke-linecap='round' stroke-dasharray='{c:.2f}' "
        "stroke-dashoffset='{o:.2f}' transform='rotate(-90 {h} {h})'/>"
        "<text x='{h}' y='{h}' text-anchor='middle' dominant-baseline='central' "
        "font-size='{fs}' font-weight='700' fill='{col}'>{p}</text>"
        "</svg>"
    ).format(s=size, h=size / 2, r=r, c=c, o=off, col=color, p=pct, fs=size * 0.31)


def countdown(epoch: int | None) -> str:
    if not epoch:
        return "—"
    return '<span class="num" data-due="{}"></span>'.format(epoch)


def split_day(epoch: int | None) -> str:
    """A countdown for the collapsed course header: short, colour-coded, live."""
    if not epoch:
        return ""
    now = __import__("time").time()
    d = epoch - now
    if d < 0:
        return '<span class="cnext hot num" data-due="{}"></span>'.format(epoch)
    if d <= 3 * 86400:
        return '<span class="cnext soon num" data-due="{}"></span>'.format(epoch)
    return '<span class="cnext num" data-due="{}"></span>'.format(epoch)


def course_hue(cid: int) -> str:
    """A stable accent per course so the cards are distinguishable at a glance."""
    h = int(hashlib.sha256(str(cid).encode()).hexdigest()[:8], 16)
    return "hsl({} {}% 38%)".format(h % 360, 42 + (h >> 8) % 22)


# ---- timeline ------------------------------------------------------------


def timeline(items, now_epoch: int, horizon_days: int = 30) -> str:
    """Show outstanding due dates from today through the next horizon days.

    A table of dates does not tell you that three things are all due tomorrow.
    The rail does, instantly.

    Deadlines on the same day share one tick with their labels stacked beneath
    it. Drawing one tick per item instead - the first two attempts did that -
    piles every label on top of its neighbours exactly when several deadlines
    collide, which is the moment the rail matters most.
    """
    buckets: dict[int, list] = {}
    for a in items:
        if not a["due"]:
            continue
        offset = (a["due"] - now_epoch) / 86400
        if offset < 0 or offset > horizon_days:
            continue
        buckets.setdefault(round(offset), []).append(a)

    if not buckets:
        return (
            "<section class='tl'><h2>خط زمانی ۳۰ روز آینده</h2>"
            "<p class='sub'>مهلتی در این بازه پیدا نشد.</p></section>"
        )

    span = float(horizon_days)
    ticks: list[str] = []
    total = sum(len(v) for v in buckets.values())
    for offset_day in sorted(buckets):
        group = buckets[offset_day]
        offset = float(offset_day)
        pct = min(max(offset / span * 100, 0), 100)
        labels = "".join(
            "<b>{}</b><small>{}</small>".format(esc(a["name"][:28]), esc(a["course"][:18]))
            for a in group
        )
        more = (
            '<i class="more">+{} مورد دیگر</i>'.format(len(group) - 3)
            if len(group) > 3 else ""
        )
        ticks.append(
            "<div class='tick' style='right:{p:.3f}%' "
            "title='{t}'></div>"
            "<div class='mark' style='right:{p:.3f}%'>"
            "{labels}{more}</div>".format(
                p=pct,
                t=esc("{} مورد در {}".format(len(group), offset_day)),
                labels=labels,
                more=more,
            )
        )

    return (
        "<section class='tl'><h2>خط زمانی ۳۰ روز آینده</h2>"
        "<p class='sub'>{total} مورد مهلت‌دار در {days} روز · "
        "راست = امروز، به چپ = دورتر</p>"
        "<div class='rail'>{m}</div></section>"
    ).format(total=total, days=len(buckets), m="".join(ticks))


# ---- panels --------------------------------------------------------------


def action_panel(items: list[dict], now_epoch: int) -> str:
    if not items:
        return (
            "<section class='act calm'><header>"
            "<div class='icon'>·</div><h2>اقدام نزدیکی ثبت نشده</h2></header>"
            "<div class='empty'>برای موعدهای گذشته و ۱۴ روز آینده، موردی برای اقدام در فهرست نیست.</div>"
            "</section>"
        )

    urgent = [item for item in items if item["state"] == "todo" and item["regular_due"] is not None and item["regular_due"] < now_epoch]
    level = "bad" if urgent else "warn"
    icon = "!" if urgent else "◔"
    rows = []
    for a in items:
        due = a["due"]
        cls = "hot" if a["state"] == "todo" and a["regular_due"] is not None and a["regular_due"] < now_epoch and not (a["late_due"] and a["late_due"] >= now_epoch) else (
            "soon" if due is not None and due - now_epoch <= 3 * 86400 else "calm"
        )
        status_note = "نیازمند بررسی وضعیت تحویل" if a["state"] == "check" else (
            "مهلت عادی گذشته؛ مهلت اضافه هنوز باز است"
            if a["late_due"] and a["regular_due"] and a["regular_due"] < now_epoch <= a["late_due"]
            else ""
        )
        rows.append(
            "<li><div class='t'>{}<small>{}</small>{}</div>"
            "<div class='when {} num' {}></div>"
            "<a class='go' href='{}' target='_blank' rel='noreferrer'>باز کردن در سایت</a></li>".format(
                esc(a["name"]), esc(a["course"]),
                "<small>{}</small>".format(esc(status_note)) if status_note else "",
                cls, 'data-due="{}"'.format(due) if due else "", esc(a["url"]),
            )
        )

    return (
        "<section class='act {lv}'><header>"
        "<div class='icon'>{ic}</div><h2>اقدام‌های نزدیک و وضعیت‌های نیازمند بررسی</h2>"
        "<span class='n'>{n} مورد</span></header><ul>{rows}</ul></section>"
    ).format(lv=level, ic=icon, n=len(items), rows="".join(rows))


def tiles(items: list[dict], now_epoch: int) -> str:
    """Counts, not percentages.

    A ring reading "100" beside "کل تکالیف" is decoration pretending to be data.
    Only the one figure that is a genuine ratio - how much is finished - gets a
    ring; the rest get a glyph, because a ring around a raw count would be a lie.
    """
    total = len(items)
    done = sum(item["state"] == "submitted" for item in items)
    open_count = sum(item["state"] == "todo" for item in items)
    overdue = sum(item["state"] == "todo" and item["regular_due"] is not None and item["regular_due"] < now_epoch for item in items)
    needs_check = sum(item["state"] == "check" for item in items)
    pct_done = int(100 * done / total) if total else 0
    specs = [
        ("کل تکالیف", total, "▦", "var(--muted)", ""),
        ("ارسال‌نشده", open_count, "◔", "var(--soon)", "warn"),
        ("گذشته از مهلت", overdue, "!", "var(--overdue)", "bad" if overdue else ""),
        ("نیازمند بررسی وضعیت", needs_check, "?", "var(--draft)", ""),
        ("ارسال‌شده", done, None, "var(--done)", "good"),
    ]
    cells = []
    for label, value, glyph, color, cls in specs:
        visual = ring(pct_done, color, 46) if glyph is None else (
            "<span class='glyph' style='color:{c}'>{g}</span>".format(c=color, g=glyph)
        )
        cells.append(
            "<div class='tile {cls}'>{v}<div><div class='v num'>{n}</div>"
            "<div class='l'>{l}</div></div></div>".format(
                cls=cls, v=visual, n=value, l=label
            )
        )
    return "<div class='tiles'>{}</div>".format("".join(cells))


def course_card(c, materials: dict) -> str:
    items = sorted(
        c["items"],
        key=lambda a: (
            ["overdue", "closed", "draft", "open", "unknown", "submitted", "graded"].index(a.bucket),
            a.due or (1 << 62),
        ),
    )
    pct = int(100 * c["done"] / c["total"]) if c["total"] else 0
    accent = course_hue(c["course_id"])
    # Read the folder now, not from the store: a file dropped in an hour ago must
    # show up without needing a `store` refresh first.
    mats = materials.get(c["course_id"], [])

    tags = []
    if c["overdue"]:
        tags.append('<span class="tag bad">{} گذشته</span>'.format(c["overdue"]))
    if c["open"]:
        tags.append('<span class="tag soon">{} باز</span>'.format(c["open"]))
    if c["total"] and not c["open"]:
        tags.append('<span class="tag ok">همه انجام‌شده</span>')
    if not c["total"]:
        tags.append('<span class="tag">موردی پیدا نشد</span>')
    tag_html = "".join(tags)

    term = '<div class="t">{}</div>'.format(esc(c["term"])) if c.get("term") else ""

    if mats:
        counts: dict[str, int] = {}
        for m in mats:
            counts[m.kind] = counts.get(m.kind, 0) + 1
        chip = "".join(
            "<b>{} {}</b>".format("{:,}".format(n), k) for k, n in sorted(counts.items())
        )
        mat_html = '<div class="mats">منابع این درس: {}</div>'.format(chip)
    else:
        mat_html = (
            "<div class='mats'>هنوز منبعی برای این درس جمع نشده — "
            "<code>cwtrack material --course {}</code></div>".format(c["course_id"])
        )

    rows = []
    for a in items:
        mats_cell = ""
        if mats:
            names = [m.name.split("/")[-1] for m in mats]
            chips = "".join("<b>{}</b>".format(esc(n)) for n in names[:4])
            extra = " +{}".format(len(names) - 4) if len(names) > 4 else ""
            mats_cell = '<div class="mats">{}</div>'.format(chips + extra)
        rows.append(
            "<tr>"
            "<td><span class='pill p-{}'>{}</span></td>"
            "<td><span class='due'>{}</span>"
            "<span class='raw'>{}</span></td>"
            "<td>{}</td>"
            "<td><span class='grade'>{}</span></td>"
            "<td><a href='{}' target='_blank' rel='noreferrer'>باز کردن</a></td>"
            "</tr>".format(
                a.bucket if a.bucket in BUCKET_FA else "unknown",
                esc(BUCKET_FA.get(a.bucket, a.bucket)),
                countdown(a.due),
                esc(a.due_text or "—"),
                mats_cell,
                esc(a.grade if a.grade and a.grade != "-" else "—"),
                esc(a.url),
            )
        )

    return (
        "<details class='course'{opn}>"
        "<summary>"
        "{ring}"
        "<div class='cmain'><div class='n'>{name}</div>{term}"
        "<div class='tags'>{tags}</div></div>"
        "{next}"
        "<span class='cnum num'>{done} از {total}</span>"
        "<span class='chev'>›</span>"
        "</summary>"
        "<div class='cbody'>{mats}"
        "<table><thead><tr><th>وضعیت</th><th>باقی‌مانده</th><th>مهلت (متن سایت)</th>"
        "<th>نمره</th><th>لینک</th></tr></thead><tbody>{rows}</tbody></table>"
        "</div></details>"
    ).format(
        opn=" open" if c["open"] or c["overdue"] else "",
        ring=ring(pct, accent, 44),
        name=esc(c["course"]),
        term=term,
        tags=tag_html,
        next=split_day(c["soonest"][0] if c["soonest"] else None),
        done=c["done"],
        total=c["total"],
        mats=mat_html,
        rows="".join(rows),
    )


def order(items):
    return items


WORK_STAGE_FA = {
    "ready_to_start": "آمادهٔ شروع",
    "in_progress": "در حال انجام",
    "under_verification": "در حال بررسی",
    "needs_completion": "نیازمند تکمیل",
    "ready_for_student_review": "آمادهٔ بررسی دانشجو",
}

SUBMISSION_LABELS = {
    "not_submitted": ("ارسال نشده", "todo"),
    "not submitted": ("ارسال نشده", "todo"),
    "no submission": ("ارسال نشده", "todo"),
    "open": ("باز؛ منتظر ارسال", "todo"),
    "draft": ("پیش‌نویس", "todo"),
    "overdue": ("مهلت گذشته؛ ارسال نشده", "overdue"),
    "closed": ("مهلت بسته شده؛ وضعیت تحویل را بررسی کن", "overdue"),
    "submitted": ("ارسال شده", "done"),
    "submitted for grading": ("ارسال شده؛ در انتظار ارزیابی", "done"),
    "sent for grading": ("ارسال شده؛ در انتظار ارزیابی", "done"),
    "sent for marking": ("ارسال شده؛ در انتظار ارزیابی", "done"),
    "graded": ("ارزیابی شده", "done"),
    "accepted": ("پذیرفته شده", "done"),
    "rejected": ("نیازمند اصلاح", "todo"),
    "ارسال نشده": ("ارسال نشده", "todo"),
    "ارسال‌نشده": ("ارسال نشده", "todo"),
    "ارسال شده": ("ارسال شده", "done"),
    "ارسال‌شده": ("ارسال شده", "done"),
    "تحویل شده": ("ارسال شده", "done"),
    "تحویل‌شده": ("ارسال شده", "done"),
    "مهلت گذشته": ("مهلت گذشته؛ ارسال نشده", "overdue"),
}

EVALUATION_LABELS = {
    "graded": "ارزیابی شده",
    "pending": "در انتظار ارزیابی",
    "accepted": "پذیرفته شده",
    "rejected": "نیازمند اصلاح",
}


def _task_key(ref: dict) -> tuple:
    return tuple(
        ref.get(key)
        for key in ("connection_id", "class_id", "assignment_id", "question_id")
    )


def _due_epoch(value) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (ValueError, OverflowError, OSError):
        return None


def _legacy_platform_assignments(assignments: list, study: dict, refreshed: str) -> list[dict]:
    """Adapt the original CW store into the same read model as connected platforms."""
    connection_by_class = {
        str(item.get("ref", {}).get("class_id")): item.get("ref", {}).get("connection_id")
        for item in study.get("classes", [])
        if item.get("platform") == "cw"
    }
    known = {
        (str(item.get("class_ref", {}).get("class_id")), str(item.get("ref", {}).get("assignment_id")))
        for item in study.get("platform_assignments", [])
        if item.get("platform") == "cw"
    }
    rows = []
    for item in assignments:
        class_id, assignment_id = str(item.course_id), str(item.cmid)
        if (class_id, assignment_id) in known:
            continue
        connection_id = connection_by_class.get(class_id) or "cw-legacy"
        ref = {
            "connection_id": connection_id,
            "class_id": class_id,
            "assignment_id": assignment_id,
        }
        deadlines = []
        if item.due:
            try:
                deadline = datetime.fromtimestamp(item.due, timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                deadline = ""
            if deadline:
                deadlines.append({"kind": "regular", "at": deadline, "raw": item.due_text})
        rows.append({
            "kind": "assignment",
            "ref": ref,
            "class_ref": {key: ref[key] for key in ("connection_id", "class_id")},
            "title": item.name,
            "course_title": item.course,
            "url": item.url,
            "platform": "cw",
            "submission": {
                "state": item.status_text or "unknown",
                "raw": item.status_text or "",
            },
            "evaluation": {
                "state": "graded" if item.grade and item.grade != "-" else "unknown",
                "grade": item.grade or None,
            },
            "deadlines": deadlines,
            "last_success_at": refreshed or "",
            "legacy_course_id": item.course_id,
            "legacy_assignment_id": item.cmid,
        })
    return rows


def _submission_presentation(platform: str, submission: dict) -> tuple[str, str, str, str]:
    state = str(submission.get("state") or "unknown").strip()
    raw = str(submission.get("raw") or "").strip()
    canonical = state.casefold()
    if canonical in {"", "unknown", "none"} and raw:
        canonical = raw.casefold()
    known = SUBMISSION_LABELS.get(canonical)
    if known:
        filter_state = (
            "submitted" if known[1] == "done"
            else "check" if canonical == "closed"
            else "todo"
        )
        return known[0], known[1], filter_state, ""
    if canonical in {"", "unknown", "none", "-", "—"}:
        if platform == "quera":
            return (
                "وضعیت ارسال از کوئرا دریافت نمی‌شود",
                "unknown",
                "check",
                "برای اطمینان در کوئرا بررسی شود",
            )
        return (
            "وضعیت ارسال از سامانه دریافت نشده",
            "unknown",
            "check",
            "وضعیت تحویل را در خود سامانه بررسی کن",
        )
    # CW may expose a localized status added by the site. Keep that source text
    # visible rather than silently converting a new value into a known state.
    return raw or state, "unknown", "check", "این عبارت مستقیماً از سامانه آمده است"


def _dashboard_tasks(study: dict, now_epoch: int) -> list[dict]:
    """Build the one deduplicated assignment view used by dashboard summaries."""
    rows = []
    seen = set()
    for item in study.get("platform_assignments", []):
        ref = item.get("ref") or {}
        key = _task_key(ref)
        has_stable_key = (
            ref.get("connection_id") is not None
            and ref.get("class_id") is not None
            and (ref.get("assignment_id") is not None or ref.get("question_id") is not None)
        )
        if has_stable_key:
            if key in seen:
                continue
            seen.add(key)
        deadlines = item.get("deadlines", []) or []
        regular = next((d for d in deadlines if isinstance(d, dict) and d.get("kind") in {"regular", "normal"}), None)
        late = next((d for d in deadlines if isinstance(d, dict) and d.get("kind") == "late"), None)
        # Older records may only have one untyped deadline.
        if regular is None:
            regular = next((d for d in deadlines if isinstance(d, dict) and not d.get("kind")), None)
        regular_due = _due_epoch(regular.get("at")) if regular else None
        late_due = _due_epoch(late.get("at")) if late else None
        state = _submission_presentation(
            item.get("platform", ""), item.get("submission", {}) or {}
        )[2]
        due = late_due if late_due and (regular_due is None or regular_due < now_epoch < late_due) else regular_due
        rows.append({
            "name": str(item.get("title") or "تکلیف بدون عنوان"),
            "course": str(item.get("course_title") or "درس نامشخص"),
            "url": item.get("url") or "#",
            "state": state,
            "due": due,
            "regular_due": regular_due,
            "late_due": late_due,
        })
    return rows


def _action_items(tasks: list[dict], now_epoch: int, horizon_days: int = 14) -> list[dict]:
    horizon = now_epoch + horizon_days * 86400
    return [
        item for item in tasks
        if item["state"] in {"todo", "check"} and (
            item["due"] is None or item["due"] <= horizon
            or item["regular_due"] is not None and item["regular_due"] < now_epoch
        )
    ]


def work_panel(items: list[dict], resources: dict | None = None) -> str:
    """Render saved assignment work without interpreting site submission state."""
    resources = resources or {}
    cards = []
    for item in items:
        source = item.get("input", {})
        name = esc(source.get("title") or "تکلیف بدون عنوان")
        course = esc(source.get("course") or "")
        stage = WORK_STAGE_FA.get(item.get("stage"), "مرحله نامشخص")
        updated = esc(str(item.get("updated_at") or "").replace("T", " ")[:16])
        questions = item.get("open_questions", [])
        meta = " · ".join(part for part in (course, updated) if part)
        details = []
        if item.get("needs_reassessment"):
            details.append("<div class='meta'>ورودی تکلیف تغییر کرده و نیازمند بازبینی است.</div>")
        if questions:
            details.append(
                "<div class='meta'>منتظر پاسخ: {}</div>".format(
                    "، ".join(esc(question) for question in questions)
                )
            )
        delivery = item.get("delivery", {})
        delivered_files = delivery.get("files", [])
        if delivered_files:
            links = []
            for file in delivered_files:
                try:
                    href = Path(file["path"]).resolve().as_uri()
                except (KeyError, OSError, ValueError):
                    continue
                links.append(
                    "<a href='{}'>{}</a>".format(esc(href), esc(file.get("name", "فایل خروجی")))
                )
            if links:
                details.append("<div class='meta'>فایل‌ها: {}</div>".format(" · ".join(links)))
        for use in item.get("resource_uses", []):
            resource = resources.get(use.get("resource_id"), {})
            used_extent = _extent_text(use.get("used_extent", {}))
            parts = "، ".join(esc(part) for part in use.get("part_ids", []))
            purpose = esc(use.get("purpose", ""))
            details.append(
                "<div class='meta'>منبع استفاده‌شده: {} · محدودهٔ {} · بخش‌ها: {} · {}</div>"
                .format(
                    esc(resource.get("title") or "منبع نسخه‌دار"),
                    used_extent,
                    parts,
                    purpose,
                )
            )
        cards.append(
            "<article class='work-card' data-stage='{}'><div class='work-card-head'>"
            "<div><div class='n'>{}</div><div class='meta'>{}</div></div>"
            "<span class='work-pill work-{}'>{}</span></div>"
            "<div class='work-details'>{}</div></article>".format(
                esc(item.get("stage") or "unknown"), name, esc(meta),
                esc(item.get("stage") or "not_started"), esc(stage), "".join(details)
            )
        )
    if not items:
        return ""
    return (
        "<section class='work-panel' id='work-items'><h2 class='sec'>پیشرفت کار روی پاسخ "
        "<span class='count'>{} کار</span></h2>{}</section>"
    ).format(len(items), "".join(cards))


def platform_panel(study: dict, work_items: list[dict] | None = None) -> str:
    """Render site submission, evaluation and local answer progress as distinct states."""
    work_items = work_items or []
    classes = {
        (item.get("ref", {}).get("connection_id"), item.get("ref", {}).get("class_id")): item
        for item in study.get("classes", [])
    }
    relations_by_task = {}
    for relation in study.get("assignment_relations", []):
        for ref in relation.get("task_refs", []):
            relations_by_task.setdefault(_task_key(ref), []).append(relation)
    work_by_task = {
        _task_key(item.get("input", {}).get("assignment_ref", {})): item
        for item in work_items
        if isinstance(item.get("input", {}).get("assignment_ref"), dict)
    }
    work_by_site = {
        (str(item.get("input", {}).get("course_id")), str(item.get("input", {}).get("cmid"))): item
        for item in work_items
        if item.get("input", {}).get("source") == "site"
        and item.get("input", {}).get("course_id") is not None
        and item.get("input", {}).get("cmid") is not None
    }
    labels = {"cw": "شارپ", "quera": "کوئرا"}
    cards = []
    assignments = sorted(
        study.get("platform_assignments", []),
        key=lambda item: _due_epoch(next(iter(item.get("deadlines", [])), {}).get("at"))
        if item.get("deadlines") and isinstance(item["deadlines"][0], dict)
        and _due_epoch(item["deadlines"][0].get("at")) is not None
        else (1 << 62),
    )
    for assignment in assignments:
        class_ref = assignment.get("class_ref", {})
        class_item = classes.get((
            class_ref.get("connection_id"), class_ref.get("class_id")
        ), {})
        platform = assignment.get("platform", "")
        submission = assignment.get("submission", {}) or {}
        submission_label, submission_tone, submission_filter, submission_note = (
            _submission_presentation(platform, submission)
        )
        evaluation = assignment.get("evaluation", {}) or {}
        evaluation_state = str(evaluation.get("state") or "unknown").casefold()
        grade = str(evaluation.get("grade") or "").strip()
        evaluation_label = (
            "نمرهٔ {}".format(grade) if grade and grade != "-"
            else EVALUATION_LABELS.get(evaluation_state, "اطلاعات ارزیابی دریافت نشده")
        )
        deadlines = assignment.get("deadlines", [])
        deadline = next((d for d in deadlines if isinstance(d, dict) and d.get("kind") in {"regular", "normal"}), None)
        late_deadline = next((d for d in deadlines if isinstance(d, dict) and d.get("kind") == "late"), None)
        if deadline is None:
            deadline = next((d for d in deadlines if isinstance(d, dict) and not d.get("kind")), {})
        due = deadline.get("at") if isinstance(deadline, dict) else ""
        due_epoch = _due_epoch(due)
        freshness = assignment.get("last_success_at") or "نامشخص"
        relation_notes = [
            "تکلیف مرتبط؛ روند انجام مستقل: {}".format(
                relation.get("reason", "")
            )
            for relation in relations_by_task.get(_task_key(assignment.get("ref", {})), [])
        ]
        local_work = work_by_task.get(_task_key(assignment.get("ref", {})))
        if local_work is None and assignment.get("legacy_course_id") is not None:
            local_work = work_by_site.get((
                str(assignment["legacy_course_id"]),
                str(assignment.get("legacy_assignment_id")),
            ))
        work_stage = (
            WORK_STAGE_FA.get(local_work.get("stage"), "مرحله نامشخص")
            if local_work else "پروندهٔ انجام در این برنامه ثبت نشده"
        )
        work_tone = local_work.get("stage", "not_started") if local_work else "not_started"
        title = assignment.get("title") or "تکلیف بدون عنوان"
        course = class_item.get("title") or assignment.get("course_title") or "درس نامشخص"
        url = assignment.get("url") or "#"
        deadline_html = (
            "<time class='assignment-date' data-local-date='{}'>{}</time>"
            "<span class='countdown' data-due='{}'></span>".format(
                esc(due), esc(due), due_epoch
            ) if due_epoch is not None else "<span class='no-deadline'>مهلت در دریافت اخیر ثبت نشده</span>"
        )
        late_at = late_deadline.get("at") if late_deadline else ""
        late_epoch = _due_epoch(late_at)
        if late_epoch is not None:
            deadline_html += "<small class='late-deadline'>مهلت اضافه: <time data-local-date='{}'>{}</time></small>".format(
                esc(late_at), esc(late_at)
            )
        note_html = (
            "<p class='assignment-note'>{}</p>".format(esc(submission_note))
            if submission_note else ""
        )
        relation_html = "".join(
            "<p class='assignment-relation'>{}</p>".format(esc(note))
            for note in relation_notes
        )
        cards.append(
            "<article class='assignment-card' data-title='{}' data-course='{}' "
            "data-platform='{}' data-submission='{}' data-due-epoch='{}'>"
            "<div class='assignment-head'><div class='assignment-title-group'>"
            "<span class='platform-badge'>{}</span>"
            "<h3><a href='{}' target='_blank' rel='noreferrer'>{}</a></h3>"
            "<p class='assignment-course'>{}</p></div>"
            "<div class='deadline-box'><span>مهلت عادی</span>{}</div></div>"
            "<div class='status-grid'>"
            "<div><small>وضعیت تحویل</small><span class='state-pill state-{}'>{}</span></div>"
            "<div><small>نتیجهٔ ارزیابی</small><span class='state-value'>{}</span></div>"
            "<div><small>پیشرفت انجام</small><span class='work-pill work-{}'>{}</span></div>"
            "</div>{}{}"
            "<div class='assignment-foot'><span>آخرین دریافت: <time data-local-date='{}'>{}</time></span>"
            "<a class='assignment-open' href='{}' target='_blank' rel='noreferrer'>"
            "رفتن به تکلیف <span aria-hidden='true'>←</span></a></div></article>".format(
                esc(title), esc(course), esc(platform), submission_filter,
                due_epoch if due_epoch is not None else "",
                esc(labels.get(platform, platform or "سامانه")), esc(url), esc(title),
                esc(course), deadline_html, submission_tone, esc(submission_label),
                esc(evaluation_label), esc(work_tone), esc(work_stage), note_html,
                relation_html, esc(freshness), esc(freshness), esc(url),
            )
        )

    connection_cards = []
    for connection in study.get("connections", []):
        label = labels.get(connection.get("platform"), connection.get("platform", "سامانه"))
        status = connection.get("last_attempt_status") or "نامشخص"
        status_label = {
            "ok": "دریافت کامل",
            "partial": "دریافت ناقص",
            "unavailable": "سامانه در دسترس نبود",
            "challenge_required": "ورود یا تأیید لازم است",
            "needs_credentials": "اطلاعات ورود لازم است",
        }.get(status, status)
        latest = connection.get("last_attempt_at") or "نامشخص"
        success = connection.get("last_success_at") or "دریافت موفقی ثبت نشده"
        connection_cards.append(
            "<span class='source-status source-{}'>{} · {}</span>"
            "<span class='source-time'>آخرین تلاش: <time data-local-date='{}'>{}</time>"
            " · آخرین دریافت کامل: <time data-local-date='{}'>{}</time></span>".format(
                esc(status), esc(label), esc(status_label), esc(latest), esc(latest),
                esc(success), esc(success),
            )
        )
    class_cards = []
    tracking_labels = {"current": "جاری", "archived": "بایگانی‌شده", "unknown": "نیم‌سال نامشخص"}
    for item in study.get("classes", []):
        offering = item.get("offering") or {}
        tracking = item.get("tracking") or {}
        course = offering.get("title") or "درس پیوند داده نشده"
        term = offering.get("term") or tracking.get("term") or "ترم نامشخص"
        state = tracking_labels.get(tracking.get("state"), "نیم‌سال نامشخص")
        label = labels.get(item.get("platform"), item.get("platform", "سامانه"))
        class_cards.append(
            "<article class='platform-class'><div class='platform-class-name'>{}</div>"
            "<div>{} · {} · <span class='tracking-state'>{}</span></div></article>".format(
                esc(item.get("title") or "درس بدون عنوان"),
                esc(label), esc(course), esc("{} · {}".format(term, state)),
            )
        )
    if not cards and not connection_cards and not class_cards:
        return ""
    body = "".join(cards) or "<div class='empty'>در دریافت کامل اخیر تکلیفی دیده نشد.</div>"
    class_details = (
        "<details class='platform-classes'><summary>کلاس‌های متصل "
        "<span class='count'>{} کلاس</span></summary><div class='platform-class-grid'>{}</div></details>"
        .format(len(class_cards), "".join(class_cards))
        if class_cards else ""
    )
    return (
        "<section class='platform-panel' id='platform-tasks'>"
        "<div class='section-heading'><div><p class='eyebrow'>CW شریف و کوئرا</p>"
        "<h2 class='sec'>تکالیف سامانه‌ها <span class='count'>{} تکلیف</span></h2>"
        "<p class='section-description'>وضعیت تحویل، ارزیابی و پیشرفت پاسخ هرکدام جداگانه نمایش داده می‌شود.</p>"
        "</div><label class='assignment-search'><span class='visually-hidden'>جست‌وجوی تکلیف</span>"
        "<input id='assignment-search' type='search' placeholder='جست‌وجوی تکلیف یا درس' autocomplete='off'></label></div>"
        "<div class='assignment-filters' role='group' aria-label='فیلتر تکالیف'>"
        "<button type='button' data-assignment-filter='all' aria-pressed='true'>همه</button>"
        "<button type='button' data-assignment-filter='soon' aria-pressed='false'>مهلت نزدیک</button>"
        "<button type='button' data-assignment-filter='check' aria-pressed='false'>بررسی در سامانه</button>"
        "<button type='button' data-assignment-filter='submitted' aria-pressed='false'>ارسال‌شده‌ها</button>"
        "<span class='filter-count' id='assignment-count'>{} مورد</span></div>"
        "<div class='assignment-list'>{}</div><p class='no-matches' hidden>با این فیلتر تکلیفی پیدا نشد.</p>{}"
        "<div class='platform-freshness'>{}</div></section>"
    ).format(
        len(cards), len(cards), body, class_details, "".join(connection_cards)
    )


RESOURCE_KIND_LABELS = {
    "file": "فایل محلی",
    "remote_file": "فایل اینترنتی",
    "web": "صفحهٔ وب",
    "video": "ویدئو",
    "folder": "پوشه",
}
RESOURCE_PROVENANCE_LABELS = {
    "student": "افزوده‌شده توسط شما",
    "quera-course": "منبع درس در کوئرا",
    "manufacturer": "سازندهٔ قطعه",
}


def _resource_kind(resource: dict) -> tuple[str, str, str]:
    location = resource.get("location") or {}
    kind = location.get("kind", "unknown")
    family = kind
    if kind in {"file", "remote_file"}:
        filename = (
            Path(location.get("path", "")).name if kind == "file"
            else urlparse(location.get("url", "")).path.rsplit("/", 1)[-1]
        )
        extension = Path(filename).suffix.lstrip(".").upper()
        mark = extension[:5] or "FILE"
        family = "file"
    else:
        mark = {"web": "WEB", "video": "▶", "folder": "DIR"}.get(kind, "REF")
    return kind, family, mark


def _resource_location(resource: dict) -> tuple[str, str]:
    location = resource.get("location") or {}
    kind = location.get("kind")
    if kind == "file":
        path = Path(location.get("path", "")).expanduser()
        label = path.name or "فایل محلی"
        try:
            return label, path.resolve().as_uri()
        except (OSError, ValueError):
            return label, ""
    if kind == "folder":
        path = Path(location.get("path", "")).expanduser()
        return path.name or "پوشهٔ محلی", ""
    url = location.get("url")
    if isinstance(url, str):
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return parsed.netloc, url
    return "مسیر ثبت نشده", ""


def _resource_scope(extent: dict) -> str:
    if not isinstance(extent, dict) or not extent:
        return "کل منبع"
    parts = []
    for key, value in extent.items():
        if key == "pages":
            label = "صفحه‌های {}".format(value)
        elif key in {"section", "sections"}:
            label = "بخش {}".format(value)
        elif key in {"chapter", "chapters"}:
            label = "فصل {}".format(value)
        elif key in {"time", "time_range"}:
            label = "بازهٔ زمانی {}".format(value)
        elif key == "files":
            label = "فایل‌های انتخاب‌شده"
        else:
            label = "{}: {}".format(key, value)
        parts.append(esc(label))
    return "، ".join(parts)


def _resource_target_label(binding: dict, study: dict) -> str:
    target = binding.get("target") or {}
    offering_id = target.get("offering_id")
    if offering_id:
        offering = next(
            (item for item in study.get("offerings", []) if item.get("id") == offering_id),
            None,
        )
        return (offering or {}).get("title") or str(offering_id)

    task_ref = target.get("task_ref")
    if isinstance(task_ref, dict):
        task = next(
            (
                item for item in study.get("platform_assignments", [])
                if _task_key(item.get("ref", {})) == _task_key(task_ref)
            ),
            None,
        )
        course = next(
            (
                item for item in study.get("classes", [])
                if item.get("ref", {}).get("connection_id") == task_ref.get("connection_id")
                and item.get("ref", {}).get("class_id") == task_ref.get("class_id")
            ),
            None,
        )
        course_name = ""
        if course:
            course_name = (course.get("offering") or {}).get("title") or course.get("title", "")
        task_name = task.get("title", "") if task else ""
        if course_name and task_name:
            return "{} · {}".format(course_name, task_name)
        return task_name or course_name or "تکلیف انتخاب‌شده"
    return "درس یا تکلیف نامشخص"


def _resource_catalog(study: dict) -> list[dict]:
    resources = {
        item.get("id"): item for item in study.get("resources", []) if item.get("id")
    }
    grouped: dict[str, dict] = {}
    for binding in study.get("resource_bindings", []):
        if not binding.get("active", True):
            continue
        resource_id = binding.get("resource_id")
        resource = resources.get(resource_id)
        if not resource:
            continue
        entry = grouped.setdefault(
            resource_id, {"resource": resource, "bindings": [], "captures": []}
        )
        entry["bindings"].append(binding)

    for capture in study.get("resource_captures", []):
        if capture.get("resource_id") in grouped:
            grouped[capture["resource_id"]]["captures"].append(capture)
    return sorted(
        grouped.values(),
        key=lambda item: (item["resource"].get("title") or "").casefold(),
    )


def _resource_course_target(binding: dict, study: dict) -> tuple[tuple, str, str, str]:
    target = binding.get("target") or {}
    offering_id = target.get("offering_id")
    if offering_id:
        offering = next(
            (item for item in study.get("offerings", []) if item.get("id") == offering_id),
            None,
        )
        return (
            ("offering", offering_id),
            (offering or {}).get("title") or "درس بدون عنوان",
            (offering or {}).get("term", ""),
            "",
        )

    task_ref = target.get("task_ref")
    if isinstance(task_ref, dict):
        task = next(
            (
                item for item in study.get("platform_assignments", [])
                if _task_key(item.get("ref", {})) == _task_key(task_ref)
            ),
            None,
        )
        class_item = next(
            (
                item for item in study.get("classes", [])
                if item.get("ref", {}).get("connection_id") == task_ref.get("connection_id")
                and item.get("ref", {}).get("class_id") == task_ref.get("class_id")
            ),
            None,
        )
        offering = (class_item or {}).get("offering") or {}
        if not offering.get("id"):
            offering = next(
                (
                    item for item in study.get("offerings", [])
                    if any(
                        ref.get("connection_id") == task_ref.get("connection_id")
                        and ref.get("class_id") == task_ref.get("class_id")
                        for ref in item.get("class_refs", [])
                    )
                ),
                {},
            )
        tracking = (class_item or {}).get("tracking") or {}
        course_name = (
            offering.get("title") or (class_item or {}).get("title")
            or (task or {}).get("course_title") or "درس بدون عنوان"
        )
        term = offering.get("term") or tracking.get("term") or ""
        class_key = (
            task_ref.get("connection_id"), task_ref.get("class_id")
        )
        key = (
            ("offering", offering["id"])
            if offering.get("id") else ("class", *class_key)
        )
        task_name = (task or {}).get("title") or "تکلیف انتخاب‌شده"
        return key, course_name, term, task_name

    fallback = binding.get("id") or binding.get("resource_id") or "unknown"
    return ("unknown", fallback), "درس نامشخص", "", ""


def _resource_course_groups(study: dict) -> list[dict]:
    groups: dict[tuple, dict] = {}
    for entry in _resource_catalog(study):
        for binding in entry["bindings"]:
            key, course_name, term, _ = _resource_course_target(binding, study)
            group = groups.setdefault(
                key,
                {"title": course_name, "term": term, "resources": {}},
            )
            resource_id = entry["resource"].get("id")
            course_resource = group["resources"].setdefault(
                resource_id,
                {
                    "resource": entry["resource"],
                    "captures": entry["captures"],
                    "bindings": [],
                },
            )
            binding_id = binding.get("id")
            if all(item.get("id") != binding_id for item in course_resource["bindings"]):
                course_resource["bindings"].append(binding)

    result = []
    for group in groups.values():
        group["resources"] = sorted(
            group["resources"].values(),
            key=lambda item: (item["resource"].get("title") or "").casefold(),
        )
        result.append(group)
    return sorted(result, key=lambda item: item["title"].casefold())


def resource_panel(study: dict) -> str:
    """Group every active resource under the course it is attached to."""
    groups = _resource_course_groups(study)
    resource_count = len(_resource_catalog(study))
    group_html = []
    for group in groups:
        items = []
        for entry in group["resources"]:
            resource = entry["resource"]
            kind, family, mark = _resource_kind(resource)
            bindings = sorted(
                entry["bindings"],
                key=lambda item: _resource_course_target(item, study)[3].casefold(),
            )
            targets = []
            for binding in bindings:
                _, _, _, task_name = _resource_course_target(binding, study)
                target_label = (
                    "تکلیف: {}".format(task_name) if task_name else "کل درس"
                )
                targets.append(
                    "<span class='resource-course-target'>{} · {}</span>".format(
                        esc(target_label), _resource_scope(binding.get("extent") or {})
                    )
                )
            capture_count = len(entry["captures"])
            extra = "{} · نسخهٔ {} · {} نسخهٔ ذخیره‌شده".format(
                RESOURCE_KIND_LABELS.get(kind, "منبع"),
                resource.get("revision", 1), capture_count,
            )
            items.append(
                "<article class='resource-course-item'><span class='resource-mark {}'>{}</span>"
                "<div class='resource-course-item-main'><h4>{}</h4><p>{}</p>"
                "<div class='resource-course-targets'>{}</div></div>"
                "<a href='resources.html#resource-{}'>جزئیات</a></article>".format(
                    esc(family), esc(mark), esc(resource.get("title") or "منبع بدون عنوان"),
                    esc(extra), "".join(targets), esc(resource.get("id", "")),
                )
            )
        term = (
            "<span>{}</span>".format(esc(group["term"]))
            if group.get("term") else "<span>منابع متصل</span>"
        )
        group_html.append(
            "<section class='resource-course-group'><header class='resource-course-head'>"
            "<span class='resource-course-icon' aria-hidden='true'>▤</span>"
            "<div class='resource-course-name'><h3>{}</h3>{}</div>"
            "<span class='resource-course-count'>{} منبع</span></header>"
            "<div class='resource-course-list'>{}</div></section>".format(
                esc(group["title"]), term, len(group["resources"]), "".join(items)
            )
        )

    contents = (
        "<div class='resource-course-groups'>{}</div>".format("".join(group_html))
        if group_html else (
            "<div class='resource-course-empty'><strong>هنوز منبعی به درسی وصل نشده</strong>"
            "<p>فایل یا لینک را همراه نام درس بفرست تا پس از اتصال، اینجا زیر همان درس دیده شود.</p></div>"
        )
    )
    return (
        "<section class='platform-panel resource-course-panel' id='course-resources'>"
        "<div class='resource-course-panel-head'><div><p class='eyebrow'>کتابخانهٔ درس</p>"
        "<h2>منابع هر درس</h2><p>منابع به تفکیک درس، همراه با تکلیف و محدودهٔ مرتبط.</p></div>"
        "<div class='resource-course-panel-actions'><span class='count'>{} منبع · {} درس</span>"
        "<a href='resources.html'>کتابخانهٔ کامل <span aria-hidden='true'>←</span></a></div></div>"
        "{}</section>"
    ).format(resource_count, len(groups), contents)


def resource_library_page(study: dict, dashboard_name: str = "index.html") -> str:
    """Render a searchable, standalone view of active course resources."""
    entries = _resource_catalog(study)
    capture_count = sum(len(item["captures"]) for item in entries)
    target_count = len({
        repr(binding.get("target"))
        for item in entries for binding in item["bindings"]
    })
    cards = []
    for entry in entries:
        resource = entry["resource"]
        kind, family, mark = _resource_kind(resource)
        kind_label = RESOURCE_KIND_LABELS.get(kind, "منبع تکمیلی")
        provenance = RESOURCE_PROVENANCE_LABELS.get(
            resource.get("provenance"), "منبع تکمیلی"
        )
        origin, href = _resource_location(resource)
        bindings = sorted(
            entry["bindings"], key=lambda item: _resource_target_label(item, study).casefold()
        )
        binding_html = []
        for binding in bindings:
            binding_html.append(
                "<div class='resource-binding'><span class='resource-binding-icon' aria-hidden='true'>↳</span>"
                "<span><b>{}</b><small>{}</small></span></div>".format(
                    esc(_resource_target_label(binding, study)),
                    _resource_scope(binding.get("extent") or {}),
                )
            )
        captures = sorted(
            entry["captures"], key=lambda item: item.get("captured_at", ""), reverse=True
        )
        if captures:
            latest = captures[0]
            snapshot = (
                "<span>نسخهٔ ذخیره‌شده: {} مورد · آخرین ثبت: "
                "<time data-local-date='{}'>{}</time></span>".format(
                    len(captures), esc(latest.get("captured_at", "")),
                    esc(latest.get("captured_at", "")),
                )
            )
        else:
            snapshot = "<span>هنوز نسخه‌ای از محتوا ذخیره نشده</span>"
        open_link = (
            "<a href='{}' target='_blank' rel='noreferrer'>باز کردن منبع "
            "<span aria-hidden='true'>↗</span></a>".format(esc(href))
            if href else "<span>مرجع پوشه‌ای</span>"
        )
        search_text = " ".join([
            resource.get("title", ""), origin, kind_label, provenance,
            *[_resource_target_label(binding, study) for binding in bindings],
        ])
        cards.append(
            "<article id='resource-{}' class='resource-card' data-resource-kind='{}' data-resource-search='{}'>"
            "<div class='resource-card-top'><span class='resource-mark {}'>{}</span>"
            "<div class='resource-classification'><strong>{}</strong><span>{}</span></div>"
            "<span class='resource-version'>نسخهٔ {}</span></div>"
            "<h3>{}</h3><p class='resource-origin'>{}</p>"
            "<div class='resource-binding-list'>{}</div>"
            "<div class='resource-card-foot'>{}{}</div></article>".format(
                esc(resource.get("id", "")), esc(family), esc(search_text.lower()),
                esc(family), esc(mark),
                esc(kind_label), esc(provenance), esc(resource.get("revision", 1)),
                esc(resource.get("title") or "منبع بدون عنوان"), esc(origin),
                "".join(binding_html), snapshot, open_link,
            )
        )

    if cards:
        content = "".join(cards)
        controls = (
            "<div class='resource-controls'><label class='resource-search'>"
            "<span class='visually-hidden'>جست‌وجو در منابع</span>"
            "<input id='resource-search' data-resource-search type='search' "
            "placeholder='نام منبع، درس یا نوع فایل' autocomplete='off'></label>"
            "<div class='resource-filters' role='group' aria-label='فیلتر منابع'>"
            "<button type='button' data-resource-filter='all' aria-pressed='true'>همه</button>"
            "<button type='button' data-resource-filter='file' aria-pressed='false'>فایل‌ها</button>"
            "<button type='button' data-resource-filter='web' aria-pressed='false'>صفحه‌های وب</button>"
            "<button type='button' data-resource-filter='video' aria-pressed='false'>ویدئوها</button>"
            "<button type='button' data-resource-filter='folder' aria-pressed='false'>پوشه‌ها</button>"
            "<span class='resource-result-count' id='resource-count'>{} منبع</span></div></div>"
        ).format(len(entries))
        empty_match = "<p class='resource-no-matches' id='resource-no-matches' hidden>منبعی با این جست‌وجو پیدا نشد.</p>"
    else:
        content = (
            "<div class='resource-empty'><span class='resource-empty-icon' aria-hidden='true'>＋</span>"
            "<strong>هنوز منبعی به درس‌ها وصل نشده</strong>"
            "<p>لینک یا فایل منبع را در گفت‌وگو با Codex بفرست و نام دقیق درس یا تکلیف را هم بنویس؛ "
            "بعد از اتصال، اینجا با نوع و بخش‌های مرتبطش دیده می‌شود.</p></div>"
        )
        controls = ""
        empty_match = ""

    return (
        "<!doctype html><html lang='fa' dir='rtl'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>کتابخانهٔ منابع درسی</title>"
        "<style>{fonts}\n{css}\n{revision_css}\n{resource_css}</style></head><body>"
        "<main class='wrap resource-page'><a class='resource-back' href='{dashboard}'>"
        "<span aria-hidden='true'>→</span> بازگشت به داشبورد</a>"
        "<header class='resource-hero'><div class='resource-hero-copy'>"
        "<p class='eyebrow'>آرشیو شخصی نیم‌سال</p><h1>کتابخانهٔ منابع</h1>"
        "<p>همهٔ فایل‌ها، پیوندها و یادداشت‌های مرتبط با درس‌ها را یک‌جا ببین؛ "
        "بخش مرتبط با هر درس و نسخه‌های ثبت‌شده هم کنار آن مشخص است.</p>"
        "<p class='resource-howto'><b>منبع تازه داری؟</b> لینک یا فایل را در گفت‌وگو بفرست و نام درس را بنویس.</p>"
        "</div><div class='resource-hero-art' aria-hidden='true'><svg viewBox='0 0 180 150' fill='none'>"
        "<path d='M32 30c21-8 39-5 57 7v88c-18-12-36-15-57-7V30Z' fill='#fff' stroke='#8dbdaf' stroke-width='3'/>"
        "<path d='M146 30c-21-8-39-5-57 7v88c18-12 36-15 57-7V30Z' fill='#f4fbf8' stroke='#8dbdaf' stroke-width='3'/>"
        "<path d='M47 51c12-3 22-2 32 3M47 67c12-3 22-2 32 3M47 83c12-3 22-2 32 3M133 51c-12-3-22-2-32 3M133 67c-12-3-22-2-32 3M133 83c-12-3-22-2-32 3' stroke='#b7d6cd' stroke-width='3' stroke-linecap='round'/>"
        "<circle cx='143' cy='31' r='18' fill='#176d60'/><path d='M143 22v18M134 31h18' stroke='#fff' stroke-width='3' stroke-linecap='round'/>"
        "<circle cx='31' cy='111' r='7' fill='#d9a15d'/><circle cx='155' cy='116' r='5' fill='#93c6b7'/>"
        "</svg></div></header>"
        "<section class='resource-stats' aria-label='خلاصهٔ کتابخانه'>"
        "<article class='resource-stat'><span class='resource-stat-icon' aria-hidden='true'>▤</span>"
        "<div><strong>{resource_count}</strong><span>منبع فعال</span></div></article>"
        "<article class='resource-stat'><span class='resource-stat-icon' aria-hidden='true'>⌁</span>"
        "<div><strong>{target_count}</strong><span>اتصال به درس یا تکلیف</span></div></article>"
        "<article class='resource-stat'><span class='resource-stat-icon' aria-hidden='true'>✓</span>"
        "<div><strong>{capture_count}</strong><span>نسخهٔ ذخیره‌شده</span></div></article></section>"
        "<section class='resource-shelf' aria-labelledby='resource-shelf-title'>"
        "<div class='resource-shelf-head'><div><h2 id='resource-shelf-title'>منابع متصل</h2>"
        "<p>فقط منابعی نمایش داده می‌شوند که به یک درس یا تکلیف وصل شده‌اند.</p></div></div>"
        "{controls}<div class='resource-grid'>{content}</div>{empty_match}</section>"
        "<p class='resource-footnote'><span aria-hidden='true'>ⓘ</span><span><b>یادآوری:</b> "
        "ثبت نسخه یعنی نگه‌داری یک کپی برای کار؛ به معنی ثبت استفاده یا مطالعهٔ آن نیست.</span></p>"
        "<footer class='foot'><span>کتابخانهٔ منابع تکمیلی · اطلاعات از داده‌های محلی درس‌ها خوانده می‌شود</span></footer>"
        "</main><script>{js}</script></body></html>"
    ).format(
        fonts=font_css(), css=CSS, revision_css=REVISION_CSS, resource_css=RESOURCE_CSS,
        dashboard=esc(dashboard_name), resource_count=len(entries), target_count=target_count,
        capture_count=capture_count, controls=controls, content=content,
        empty_match=empty_match, js=JS + RESOURCE_JS,
    )


RESOURCE_JS = """
function setupResourceFilters(){
  var cards = Array.prototype.slice.call(document.querySelectorAll('.resource-card'));
  var buttons = Array.prototype.slice.call(document.querySelectorAll('[data-resource-filter]'));
  var search = document.getElementById('resource-search');
  var counter = document.getElementById('resource-count');
  var empty = document.getElementById('resource-no-matches');
  var selected = 'all';
  function apply(){
    var query = search ? search.value.trim().toLocaleLowerCase('fa') : '';
    var shown = 0;
    cards.forEach(function(card){
      var family = card.getAttribute('data-resource-kind');
      var haystack = (card.getAttribute('data-resource-search') || '').toLocaleLowerCase('fa');
      var pass = (!query || haystack.indexOf(query) >= 0)
        && (selected === 'all' || selected === family);
      card.hidden = !pass;
      if(pass) shown++;
    });
    if(counter) counter.textContent = new Intl.NumberFormat('fa-IR').format(shown)+' منبع';
    if(empty) empty.hidden = shown !== 0;
  }
  buttons.forEach(function(button){
    button.addEventListener('click', function(){
      selected = button.getAttribute('data-resource-filter');
      buttons.forEach(function(other){ other.setAttribute('aria-pressed', other === button ? 'true' : 'false'); });
      apply();
    });
  });
  if(search) search.addEventListener('input', apply);
  apply();
}
document.addEventListener('DOMContentLoaded', setupResourceFilters);
"""


# ---- page ----------------------------------------------------------------


def build(user: dict, assignments: list, gap: dict, now: datetime, now_epoch: int,
          materials: dict | None = None, work_items: list[dict] | None = None,
          has_course_data: bool = True, study_view: dict | None = None) -> str:
    materials = materials or {}
    work_items = work_items or []
    study_view = study_view or {}
    resource_titles = {item.get("id"): item for item in study_view.get("resources", [])}
    platform_assignments = study_view.get("platform_assignments", [])
    name = user.get("fullname") or ""
    dashboard_study = {
        **study_view,
        "platform_assignments": platform_assignments + _legacy_platform_assignments(
            assignments, study_view, user.get("refreshed", "")
        ),
    }
    dashboard_tasks = _dashboard_tasks(dashboard_study, now_epoch)
    task_actions = _action_items(dashboard_tasks, now_epoch)
    task_timeline = [
        item for item in dashboard_tasks
        if item["state"] != "submitted" and item["due"] is not None
        and now_epoch <= item["due"] <= now_epoch + 30 * 86400
    ]

    unknown = [a for a in assignments if a.bucket == "unknown"]

    banners = ""
    if has_course_data and unknown:
        banners += (
            "<div class='note'><b>{} مورد ناشناخته.</b> پارسر وضعیتشان را نفهمید و "
            "«انجام‌شده» حسابشان نکرده — عمداً. فایل‌های خام در "
            "<code>.cw/dump/</code> هستند؛ نگاه کن و اگر خواستی اصلاحشان کن.</div>".format(
                len(unknown)
            )
        )
    if has_course_data:
        banners += (
            "<div class='note'>درس‌هایی که «موردی پیدا نشد» دارند، در لحظهٔ آخرین بررسی "
            "تکلیفی نداشتند — نه اینکه ثابت شده باشد تا آخر ترم تکلیفی نخواهند داشت. "
            "هر چند هفته یک‌بار <code>cwtrack fetch</code> را دوباره اجرا کن.</div>"
        )
    else:
        banners += "<div class='note'>اطلاعات درس از سامانه در دسترس نیست</div>"

    if assignments:
        courses = "".join(course_card(c, materials) for c in gap["per_course"])
        body = (
            "{banners}"
            "{platforms}"
            "{resources}"
            "{work_panel}"
            "{actions}"
            "{timeline}"
            "{tiles}"
            "<h2 class='sec' id='course-list'>درس‌ها <span class='count'>{nc} درس</span></h2>"
            "{courses}"
        ).format(
            banners=banners,
            platforms=platform_panel(dashboard_study, work_items),
            resources=resource_panel(dashboard_study),
            work_panel=work_panel(work_items, resource_titles),
            actions=action_panel(task_actions, now_epoch),
            timeline=timeline(task_timeline, now_epoch),
            tiles=tiles(dashboard_tasks, now_epoch),
            nc=len(gap["per_course"]),
            courses=courses,
        )
    elif dashboard_tasks or study_view.get("classes") or study_view.get("connections"):
        body = (
            banners
            + action_panel(task_actions, now_epoch)
            + timeline(task_timeline, now_epoch)
            + tiles(dashboard_tasks, now_epoch)
            + platform_panel(dashboard_study, work_items)
            + resource_panel(dashboard_study)
            + work_panel(work_items, resource_titles)
        )
    else:
        body = banners + resource_panel(dashboard_study) + work_panel(work_items, resource_titles) + (
            "<div class='empty'><div class='big'>▤</div>"
            "<div>هنوز چیزی جمع نشده. اولین بار:</div>"
            "<code>cwtrack fetch</code></div>"
        )

    nav_items = []
    if platform_assignments or assignments or study_view.get("classes") or study_view.get("connections"):
        nav_items.append("<a href='#platform-tasks'>تکالیف سامانه‌ها</a>")
    if work_items:
        nav_items.append("<a href='#work-items'>پیشرفت پاسخ</a>")
    if assignments:
        nav_items.append("<a href='#course-list'>درس‌های شارپ</a>")
    nav_items.append(
        "<a class='resource-section-nav' href='#course-resources'>منابع هر درس</a>"
    )
    navigation = (
        "<nav class='section-nav' aria-label='پرش به بخش'>" + "".join(nav_items) + "</nav>"
        if nav_items else ""
    )

    return (
        "<!doctype html>\n<html lang='fa' dir='rtl'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>وضعیت تکالیف{who}</title>"
        "<style>{fonts}\n{css}\n{revision_css}\n{resource_css}</style></head><body><div class='wrap'>"
        "<a class='skip-link' href='#main-content'>رفتن به محتوای اصلی</a>"
        "<header class='top'><div class='id' aria-hidden='true'>CW</div><div>"
        "<p class='eyebrow'>مرکز پیگیری نیم‌سال</p><h1>وضعیت تکالیف</h1>"
        "<div class='meta'>{name} · <b>{username}</b> · آخرین دریافت فهرست CW {refreshed} "
        "· ساعت سایت <span id='clock' class='num'></span></div>"
        "</div></header>{navigation}"
        "<main id='main-content'>{body}</main>"
        "<footer class='foot'>ساخته‌شده با مهارت <code>sharif-cw</code>"
        "<span>· فقط خواندنی: هیچ چیزی به سایت ارسال نمی‌شود</span></footer>"
        "</div><script>{js}</script></body></html>"
    ).format(
        who=" — {}".format(esc(name)) if name else "",
        fonts=font_css(),
        css=CSS,
        revision_css=REVISION_CSS,
        resource_css=RESOURCE_CSS,
        name=esc(name) or "—",
        username=esc(user.get("username") or "—"),
        refreshed=esc(user.get("refreshed") or "—"),
        navigation=navigation,
        body=body,
        js=JS,
    )


def _extent_text(extent: dict) -> str:
    if not isinstance(extent, dict) or not extent:
        return "نامشخص"
    return "، ".join(
        "{} {}".format(esc(key), esc(value if isinstance(value, str) else str(value)))
        for key, value in extent.items()
    )
