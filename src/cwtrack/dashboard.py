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
from datetime import datetime
from pathlib import Path

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
  --ink:#101418; --ink-2:#3d4650; --muted:#77808b; --faint:#a4acb6;
  --line:#e7e3db; --line-2:#f0ede6; --bg:#f6f4ef; --card:#fff;
  --accent:#1f4e79; --accent-soft:#e8f0f8;
  --overdue:#c0271d; --overdue-soft:#fdecea;
  --soon:#b26a00;    --soon-soft:#fff4e0;
  --done:#12703c;    --done-soft:#e7f5ec;
  --draft:#5a5590;   --draft-soft:#eeedf8;
  --shadow:0 1px 2px rgba(16,20,24,.05), 0 6px 20px -8px rgba(16,20,24,.10);
  --shadow-hi:0 2px 4px rgba(16,20,24,.06), 0 14px 34px -10px rgba(16,20,24,.16);
  --r:14px; --r-sm:9px;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact;scroll-behavior:smooth}
body{
  direction:rtl;text-align:right;color:var(--ink);background:var(--bg);
  font-family:'Estedad','Vazirmatn',Tahoma,sans-serif;
  font-size:14.5px;line-height:1.9;font-weight:400;
  margin:0;padding:30px 20px 72px;
  font-feature-settings:'ss01';
  text-rendering:optimizeLegibility;
}
.wrap{max-width:1120px;margin:0 auto}
.num{font-variant-numeric:tabular-nums;font-feature-settings:'tnum'}

/* ---------- header ---------- */
.top{display:flex;align-items:flex-start;gap:16px;margin-bottom:26px}
.top .id{
  width:46px;height:46px;flex:0 0 46px;border-radius:12px;
  background:linear-gradient(145deg,var(--accent),#2f6da4);color:#fff;
  display:flex;align-items:center;justify-content:center;
  font-size:19px;font-weight:800;letter-spacing:-.02em;
}
.top h1{font-size:23px;font-weight:800;margin:0;line-height:1.4;letter-spacing:-.01em}
.top .meta{color:var(--muted);font-size:12.5px;margin-top:3px}
.top .meta b{color:var(--ink-2);font-weight:600}

/* ---------- action panel: the point of the page ---------- */
.act{
  background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  box-shadow:var(--shadow);overflow:hidden;margin-bottom:22px;
}
.act>header{
  display:flex;align-items:center;gap:12px;padding:15px 20px;
  border-bottom:1px solid var(--line-2);background:#fcfbf9;
}
.act .icon{
  width:34px;height:34px;flex:0 0 34px;border-radius:10px;display:flex;
  align-items:center;justify-content:center;font-size:17px;font-weight:800;
}
.act.calm .icon{background:var(--accent-soft);color:var(--accent)}
.act.warn .icon{background:var(--soon-soft);color:var(--soon)}
.act.bad  .icon{background:var(--overdue-soft);color:var(--overdue)}
.act>header h2{font-size:16.5px;font-weight:800;margin:0;border:0;padding:0}
.act>header .n{margin-inline-start:auto;color:var(--muted);font-size:12.5px;font-weight:600}
.act ul{list-style:none;margin:0;padding:6px 8px}
.act li{
  display:flex;align-items:center;gap:14px;padding:11px 12px;border-radius:10px;
  flex-wrap:wrap;
}
.act li+li{border-top:1px solid var(--line-2)}
.act li:hover{background:#fbfaf7}
.act .t{font-weight:650;flex:1;min-width:240px}
.act .t small{display:block;color:var(--muted);font-weight:400;font-size:12px;margin-top:1px}
.act .when{
  font-weight:800;font-size:14px;padding:4px 11px;border-radius:99px;white-space:nowrap;
}
.act .when.hot{background:var(--overdue);color:#fff}
.act .when.soon{background:var(--soon-soft);color:var(--soon)}
.act .when.calm{background:var(--accent-soft);color:var(--accent)}
.act .go{
  font-size:12.5px;font-weight:600;color:var(--accent);text-decoration:none;
  border:1px solid var(--line);border-radius:8px;padding:5px 11px;white-space:nowrap;
  transition:background .12s,border-color .12s;
}
.act .go:hover{background:var(--accent-soft);border-color:#c3d7e8}
.act .empty{padding:20px;color:var(--muted);font-size:13.5px}

/* ---------- timeline ---------- */
.tl{
  background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  box-shadow:var(--shadow);padding:17px 20px 18px;margin-bottom:22px;
  overflow-x:auto;
}
.tl h2{font-size:14.5px;font-weight:800;margin:0 0 2px;border:0;padding:0;color:var(--ink)}
.tl .sub{color:var(--muted);font-size:12px;margin:0 0 14px}
.rail{position:relative;min-width:520px;min-height:158px;padding-top:8px}
.rail .line{
  position:absolute;inset-inline:0;top:14px;height:3px;border-radius:99px;
  background:linear-gradient(to left,var(--accent-soft),var(--line));
}
.rail .tick{
  position:absolute;top:10px;width:11px;height:11px;border-radius:50%;
  background:var(--card);border:3px solid var(--accent);
  transform:translateX(50%);margin-inline-start:-5px;
}
.rail .tick.late{border-color:var(--overdue);background:var(--overdue)}
.rail .mark{
  position:absolute;top:28px;transform:translateX(50%);margin-inline-start:-70px;
  width:140px;text-align:center;
}
.rail .mark b{
  display:block;font-size:11.5px;font-weight:700;color:var(--ink-2);line-height:1.4;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
.rail .mark small{
  display:block;color:var(--muted);font-size:10.5px;font-weight:400;line-height:1.5;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:2px;
}
.rail .mark.late b{color:var(--overdue)}
.rail .more{
  display:block;font-style:normal;font-size:10.5px;color:var(--faint);
  font-weight:600;margin-top:2px;
}
.tl .none{color:var(--muted);font-size:13px;padding:6px 0}

/* ---------- stats ---------- */
.tiles{display:flex;gap:13px;flex-wrap:wrap;margin-bottom:26px}
.tile{
  flex:1 1 150px;background:var(--card);border:1px solid var(--line);
  border-radius:var(--r);padding:15px 17px;box-shadow:var(--shadow);
  display:flex;align-items:center;gap:14px;
}
.tile .ring{flex:0 0 46px}
.tile .glyph{
  flex:0 0 46px;width:46px;height:46px;border-radius:50%;display:flex;
  align-items:center;justify-content:center;font-size:19px;font-weight:800;
  background:#f4f1ea;
}
.tile .v{font-size:25px;font-weight:800;line-height:1.15;letter-spacing:-.02em}
.tile .l{font-size:12px;color:var(--muted);font-weight:600}
.tile.bad .v{color:var(--overdue)} .tile.warn .v{color:var(--soon)}
.tile.good .v{color:var(--done)}

/* ---------- courses ---------- */
h2.sec{
  font-size:15px;font-weight:800;color:var(--ink);margin:0 0 12px;padding:0;
  border:0;display:flex;align-items:center;gap:9px;
}
h2.sec .count{
  font-size:11.5px;font-weight:700;color:var(--muted);background:var(--card);
  border:1px solid var(--line);border-radius:99px;padding:1px 9px;
}
.course{
  background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  box-shadow:var(--shadow);margin-bottom:11px;overflow:hidden;
  transition:box-shadow .15s,border-color .15s;
}
.course[open]{box-shadow:var(--shadow-hi);border-color:#d8d2c6}
.course>summary{
  cursor:pointer;list-style:none;padding:15px 18px;display:flex;align-items:center;
  gap:18px;
}
.course>summary::-webkit-details-marker{display:none}
.course>summary:hover{background:#fcfbf9}
.course>summary:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.cring{flex:0 0 44px}
.cmain{flex:1;min-width:0}
.cmain .n{font-weight:750;font-size:15.5px;line-height:1.5}
.cmain .t{color:var(--muted);font-size:12px}
.cmain .tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.tag{
  font-size:11px;font-weight:700;border-radius:99px;padding:1px 9px;
  background:var(--line-2);color:var(--ink-2);
}
.tag.bad{background:var(--overdue-soft);color:var(--overdue)}
.tag.soon{background:var(--soon-soft);color:var(--soon)}
.tag.ok{background:var(--done-soft);color:var(--done)}
.tag.q{background:var(--draft-soft);color:var(--draft)}
.cnum{color:var(--muted);font-size:12px;font-weight:700;white-space:nowrap}
.cnext{
  font-size:12px;font-weight:700;white-space:nowrap;padding:3px 10px;border-radius:99px;
  background:var(--line-2);color:var(--ink-2);
}
.cnext.hot{background:var(--overdue-soft);color:var(--overdue)}
.cnext.soon{background:var(--soon-soft);color:var(--soon)}
.chev{
  flex:0 0 auto;color:var(--faint);transition:transform .18s;margin-inline-start:2px;
}
.course[open] .chev{transform:rotate(90deg)}

/* ---------- assignment table ---------- */
.cbody{border-top:1px solid var(--line-2);background:#fdfcfa}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:right;padding:9px 14px;border-bottom:1px solid var(--line-2);
      vertical-align:top}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:#faf8f4}
th{color:var(--muted);font-weight:700;font-size:11.5px;background:#f7f5f0;
   position:sticky;top:0}
.pill{
  display:inline-flex;align-items:center;gap:6px;font-size:11.5px;font-weight:700;
  border-radius:99px;padding:2px 10px;white-space:nowrap;
}
.pill::before{content:'';width:6px;height:6px;border-radius:50%;background:currentColor}
.p-overdue{background:var(--overdue-soft);color:var(--overdue)}
.p-closed{background:var(--overdue-soft);color:var(--overdue)}
.p-draft{background:var(--draft-soft);color:var(--draft)}
.p-open{background:var(--accent-soft);color:var(--accent)}
.p-submitted{background:var(--done-soft);color:var(--done)}
.p-graded{background:var(--done-soft);color:var(--done)}
.p-unknown{background:var(--line-2);color:var(--muted)}
.due{font-weight:700;white-space:nowrap}
.due.hot{color:var(--overdue)} .due.soon{color:var(--soon)}
.raw{color:var(--muted);font-size:11.5px;display:block;font-weight:400}
.grade{font-weight:750}
.mats{font-size:11px;color:var(--muted);margin-top:3px}
.mats b{
  display:inline-block;background:var(--line-2);border-radius:5px;padding:0 6px;
  margin:2px 0 0 4px;font-weight:600;
}
.noteslink{font-size:11.5px;color:var(--accent);text-decoration:none}

/* ---------- banners ---------- */
.note{
  border-radius:var(--r-sm);padding:12px 16px;margin:0 0 20px;font-size:13.5px;
  border:1px solid var(--line);background:#fffdf5;color:var(--ink-2);
}
.note b{color:var(--ink)}
.note code{
  font-family:Consolas,monospace;font-size:12px;background:#f1eee6;padding:1px 5px;
  border-radius:4px;direction:ltr;display:inline-block;
}

.empty{
  text-align:center;padding:56px 20px;color:var(--muted);
  background:var(--card);border:1px dashed var(--line);border-radius:var(--r);
}
.empty .big{font-size:34px;margin-bottom:10px}
.empty code{
  font-family:Consolas,monospace;font-size:12.5px;background:var(--line-2);
  padding:2px 8px;border-radius:6px;direction:ltr;display:inline-block;margin-top:8px;
}
.foot{
  margin-top:34px;padding-top:14px;border-top:1px solid var(--line);
  color:var(--faint);font-size:12px;display:flex;gap:14px;flex-wrap:wrap;
}
.foot code{font-family:Consolas,monospace;direction:ltr;display:inline-block}

@media (max-width:640px){
  body{padding:18px 13px 50px;font-size:14px}
  .top h1{font-size:20px}
  .tile{flex:1 1 100%}
  .cnum,.cnext{display:none}
  .act .when{order:3}
}
@media print{
  body{background:#fff;padding:0}
  .course{break-inside:avoid;box-shadow:none}
  .course[open] .cbody{display:block}
  .chev{display:none}
  .act li:hover,.course>summary:hover{background:none}
}
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
    """Upcoming deadlines on a rail. Late items clamp to the left edge.

    A table of dates does not tell you that three things are all due tomorrow.
    The rail does, instantly.

    Deadlines on the same day share one tick with their labels stacked beneath
    it. Drawing one tick per item instead - the first two attempts did that -
    piles every label on top of its neighbours exactly when several deadlines
    collide, which is the moment the rail matters most.
    """
    buckets: dict[int, list] = {}
    for a in items:
        if not a.due:
            continue
        offset = (a.due - now_epoch) / 86400
        if offset < -1 or offset > horizon_days:
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
        pct = 100 - (min(offset, 0.0) / span) * 100
        late = offset < 0
        labels = "".join(
            "<b>{}</b><small>{}</small>".format(esc(a.name[:28]), esc(a.course[:18]))
            for a in group
        )
        more = (
            '<i class="more">+{} مورد دیگر</i>'.format(len(group) - 3)
            if len(group) > 3 else ""
        )
        ticks.append(
            "<div class='tick{late}' style='right:{p:.3f}%' "
            "title='{t}'></div>"
            "<div class='mark{late}' style='right:{p:.3f}%'>"
            "{labels}{more}</div>".format(
                late=" late" if late else "",
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


def action_panel(gap) -> str:
    urgent, soon = gap["urgent"], gap["soon"]
    items = urgent + soon
    if not items:
        if gap["unscheduled"]:
            return (
                "<section class='act warn'><header>"
                "<div class='icon'>!</div><h2>کارهای نامشخص</h2></header>"
                "<div class='empty'>هیچ مهلت نزدیکی نیست، ولی این موارد ارسال‌نشده "
                "مانده‌اند و مهلتشان گذشته یا ندارند: "
                + "، ".join(esc(a.name) for a in gap["unscheduled"][:8]) +
                "</div></section>"
            )
        return (
            "<section class='act calm'><header>"
            "<div class='icon'>✓</div><h2>کاری باقی نمانده</h2></header>"
            "<div class='empty'>هیچ تکلیف باز یا سررسیدشده‌ای در فهرست نیست.</div>"
            "</section>"
        )

    level = "bad" if urgent else "warn"
    icon = "!" if urgent else "◔"
    rows = []
    for a in items:
        cls = "hot" if a.bucket in ("overdue", "closed") else (
            "soon" if (a.due and a.due - now_stamp()) <= 3 * 86400 else "calm"
        )
        rows.append(
            "<li><div class='t'>{}<small>{}</small></div>"
            "<div class='when {} num' {}></div>"
            "<a class='go' href='{}' target='_blank' rel='noreferrer'>باز کردن در سایت</a></li>".format(
                esc(a.name), esc(a.course), cls,
                'data-due="{}"'.format(a.due) if a.due else "",
                esc(a.url),
            )
        )

    return (
        "<section class='act {lv}'><header>"
        "<div class='icon'>{ic}</div><h2>الان چه کاری مانده</h2>"
        "<span class='n'>{n} مورد</span></header><ul>{rows}</ul></section>"
    ).format(lv=level, ic=icon, n=len(items), rows="".join(rows))


def now_stamp() -> float:
    import time

    return time.time()


def tiles(gap) -> str:
    """Counts, not percentages.

    A ring reading "100" beside "کل تکالیف" is decoration pretending to be data.
    Only the one figure that is a genuine ratio - how much is finished - gets a
    ring; the rest get a glyph, because a ring around a raw count would be a lie.
    """
    c = gap["counts"]
    pct_done = int(100 * c["done"] / c["total"]) if c["total"] else 0
    specs = [
        ("کل تکالیف", c["total"], "▦", "#77808b", ""),
        ("ارسال‌نشده", c["open"], "◔", "#b26a00", "warn"),
        ("گذشته از مهلت", c["urgent"], "!", "#c0271d", "bad" if c["urgent"] else ""),
        ("انجام‌شده", c["done"], None, "#12703c", "good"),
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


# ---- page ----------------------------------------------------------------


def build(user: dict, assignments: list, gap: dict, now: datetime, now_epoch: int,
          materials: dict | None = None) -> str:
    materials = materials or {}
    name = user.get("fullname") or ""
    initials = "".join(part[0] for part in name.split()[:2]) or "؟"

    unknown = [a for a in assignments if a.bucket == "unknown"]

    banners = ""
    if unknown:
        banners += (
            "<div class='note'><b>{} مورد ناشناخته.</b> پارسر وضعیتشان را نفهمید و "
            "«انجام‌شده» حسابشان نکرده — عمداً. فایل‌های خام در "
            "<code>.cw/dump/</code> هستند؛ نگاه کن و اگر خواستی اصلاحشان کن.</div>".format(
                len(unknown)
            )
        )
    banners += (
        "<div class='note'>درس‌هایی که «موردی پیدا نشد» دارند، در لحظهٔ آخرین بررسی "
        "تکلیفی نداشتند — نه اینکه ثابت شده باشد تا آخر ترم تکلیفی نخواهند داشت. "
        "هر چند هفته یک‌بار <code>cwtrack fetch</code> را دوباره اجرا کن.</div>"
    )

    if assignments:
        courses = "".join(course_card(c, materials) for c in gap["per_course"])
        body = (
            "{banners}"
            "{actions}"
            "{timeline}"
            "{tiles}"
            "<h2 class='sec'>درس‌ها <span class='count'>{nc} درس</span></h2>"
            "{courses}"
        ).format(
            banners=banners,
            actions=action_panel(gap),
            timeline=timeline(
                [a for a in assignments if a.bucket in ("overdue", "closed", "draft", "open")],
                now_epoch,
            ),
            tiles=tiles(gap),
            nc=len(gap["per_course"]),
            courses=courses,
        )
    else:
        body = (
            "<div class='empty'><div class='big'>▤</div>"
            "<div>هنوز چیزی جمع نشده. اولین بار:</div>"
            "<code>cwtrack fetch</code></div>"
        )

    return (
        "<!doctype html>\n<html lang='fa' dir='rtl'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>وضعیت تکالیف{who}</title>"
        "<style>{fonts}\n{css}</style></head><body><div class='wrap'>"
        "<header class='top'><div class='id'>{ini}</div><div>"
        "<h1>وضعیت تکالیف</h1>"
        "<div class='meta'>{name} · <b>{username}</b> · به‌روزرسانی {refreshed} "
        "· ساعت سایت <span id='clock' class='num'></span></div>"
        "</div></header>"
        "{body}"
        "<footer class='foot'>ساخته‌شده با مهارت <code>sharif-cw</code>"
        "<span>· فقط خواندنی: هیچ چیزی به سایت ارسال نمی‌شود</span></footer>"
        "</div><script>{js}</script></body></html>"
    ).format(
        who=" — {}".format(esc(name)) if name else "",
        fonts=font_css(),
        css=CSS,
        ini=esc(initials),
        name=esc(name) or "—",
        username=esc(user.get("username") or "—"),
        refreshed=esc(user.get("refreshed") or "—"),
        body=body,
        js=JS,
    )
