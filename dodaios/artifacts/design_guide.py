"""The design standard every artifact follows — the pattern, not the content.

One look for every page the assistant makes (a worker-written artifact, a
report, a living page, a rendered Markdown output): a **plain document**. One
reading column on a near-white ground, near-black text, one accent colour,
hairline boxes, and a fixed set of blocks that each carry statements — a
metric row, a table, a callout, numbered steps, a plus/minus pair, a chart, a
list of sources. The page is simple to look at and dense in what it says.

History, because the reasons still apply:

* 2026-08-23 — the first standard. Our archive of worker pages was textbook
  generated design (gradient headline over a centred hero, emoji chips, a
  Tailwind rainbow, no light theme, web fonts the sandbox can never load), so
  the worker got the tokens, a way to read the request, and the explicit list
  of what reads as generated. Those three stay.
* 2026-09-29 — an editorial kit (eyebrow, claim headline, mono labels, hairline
  section heads, colophon with the mark).
* 2026-11-13 — the maintainer asked for pages that are "really simple to look
  at, but with many statements", and for interactive infographics to stay part
  of them. The editorial furniture went: no eyebrow, no mono labels, no
  section marks, no colophon, no brand mark on the page (the app that frames
  it is the brand). What a page has instead is the block kit below and a small
  script that makes the blocks interactive (hover values, switchable views,
  sortable tables, a contents box that follows the reader).

The categorical series colours were validated with the data-visualisation
method's own checker on both page grounds (lightness band, chroma floor, CVD
separation, normal-vision floor, contrast) —
``#2A6FD0,#D4532E,#158F6B,#A86B00,#5B46C2,#C23F86`` on ``#FDFDFC`` and
``#4F8EF7,#E0633F,#1F9E7F,#C98500,#9085E9,#C84E8A`` on ``#141413``, all checks
passing; keep them in this order and re-validate before changing one (amber
directly beside the orange fails).

Pure text; no I/O. ``brief.py`` assembles it into the mission prompt;
``report.py``, ``living.py`` and ``ui/web/artifact_view.py`` lay their pages
out with the same tokens and kit.
"""

from __future__ import annotations

from typing import Final

# --- The tokens and the block kit, as one stylesheet --------------------------
#
# Light is the base, because a page is a document: it is read, printed and
# saved as a PDF on white. Dark follows the OS preference OR an explicit
# stamp: the Artifacts stage passes the app's current theme as
# `?theme=light|dark`, and the bootstrap script below stamps `data-theme` from
# it — so the page follows the app, not the OS, whenever the app says which it
# is. Every colour is a token defined in ALL THREE scopes; nothing is defined
# only inside a media block (the classic unreadable-artifact bug). Both dark
# scopes are `screen` only, so print always gets the light base.
THEME_CSS: Final = """\
:root{color-scheme:light;
  --bg:#FDFDFC;--bg-2:#F4F4F2;--bg-3:#EAEAE7;
  --ink:#171717;--ink-2:#62625E;--ink-3:#8F8F8A;
  --line:#E6E6E2;--line-2:#D4D4CF;
  --accent:#2A6FD0;--accent-ink:#FFFFFF;--accent-soft:#E8F0FC;
  --info:#1D4F9A;--info-soft:#E8F0FC;
  --good:#17703F;--good-soft:#E4F4EA;
  --warn:#8A5200;--warn-soft:#FCF1DE;
  --bad:#B3352A;--bad-soft:#FBEAE8;
  --sunken:#F4F4F2;
  --s1:#2A6FD0;--s2:#D4532E;--s3:#158F6B;--s4:#A86B00;--s5:#5B46C2;--s6:#C23F86;
  --seq-1:#DCE8FA;--seq-2:#A9C6F2;--seq-3:#6FA0E6;--seq-4:#2A6FD0;--seq-5:#1D4F9A;
  --radius:12px;--radius-sm:6px;
  --font:"Inter",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,
    sans-serif;
  --mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace}
@media screen and (prefers-color-scheme:dark){
:root:not([data-theme="light"]){color-scheme:dark;
  --bg:#141413;--bg-2:#1E1E1D;--bg-3:#292927;
  --ink:#F3F3F0;--ink-2:#A6A6A1;--ink-3:#787873;
  --line:#2B2B29;--line-2:#3C3C39;
  --accent:#4F8EF7;--accent-ink:#141413;--accent-soft:#17263F;
  --info:#A9C8FF;--info-soft:#17263F;
  --good:#6FD39A;--good-soft:#14291D;
  --warn:#F0B955;--warn-soft:#2E2311;
  --bad:#F28B82;--bad-soft:#331917;
  --sunken:#1E1E1D;
  --s1:#4F8EF7;--s2:#E0633F;--s3:#1F9E7F;--s4:#C98500;--s5:#9085E9;--s6:#C84E8A;
  --seq-1:#1D3257;--seq-2:#2A4B85;--seq-3:#3A6BC0;--seq-4:#4F8EF7;--seq-5:#A9C8FF}}
@media screen{
:root[data-theme="dark"]{color-scheme:dark;
  --bg:#141413;--bg-2:#1E1E1D;--bg-3:#292927;
  --ink:#F3F3F0;--ink-2:#A6A6A1;--ink-3:#787873;
  --line:#2B2B29;--line-2:#3C3C39;
  --accent:#4F8EF7;--accent-ink:#141413;--accent-soft:#17263F;
  --info:#A9C8FF;--info-soft:#17263F;
  --good:#6FD39A;--good-soft:#14291D;
  --warn:#F0B955;--warn-soft:#2E2311;
  --bad:#F28B82;--bad-soft:#331917;
  --sunken:#1E1E1D;
  --s1:#4F8EF7;--s2:#E0633F;--s3:#1F9E7F;--s4:#C98500;--s5:#9085E9;--s6:#C84E8A;
  --seq-1:#1D3257;--seq-2:#2A4B85;--seq-3:#3A6BC0;--seq-4:#4F8EF7;--seq-5:#A9C8FF}}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 var(--font);
  -webkit-font-smoothing:antialiased;overflow-wrap:break-word}
h1,h2,h3,p,ul,ol,dl,dd,figure,pre,blockquote{margin:0}
h1{font-size:30px;line-height:1.2;font-weight:600;letter-spacing:-.015em;text-wrap:balance}
h2{font-size:22px;line-height:1.3;font-weight:600;letter-spacing:-.01em;text-wrap:balance}
h3{font-size:16px;line-height:1.5;font-weight:600}
a{color:var(--accent);text-decoration:underline;text-decoration-thickness:1px;
  text-underline-offset:3px}
strong,b{font-weight:600}
code,pre,.mono{font-family:var(--mono);font-size:.875em}
pre{background:var(--bg-2);border-radius:8px;padding:12px 14px;overflow-x:auto;line-height:1.5}
:not(pre)>code{background:var(--bg-2);padding:1px 5px;border-radius:4px}
hr{border:0;border-top:1px solid var(--line);margin:32px 0}
.muted{color:var(--ink-2)}
.num{font-variant-numeric:tabular-nums}
.t-good{color:var(--good);font-weight:500}.t-warn{color:var(--warn);font-weight:500}
.t-bad{color:var(--bad);font-weight:500}
/* --- The kit: the blocks a page is made of. Use these classes; do not
   rebuild parallel ones. --- */
.page{max-width:748px;margin:0 auto;padding:56px 24px 96px}
.page.wide{max-width:1088px}
.page>h1+*{margin-top:20px}
.summary+.summary{margin-top:12px}
.toc{display:flex;flex-direction:column;gap:2px;margin-top:32px;padding:12px 16px;
  border:1px solid var(--line-2);border-radius:var(--radius)}
.toc-label{margin-bottom:4px;font-size:12px;line-height:16px;font-weight:500;color:var(--ink-2)}
.toc a{display:block;margin:0 -6px;padding:2px 6px;border-radius:var(--radius-sm);
  font-size:14px;line-height:20px;color:var(--ink-2);text-decoration:none;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.toc a:hover{background:var(--bg-2);color:var(--ink)}
.toc a.is-current{color:var(--ink);font-weight:500}
.section{margin-top:64px;scroll-margin-top:24px}
.section>*+*{margin-top:20px}
.section>h2+*{margin-top:12px}
.section>h2+.caption{margin-top:4px}
.section>p+p{margin-top:12px}
.section>*+h3{margin-top:32px}
.section>h3+*{margin-top:8px}
.section>*+.note{margin-top:8px}
.caption,.note{font-size:14px;line-height:20px;color:var(--ink-2)}
.page ul:not([class]),.page ol:not([class]){display:grid;gap:8px;padding-left:24px}
.page ol:not([class])>li::marker{color:var(--ink-2);font-variant-numeric:tabular-nums}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:24px 32px}
.metric .value{font-size:24px;line-height:1.25;font-weight:600;letter-spacing:-.01em;
  font-variant-numeric:tabular-nums}
.metric .label{margin-top:6px;font-size:14px;line-height:20px}
.metric .detail{font-size:14px;line-height:20px;color:var(--ink-2)}
.metric .up{color:var(--good)}.metric .down{color:var(--bad)}
.callout{position:relative;padding:14px 18px 14px 46px;border-radius:var(--radius);
  background:var(--bg-2)}
.callout::before{content:"i";position:absolute;left:18px;top:17px;width:18px;height:18px;
  border:1.5px solid currentColor;border-radius:50%;font:700 11px/15px var(--font);
  text-align:center}
.callout .lead{display:block;font-weight:600}
.callout a{color:inherit}
.callout p+p{margin-top:8px}
.callout.info{background:var(--info-soft);color:var(--info)}
.callout.good{background:var(--good-soft);color:var(--good)}
.callout.warn{background:var(--warn-soft);color:var(--warn)}
.callout.bad{background:var(--bad-soft);color:var(--bad)}
.callout.good::before{content:"\\2713"}
.callout.warn::before,.callout.bad::before{content:"!"}
.table-wrap{overflow-x:auto;border:1px solid var(--line-2);border-radius:var(--radius)}
.table{width:100%;border-collapse:collapse;font-size:14px;line-height:20px}
.table th,.table td{padding:10px 12px;text-align:left;vertical-align:top;
  border-bottom:1px solid var(--line);border-left:1px solid var(--line)}
.table th:first-child,.table td:first-child{border-left:0}
.table tbody tr:last-child td{border-bottom:0}
.table th{font-weight:500}
.table .n{text-align:right;font-variant-numeric:tabular-nums}
.table[data-sort] thead th{cursor:pointer;user-select:none}
.table[data-sort] thead th:hover{background:var(--bg-2)}
.table th[aria-sort="ascending"]::after{content:" \\2191";color:var(--ink-3)}
.table th[aria-sort="descending"]::after{content:" \\2193";color:var(--ink-3)}
.props{display:grid;grid-template-columns:minmax(96px,132px) 1fr;font-size:14px;line-height:20px}
.props dt,.props dd{padding:12px 0;border-bottom:1px solid var(--line)}
.props dt{padding-right:16px;color:var(--ink-2)}
.props dt:last-of-type,.props dd:last-of-type{border-bottom:0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.card{min-width:0;padding:16px 18px;border:1px solid var(--line-2);border-radius:var(--radius)}
.card>*+*{margin-top:12px}
.marks{display:grid;gap:8px;padding:0;list-style:none;font-size:14px;line-height:20px}
.marks li{position:relative;padding-left:28px}
.marks li::before{position:absolute;left:0;top:2px;width:16px;height:16px;border-radius:4px;
  font:700 13px/16px var(--font);text-align:center}
.marks.plus li::before{content:"+";background:var(--good-soft);color:var(--good)}
.marks.minus li::before{content:"\\2212";background:var(--bad-soft);color:var(--bad)}
.steps{padding:0;list-style:none;counter-reset:step}
.steps>li{position:relative;padding:0 0 20px 36px;counter-increment:step}
.steps>li:last-child{padding-bottom:0}
.steps>li::before{content:counter(step);position:absolute;left:0;top:1px;width:22px;height:22px;
  border:1px solid var(--line-2);border-radius:50%;background:var(--bg);
  font:600 12px/20px var(--font);text-align:center;font-variant-numeric:tabular-nums}
.steps>li::after{content:"";position:absolute;left:10.5px;top:27px;bottom:4px;width:1px;
  background:var(--line-2)}
.steps>li:last-child::after{display:none}
.steps>li.is-done::before{content:"\\2713";border-color:transparent;background:var(--good-soft);
  color:var(--good)}
.steps>li.is-now::before{border-color:var(--ink);background:var(--ink);color:var(--bg)}
.steps p{margin-top:2px;font-size:14px;line-height:20px;color:var(--ink-2)}
.links{padding:0;list-style:none;counter-reset:link;border:1px solid var(--line-2);
  border-radius:var(--radius);overflow:hidden}
.links li+li{border-top:1px solid var(--line)}
.links a{display:grid;grid-template-columns:auto minmax(0,1fr) auto;column-gap:12px;
  align-items:center;padding:10px 16px;font-size:14px;line-height:20px;color:var(--ink);
  text-decoration:none}
.links a:hover{background:var(--bg-2)}
.links a::before{content:counter(link);counter-increment:link;grid-row:1/span 2;min-width:24px;
  height:24px;padding:0 4px;border:1px solid var(--line);border-radius:var(--radius-sm);
  background:var(--bg-2);color:var(--ink-2);font:500 12px/22px var(--font);text-align:center;
  font-variant-numeric:tabular-nums}
.links a::after{content:"\\2197";grid-column:3;grid-row:1/span 2;color:var(--ink-3)}
.links .site{grid-column:2;font-size:12px;line-height:16px;color:var(--ink-2)}
.chip{display:inline-block;padding:1px 8px;border-radius:var(--radius-sm);background:var(--bg-2);
  color:var(--ink-2);font-size:12px;line-height:18px;font-weight:500;white-space:nowrap}
.chip.info{background:var(--info-soft);color:var(--info)}
.chip.good{background:var(--good-soft);color:var(--good)}
.chip.warn{background:var(--warn-soft);color:var(--warn)}
.chip.bad{background:var(--bad-soft);color:var(--bad)}
/* Charts. A figure.card holds one; marks take the series tokens, text takes
   the ink tokens. */
.chart svg{display:block;width:100%;height:auto;overflow:visible}
.chart .gridline{stroke:var(--line);stroke-width:1}
.chart .axis{stroke:var(--line-2);stroke-width:1}
.chart .tick,.chart .mark-label{fill:var(--ink-2);font:12px var(--font);
  font-variant-numeric:tabular-nums}
.chart .line{fill:none;stroke:var(--c,var(--s1));stroke-width:2;stroke-linejoin:round;
  stroke-linecap:round}
.chart .area{fill:var(--c,var(--s1));opacity:.1}
.chart .dot{fill:var(--c,var(--s1));stroke:var(--bg);stroke-width:2}
.chart .colbar{fill:var(--c,var(--s1))}
.chart .event{stroke:var(--ink-3);stroke-width:1;stroke-dasharray:3 3}
.chart .hit{fill:transparent;cursor:default}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;line-height:16px;color:var(--ink-2)}
.legend i{display:inline-block;width:10px;height:10px;margin-right:6px;border-radius:3px;
  background:var(--c,var(--s1))}
.cols{display:flex;align-items:stretch;gap:6px;height:200px}
.col{position:relative;flex:1;min-width:0;font-size:12px;line-height:16px;color:var(--ink-2);
  text-align:center}
.col i{position:absolute;left:50%;bottom:22px;width:min(100%,28px);min-height:2px;
  height:calc((100% - 44px)*var(--v)/100);transform:translateX(-50%);
  border-radius:4px 4px 0 0;background:var(--c,var(--s1))}
.col b{position:absolute;left:0;right:0;bottom:calc(26px + (100% - 44px)*var(--v)/100);
  font-weight:500;font-variant-numeric:tabular-nums}
.col span{position:absolute;left:0;right:0;bottom:0;overflow:hidden;white-space:nowrap}
.cols:has(.is-key) .col:not(.is-key) i{opacity:.4}
.col.is-key b{color:var(--ink)}
.bars{display:grid;gap:10px;font-size:14px;line-height:20px}
.bar{display:grid;grid-template-columns:minmax(72px,30%) 1fr auto;gap:12px;align-items:center}
.bar i{display:block;width:calc(var(--v)*1%);min-width:2px;height:10px;border-radius:0 4px 4px 0;
  background:var(--c,var(--s1))}
.bar b{font-weight:500;font-variant-numeric:tabular-nums}
.bars:has(.is-key) .bar:not(.is-key) i{opacity:.4}
.matrix{position:relative;aspect-ratio:16/9;margin:0 0 24px 24px;border:1px solid var(--line-2);
  border-radius:8px;font-size:12px;line-height:16px}
.matrix::before{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--line)}
.matrix::after{content:"";position:absolute;top:50%;left:0;right:0;height:1px;background:var(--line)}
.matrix .q{position:absolute;color:var(--ink-2)}
.matrix .q:nth-of-type(1){left:12px;top:10px}
.matrix .q:nth-of-type(2){left:calc(50% + 12px);top:10px}
.matrix .q:nth-of-type(3){left:12px;bottom:10px}
.matrix .q:nth-of-type(4){left:calc(50% + 12px);bottom:10px}
.matrix .pt{position:absolute;z-index:1;left:calc(var(--x)*1%);bottom:calc(var(--y)*1%);
  display:flex;align-items:center;gap:6px;transform:translate(-5px,50%);white-space:nowrap}
.matrix .pt::before{content:"";flex:none;width:10px;height:10px;border-radius:50%;
  background:var(--c,var(--s1));box-shadow:0 0 0 2px var(--bg)}
.matrix .x-axis,.matrix .y-axis{position:absolute;display:flex;justify-content:space-between;
  color:var(--ink-3)}
.matrix .x-axis{left:0;right:0;top:calc(100% + 6px)}
.matrix .y-axis{right:calc(100% + 6px);top:0;bottom:0;writing-mode:vertical-rl;
  transform:rotate(180deg)}
/* Controls for the interactive blocks. */
.seg{display:inline-flex;gap:2px;padding:2px;border-radius:8px;background:var(--bg-2)}
.seg button{appearance:none;padding:4px 12px;border:0;border-radius:6px;background:transparent;
  color:var(--ink-2);font:500 14px/20px var(--font);cursor:pointer}
.seg button:hover{color:var(--ink)}
.seg button[aria-pressed="true"]{background:var(--bg);color:var(--ink);
  box-shadow:0 0 0 1px var(--line-2)}
.btn{appearance:none;padding:6px 14px;border:1px solid var(--line-2);border-radius:8px;
  background:var(--bg);color:var(--ink);font:500 14px/20px var(--font);cursor:pointer}
.btn:hover{background:var(--bg-2)}
input,select,textarea{font:inherit;color:inherit}
input[type="range"],input[type="checkbox"],input[type="radio"]{accent-color:var(--accent)}
.field{padding:6px 10px;border:1px solid var(--line-2);border-radius:8px;background:var(--bg)}
.tip{position:fixed;z-index:10;max-width:260px;padding:6px 10px;border-radius:8px;
  background:var(--ink);color:var(--bg);font-size:12px;line-height:16px;pointer-events:none}
[hidden]{display:none!important}
@media (max-width:560px){.page{padding:32px 16px 64px}h1{font-size:26px}
.section{margin-top:48px}.props{grid-template-columns:1fr}
.props dt{padding-bottom:0;border-bottom:0}.props dd{padding-top:2px}
.matrix{aspect-ratio:1/1}}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (prefers-reduced-motion:reduce){
*,*::before,*::after{animation:none!important;transition:none!important}}
@media print{.page{max-width:none;padding:0}.tip,.seg{display:none!important}
*{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}
h1,h2,h3{break-after:avoid}tr,.card,.callout,.metric,.steps>li{break-inside:avoid}
.table-wrap{overflow:visible}}"""

# Stamps `data-theme` from the `?theme=` query the Artifacts stage appends, so
# the page follows the app's theme. Harmless anywhere else (no query → OS).
THEME_BOOTSTRAP_JS: Final = """\
(function(){try{
var t=new URLSearchParams(location.search).get("theme");
if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t);}
}catch(e){}})();"""

#: The message a framed page sends to the app when the reader clicks a web
#: link (``FRAMED_LINK_MESSAGE`` in ``frontend/src/hooks/useFramedPageLinks.ts``;
#: a parity test keeps both names equal).
FRAMED_LINK_MESSAGE: Final = "dodaios-open-link"

# What makes the kit's blocks interactive, in one script the worker pastes at
# the end of <body>. Five behaviours, each driven by markup alone, so a page
# gets them without writing code:
#   .toc                    the link of the section being read is marked
#   [data-tip]              a tooltip with that text on hover and on focus
#   .seg[data-for=G]        its buttons (data-show=V) switch the blocks marked
#                           data-group=G between their data-view values
#   table[data-sort]        a click on a column head sorts the rows
#                           (a cell's data-value wins over its text)
#   a[href^=http]           a web link opens outside the page: the page is
#                           framed without popups and navigation, so it asks
#                           the app to open the address; opened on its own in
#                           a browser tab, it goes there itself
# No network, no storage: the sandbox the page runs in allows neither anyway.
PAGE_JS: Final = """\
(function(){
function start(){
var d=document,each=function(l,f){Array.prototype.forEach.call(l,f);};
var links=d.querySelectorAll('.toc a[href^="#"]'),secs=[];
each(links,function(a){
  secs.push(d.getElementById(decodeURIComponent(a.getAttribute("href").slice(1))));});
function mark(){var cur=0;
  secs.forEach(function(s,i){if(s&&s.getBoundingClientRect().top<=innerHeight*.3)cur=i;});
  if(scrollY>0&&innerHeight+scrollY>=d.documentElement.scrollHeight-2)cur=links.length-1;
  each(links,function(a,i){a.classList.toggle("is-current",i===cur);});}
if(links.length){mark();addEventListener("scroll",mark,{passive:true});}
var tip=d.createElement("div");tip.className="tip";tip.hidden=true;d.body.appendChild(tip);
function show(e){
  var t=e.target&&e.target.closest?e.target.closest("[data-tip]"):null;
  if(!t){tip.hidden=true;return;}
  tip.textContent=t.getAttribute("data-tip");tip.hidden=false;
  var r=t.getBoundingClientRect(),x=e.clientX||r.left+r.width/2,y=e.clientY||r.top;
  var w=tip.offsetWidth,h=tip.offsetHeight;
  tip.style.left=Math.max(8,Math.min(innerWidth-w-8,x-w/2))+"px";
  tip.style.top=(y-h-12<8?y+18:y-h-12)+"px";}
function hide(){tip.hidden=true;}
d.addEventListener("pointermove",show);d.addEventListener("focusin",show);
d.addEventListener("focusout",hide);d.documentElement.addEventListener("pointerleave",hide);
d.addEventListener("click",function(e){
  var a=e.target.closest?e.target.closest("a[href]"):null;
  var h=a?(a.getAttribute("href")||"").trim():"";
  if(h.indexOf("http://")===0||h.indexOf("https://")===0){
    e.preventDefault();
    if(window.parent!==window){window.parent.postMessage({type:"dodaios-open-link",href:h},"*");}
    else{location.href=h;}
    return;}
  var b=e.target.closest?e.target.closest(".seg button[data-show]"):null;
  if(b){var g=b.parentNode.getAttribute("data-for");
    each(b.parentNode.children,function(x){x.setAttribute("aria-pressed",x===b?"true":"false");});
    each(d.querySelectorAll('[data-view][data-group="'+g+'"]'),function(v){
      v.hidden=v.getAttribute("data-view")!==b.getAttribute("data-show");});
    return;}
  var th=e.target.closest?e.target.closest("table[data-sort] thead th"):null;
  if(!th)return;
  var body=th.closest("table").tBodies[0],i=th.cellIndex;
  var asc=th.getAttribute("aria-sort")!=="ascending";
  each(th.parentNode.cells,function(c){c.removeAttribute("aria-sort");});
  th.setAttribute("aria-sort",asc?"ascending":"descending");
  function key(r){var c=r.cells[i];
    return c?(c.getAttribute("data-value")||c.textContent).trim():"";}
  Array.prototype.slice.call(body.rows).sort(function(a,b){
    var x=key(a),y=key(b),nx=Number(x),ny=Number(y);
    var c=x!==""&&y!==""&&!isNaN(nx)&&!isNaN(ny)?nx-ny:x.localeCompare(y,undefined,{numeric:true});
    return asc?c:-c;}).forEach(function(r){body.appendChild(r);});
});
}
if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",start);}
else{start();}
})();"""

# The skeleton every page starts from: the document's name, a summary that
# already answers, a contents box, then sections that each carry statements,
# and the sources last.
PAGE_SKELETON: Final = (
    '<main class="page">\n'
    "  <h1>Laptop performance: what slows it down</h1>\n"
    '  <p class="summary">Measured on 12 May over ten minutes. One render loop keeps '
    "93 % of a core busy while the window is idle; closing that app fixes it. "
    "Battery health was not measured.</p>\n"
    '  <nav class="toc" aria-label="On this page">\n'
    '    <p class="toc-label">On this page</p>\n'
    '    <a href="#where-the-time-goes">Where the time goes</a>\n'
    '    <a href="#what-to-do">What to do</a>\n'
    '    <a href="#sources">Sources</a>\n'
    "  </nav>\n"
    '  <section class="section" id="where-the-time-goes">\n'
    "    <h2>Where the time goes</h2>\n"
    '    <p class="caption">Process sampling, ten-minute window, window idle.</p>\n'
    '    <div class="metrics">\n'
    '      <div class="metric"><div class="value">93 %</div>'
    '<div class="label">of one core</div><div class="detail">render loop, idle</div></div>\n'
    "      …\n"
    "    </div>\n"
    "    <p>…</p>\n"
    '    <div class="callout info"><strong class="lead">Recommendation</strong>…</div>\n'
    "  </section>\n"
    "  …\n"
    '  <section class="section" id="sources">\n'
    "    <h2>Sources</h2>\n"
    '    <ol class="links">\n'
    '      <li><a href="https://example.org/doc">Title of the source'
    '<span class="site">example.org</span></a></li>\n'
    "    </ol>\n"
    "  </section>\n"
    "</main>"
)

# The markup of each block, because a class name alone does not say how the
# block is built. Shown once, with the smallest content that shows its shape.
KIT_MARKUP: Final = """\
<!-- metric row: two to four current values -->
<div class="metrics">
  <div class="metric"><div class="value">346</div><div class="label">Stars</div>
    <div class="detail">as of 9 Nov</div></div>
</div>

<!-- callout: tone info | good | warn | bad, or none for a neutral note -->
<div class="callout warn"><strong class="lead">Hard rule</strong>No run without a limit.</div>

<!-- table: .n for a column of numbers, data-sort to make it sortable -->
<div class="table-wrap"><table class="table" data-sort>
  <thead><tr><th>Provider</th><th class="n">Price</th></tr></thead>
  <tbody><tr><td>Alpha</td><td class="n" data-value="19">19 €</td></tr></tbody>
</table></div>
<p class="note">List prices, read on 13 Nov.</p>

<!-- properties: what one thing is, attribute by attribute -->
<dl class="props"><dt>For whom</dt><dd>Single developers and very small teams.</dd></dl>

<!-- for and against, side by side -->
<div class="grid">
  <div class="card"><h3>Why A</h3><ul class="marks plus"><li>…</li></ul></div>
  <div class="card"><h3>Risks of A</h3><ul class="marks minus"><li>…</li></ul></div>
</div>

<!-- a real sequence; is-done / is-now show progress in a plan -->
<ol class="steps">
  <li class="is-done"><h3>Account and billing</h3><p>Login, checkout, invoices.</p></li>
  <li class="is-now"><h3>Metering and auto-stop</h3><p>Every run has a limit.</p></li>
</ol>

<!-- column chart: --v is the value as a percentage of the largest one -->
<figure class="card chart"><h3>New stars per week</h3>
  <div class="cols">
    <div class="col" style="--v:30" data-tip="28 Sep: 23 stars">
      <b>23</b><i></i><span>28.09.</span></div>
    <div class="col is-key" style="--v:100" data-tip="5 Oct: 76 stars">
      <b>76</b><i></i><span>05.10.</span></div>
  </div>
</figure>

<!-- horizontal bars, for long names -->
<div class="bars">
  <div class="bar" style="--v:64" data-tip="Reddit: 64 %">
    <span>Reddit</span><i></i><b>64 %</b></div>
</div>

<!-- line chart: inline SVG on the .chart classes; a .hit rect per point
     carries the tooltip -->
<figure class="card chart"><h3>Stars over time</h3>
  <svg viewBox="0 0 700 280" role="img" aria-label="Stars from 10 Sep to 8 Nov">
    <line class="gridline" x1="44" x2="676" y1="60" y2="60"/>
    <text class="tick" x="36" y="64" text-anchor="end">300</text>
    <line class="event" x1="352" x2="352" y1="20" y2="244"/>
    <text class="mark-label" x="346" y="16" text-anchor="end">Rename</text>
    <path class="line" d="M44,230 L352,150 L676,24"/>
    <circle class="dot" cx="676" cy="24" r="4"/>
    <text class="mark-label" x="668" y="14" text-anchor="end">345</text>
    <rect class="hit" x="340" y="20" width="24" height="224" data-tip="12 Oct: 188 stars"
      tabindex="0"/>
  </svg>
</figure>

<!-- 2×2 matrix: --x and --y are 0–100 from the bottom left -->
<div class="matrix">
  <span class="q">First</span><span class="q">Plan</span>
  <span class="q">On the side</span><span class="q">Later</span>
  <span class="pt" style="--x:10;--y:60">Answer the two issues</span>
  <span class="x-axis"><span>little effort</span><span>much effort →</span></span>
  <span class="y-axis"><span>little impact</span><span>much impact →</span></span>
</div>

<!-- switchable views: the buttons show one block of the group -->
<div class="seg" data-for="range">
  <button data-show="week" aria-pressed="true">Week</button>
  <button data-show="month" aria-pressed="false">Month</button>
</div>
<div data-group="range" data-view="week">…</div>
<div data-group="range" data-view="month" hidden>…</div>

<!-- sources: numbered by the list itself -->
<ol class="links">
  <li><a href="https://example.org/pricing">Example pricing
    <span class="site">example.org</span></a></li>
</ol>"""


# --- The guide, section by section ---------------------------------------------

READ_THE_REQUEST: Final = """\
## Read the request first — the form follows the ask
The request names the deliverable; honour it literally before any rule below.
- Asked for a chart, "Balken", "Kurve", "Verlauf", "Anteile" → the chart IS the page: \
one clear chart (or a small set of them) with a one-line takeaway above it and the \
numbers in a table below, not a long document with a chart somewhere inside.
- Asked for a comparison, "Gegenüberstellung", "Vergleich" → a comparison table with \
the SAME attributes in the same order for every option, then one recommendation.
- Asked to explain, "erklär mir", "wie funktioniert" → a readable document: short \
sections in reading order, ONE diagram or chart exactly where it helps the \
explanation, never decoration.
- Asked for a plan, report, analysis, "Geschäftsplan", "Bericht", "Auswertung" → the \
full document: summary, contents box, sections that each state findings with their \
numbers, the decisions that are open, the sources.
- Asked for a dashboard, "Übersicht", "Status" → a page that is scanned, not read: \
the metric row first, the charts below, a sortable table for the long tail; use \
`.page wide`.
- Asked for a timeline, flow, hierarchy, mind map → a diagram drawn with CSS grid / \
flex or inline SVG: nodes as `.card`s, hairline connectors, arrows only where \
direction carries meaning.
- Asked for a landing page, one-pager, tool, game → the same plain look: one real \
statement at the top, the working thing right below it, then restraint.
Default when unsure: the plain document. Every kind of request gets the same quiet \
page — no hero, no tagline, no marketing voice."""

PAGE_ANATOMY: Final = """\
## Page anatomy — simple to look at, dense in what it says
A page is one reading column (`.page`, about 700 px) on the page ground. Nothing \
decorates it: no header band, no logo, no hero, no coloured headline, no footer. \
What fills it is statements. In this order:
1. `<h1>` — the document's name, as a person would file it ("Business plan v1: cloud \
service", "Growth report"), not a slogan.
2. `<p class="summary">` — two to four sentences that already answer: what this is \
and for whom, the date and the period the numbers cover, the result in one sentence, \
and what the page deliberately leaves out.
3. `<nav class="toc">` — the contents box, when the page has four sections or more: \
one link per section, in order, each to the section's `id`.
4. The sections (`<section class="section" id="…">`): an `<h2>` that names the topic \
in a few words, optionally a `<p class="caption">` right under it that says where the \
numbers come from or how to read the section, then the blocks.
5. A last section "Sources" (in the page's language) as `<ol class="links">`, when \
the page rests on sources: one row per source, its title and its site. Web links \
are plain `<a href="https://…">` with no `target`; the page script opens them \
outside the page.
Inside a section, pick the block by what the content IS:
- two to four current values → `.metrics`
- running argument → paragraphs, two to four sentences each
- the one recommendation, the one caveat, the one rule → a `.callout` with a tone \
(`info` for a recommendation or a role note, `warn` for a risk or an open decision, \
`good` / `bad` for a verdict); at most one or two per section
- the same attributes for several things → `.table`; the attributes of ONE thing → \
`.props`
- arguments for and against → two `.card`s with `.marks plus` and `.marks minus`
- a real sequence (build order, roadmap, how-to) → `.steps`; points with no order → a \
plain `<ul>`; ranked or countable points → a plain `<ol>`
- a number over time, a comparison of magnitudes, a position on two axes → a chart \
(see Charts)
A `.note` under a table or chart states the source or the assumption. Use the kit \
instead of inventing parallel components; extend it only for what it does not cover, \
on the same tokens. The skeleton:
```html
""" + PAGE_SKELETON + """
```
The blocks, with their markup:
```html
""" + KIT_MARKUP + """
```
The example text shows the register — replace every word with the request's own \
content."""

WRITING: Final = """\
## Writing — the statements are the page
- Every section says something that can be checked: a number with its unit (6 of 53, \
93 %, 19 €/month), a date, a name, a decision. A section that only describes is cut \
or merged.
- The summary answers first. The reader who stops after it knows the result.
- Every figure carries where it comes from and when it was read; a claim without \
evidence is marked as an assumption in plain words.
- One recommendation per decision, with the reason it beats the runner-up; trade-offs \
named in one plain clause ("but: the most expensive of the three").
- Headings are short and plain: the topic in two to five words ("What comparable \
products charge"), or the finding itself where the section has one.
- Short sentences, common words, no filler; labels as short as a person would say \
them — a metric label is two to four words, never a sentence.
- Open decisions are stated as questions the reader can answer, each with the \
recommended answer.
- Length follows content: a page is as long as its statements, never padded; cut any \
section that restates another."""

DESIGN_SYSTEM: Final = """\
## Design system — one plain look for every page
Paste the stylesheet below VERBATIM as the first <style> in <head>, the bootstrap \
script as the first <script> in <head>, and the page script as the last <script> \
before </body>. The stylesheet is the tokens AND the block kit (see Page anatomy); \
your own CSS comes after it. Derive every colour, font and radius from the tokens; \
never introduce a hex that is not in the block. Light is the base, dark is fully \
defined, both are complete — scan your stylesheet before finishing: no colour may be \
defined ONLY inside a media or [data-theme] block.
- Ground and ink: the page is `--bg`, text is `--ink`, secondary text (captions, \
notes, table of contents, labels under a value) is `--ink-2`. Boxes are the page \
ground with a 1px `--line-2` border and radius `--radius`; rows inside them are \
separated by 1px `--line`. `--bg-2` is the quiet fill (code, hover, a neutral \
callout). No shadows, no gradients, no second surface colour.
- Colour is rare and always means something: `--accent` for links and for the one \
data series; the tones `--info / --good / --warn / --bad` with their `-soft` grounds \
for callouts, chips and a marked cell (`.t-warn`), always with words that say what \
the colour means. Headings and body text are never coloured.
- Type: `--font` for everything a person reads; `--mono` only for code, file paths \
and commands. One scale — 30 px title, 22 px section heading, 16 px sub-heading and \
body, 14 px for tables, captions and notes, 12 px for chart ticks and small labels; \
weight 600 for headings and values, 500 for table heads. Stay on it, never an inline \
`style="font-size:…"`. No uppercase labels, no letter-spaced eyebrows.
- Width: `.page` for documents (the default); `.page wide` (about 1040 px) only for \
a dashboard or a table with six columns or more. Running text never goes wider than \
the 700 px column.
- Spacing comes from the kit: 64 px between sections, 20 px between blocks, 12 px \
between paragraphs. Do not add margins of your own between kit blocks. Wide tables, \
code and diagrams scroll inside their own container — the page body never scrolls \
sideways.
- Copy is design material: the `<title>` is the page's name (a short noun phrase, no \
explainer after a dash), labels name things the way a person would, numbers carry \
their unit, notes state the source or assumption."""

CHARTS: Final = """\
## Charts and interactive blocks
A page that carries numbers shows the important ones as a picture the reader can \
question — at least one interactive infographic wherever the content has a series, a \
ranking or a position on two axes. The page script (pasted verbatim) makes the kit \
interactive from markup alone; write your own script only for what it does not cover \
(a calculator, a filter, a slider that recomputes a chart).
- Form before colour. A single current value → a `.metric`, not a one-bar chart. \
Magnitude compared → `.cols` (few values, short labels) or `.bars` (long names). \
Trend → a line as inline SVG on the `.chart` classes (an area only for one series). \
Position on two measures → `.matrix`. Part-to-whole → one stacked horizontal bar. \
Never a dual-axis chart: two measures of different scale get two charts side by side \
in a `.grid`.
- A chart sits in a `<figure class="card chart">` with an `<h3>` that says what it \
shows, including the unit and the period. Two small charts go side by side in a \
`.grid`; a `.cols` chart with more than six columns takes the full width, so its \
labels fit.
- Every mark answers on hover and on focus: give each column, bar, point and matrix \
dot a `data-tip` with the full statement ("5 Oct: 76 stars"); on a line, lay an \
invisible `.hit` rect over each point (at least 24 px wide, `tabindex="0"`).
- Where two readings of the same data are useful (week / month, absolute / share), \
offer both with a `.seg` control above the chart instead of drawing both. Where a \
table has more than about eight rows, make it sortable with `data-sort` and give \
number cells a `data-value`.
- Marks are thin and calm: columns at most 28 px wide, 4 px rounded at the data end \
and square at the baseline; lines 2 px with round joins; dots 4 px radius with a 2 px \
ring in the page ground; grid lines 1 px solid `--line`, never dashed (the dashed \
`.event` line is for a dated event only); generous padding; the data is the only loud \
thing.
- Colour by job: ONE series → `--s1`, and the one value the text is about marked \
`is-key` (the others fade by themselves). TWO OR MORE series → the slots `--s1 … \
--s6` in that fixed order (set `--c` on the mark), never cycled, never generated; \
past six fold the tail into "Other". Magnitude → the ramp `--seq-1 … --seq-5` (one \
hue). Colour follows the entity, never its rank.
- Text wears ink tokens: values, labels, ticks and legends in `--ink` / `--ink-2`, \
never in the series colour; identity comes from a `.legend` swatch beside the text.
- A legend is always present for two or more series (none for one); label \
selectively (the endpoint, the extreme, the event) — never a number on every point \
of a line; axis ticks are round numbers with thousands separators.
- Every value is reachable without hovering: direct labels or a table under the \
chart carry the data too.
- Diagrams: nodes are `.card`s, connectors 1 px `--line-2` with small arrowheads \
only where direction matters; a flow reads left→right or top→bottom, never both; no \
emoji icons — draw small inline-SVG icons or use none."""

AVOID: Final = """\
## What reads as generated — never ship these (they were in our own archive)
- A centred hero with a giant headline and a tagline; gradient text; glows, blurred \
colour blobs, radial backdrops; a gradient anywhere; a shadow under a card.
- Furniture that says nothing: an eyebrow line above the title, uppercase \
letter-spaced labels, a "§ 1" mark beside a heading, a footer band, a logo or brand \
mark on the page, 01/02/03 markers on non-sequences.
- Pills and chips as decoration; emoji as section markers or icons.
- A stand-in for a logo: a lettered tile ("G", "OA", "A" in a coloured square), an emoji, \
an invented glyph or a generic "AI" spark beside a vendor's name — the original mark \
(supplied in the brief when the request names the brand) or the name in plain text, \
nothing in between.
- The Tailwind rainbow (#3b82f6, #a855f7, #8b5cf6, #06b6d4, #10b981, #f59e0b, #f43f5e, \
slate greys) and any palette not in the token block; near-black with one acid-green \
or neon accent; purple-to-blue gradients.
- A coloured headline; a card with an accent bar on its side; a filled table head; \
zebra rows; cards nested in cards; three equal columns of icon + title + sentence.
- Marketing voice ("Next-Gen", "Intelligence Hub", "Tracker", "supercharge"); \
lorem ipsum; placeholder numbers; "TODO"; a title with an appended explainer \
("Dashboard — an interactive overview of…").
- Charts: dual axes, thick saturated blocks, dashed grids, rainbow categories, a value \
on every point of a line, a 2-slice pie, legend-less multi-series, text in the series \
colour, a chart whose marks say nothing on hover.
- A summary that restates the title; a section with no number, date or name in it; \
metric labels that are whole sentences; the same finding said twice.
- Hex colours or `#fff` written into component CSS (they break the other theme); \
inline font sizes; margins added between kit blocks.
- Web fonts or anything fetched (the sandbox blocks every request — the page breaks \
silently); scattered micro-animations; animation that runs without being asked for."""

DONE_MEANS: Final = """\
## Done means
- The file opens from disk with no network and renders with no console errors; every \
script, style and image is inline.
- Both themes read correctly: open it once with `?theme=light` and once with \
`?theme=dark` (or flip the OS setting) — same hierarchy, legible contrast; no colour \
defined only in a media/[data-theme] block.
- The page does exactly what the request asked — the chart the user named, the \
comparison, the explanation — with the real numbers and facts from the request; \
where something was missing, a clearly labelled assumption.
- It opens with the document's name and a summary that answers, lists its sections \
in the contents box when there are four or more, and every section states something \
that can be checked.
- Every chart mark, every sortable table and every view switch responds; the contents \
box marks the section being read.
- Nothing on the page says how it was built, which model wrote it, or what the \
instructions were; it carries no logo and no brand line.
- Nothing else was created or changed."""


__all__ = [
    "AVOID",
    "CHARTS",
    "DESIGN_SYSTEM",
    "DONE_MEANS",
    "FRAMED_LINK_MESSAGE",
    "KIT_MARKUP",
    "PAGE_ANATOMY",
    "PAGE_JS",
    "PAGE_SKELETON",
    "READ_THE_REQUEST",
    "THEME_BOOTSTRAP_JS",
    "THEME_CSS",
    "WRITING",
]
