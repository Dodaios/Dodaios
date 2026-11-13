"""How a node's page and the app talk: comments left on the page.

A node's page runs in a sandbox of its own (scripts, and nothing else): the
app cannot see where the reader clicks in it, and the page cannot reach the
app's API. So the two talk in messages, and the page does the part only it
can do. In COMMENT mode a click on the page drops a numbered pin with a small
field at that very place; the reader writes what should change and adds it.
The page tells the app the comment, the text it was left on and where in the
node that is. The app collects them; one "Send" in the app's toolbar hands
them all to the assistant at once (``comments.py``), which revises the node.

Messages (``postMessage``; the app checks that they come from its own frame,
the page that they come from its parent):

* page → app ``dodaios-node-ready``: the page has loaded; the app answers
  with the mode it is in.
* app → page ``dodaios-node-mode`` ``{mode: "view" | "comment", labels}``:
  ``labels`` are the few words the page shows, in the reader's language.
* page → app ``dodaios-node-comment`` ``{n, text, quote, where}``: comment
  ``n`` was added. ``quote`` is the text under the pin, ``where`` names the
  place in the node's own terms (``/slides/2``, ``Price × Netflix``,
  ``§ Costs``), so the assistant does not have to guess.
* page → app ``dodaios-node-comment-remove`` ``{n}``: the reader took comment
  ``n`` back before it was sent.
* app → page ``dodaios-node-comment-state``
  ``{n, state: "pending" | "sent" | "failed"}``: ``pending`` once the app holds
  the comment (it waits for "Send"), ``sent`` once it went to the assistant,
  ``failed`` when that did not work (it stays and can be sent again).

The pin and its field are drawn by the page, not by the app, because only
the page knows its own scroll position and layout: a pin drawn here stays on
the sentence it was put on. While the mode is on, clicks do not reach the
page's own controls (a deck does not turn its slide, a link does not open):
the click belongs to the comment.

Everything is text set through ``textContent``; nothing from a message is
ever written as markup.
"""

from __future__ import annotations

from typing import Final

#: The message names, shared with ``frontend/src/components/nodes/nodeBridge.ts``
#: (a parity test keeps both sides equal).
READY_MESSAGE: Final[str] = "dodaios-node-ready"
MODE_MESSAGE: Final[str] = "dodaios-node-mode"
COMMENT_MESSAGE: Final[str] = "dodaios-node-comment"
COMMENT_STATE_MESSAGE: Final[str] = "dodaios-node-comment-state"
COMMENT_REMOVE_MESSAGE: Final[str] = "dodaios-node-comment-remove"

MAX_COMMENT_CHARS: Final[int] = 2_000
MAX_QUOTE_CHARS: Final[int] = 240
MAX_WHERE_CHARS: Final[int] = 300

BRIDGE_CSS: Final[str] = """
:root[data-node-mode="comment"],:root[data-node-mode="comment"] *{cursor:crosshair!important}
.nc-layer{position:absolute;left:0;top:0;width:0;height:0;z-index:2147483000}
:root[data-node-mode] .nc-layer,:root[data-node-mode] .nc-layer *{cursor:auto!important}
.nc{position:absolute;display:flex;align-items:flex-end;gap:10px;transform:translateY(-100%);
  font:14px/20px var(--font);color:var(--ink)}
.nc.nc-left{flex-direction:row-reverse;transform:translate(-100%,-100%)}
.nc-pin{flex:none;min-width:30px;height:30px;padding:0 9px;border-radius:15px 15px 15px 4px;
  background:var(--accent);color:var(--accent-ink);font:600 13px/30px var(--font);text-align:center;
  font-variant-numeric:tabular-nums;box-shadow:0 0 0 2px var(--bg),0 4px 14px rgba(0,0,0,.28)}
.nc-left .nc-pin{border-radius:15px 15px 4px 15px}
.nc-box{display:flex;align-items:flex-end;gap:6px;width:min(340px,calc(100vw - 96px));
  padding:6px 7px 6px 16px;border:1px solid var(--line-2);border-radius:22px;background:var(--bg-3);
  box-shadow:0 8px 28px rgba(0,0,0,.28)}
.nc-box textarea{flex:1;min-width:0;height:28px;max-height:120px;padding:4px 0;border:0;outline:0;
  resize:none;background:transparent;color:var(--ink);font:inherit}
.nc-box textarea::placeholder{color:var(--ink-3)}
.nc-send{flex:none;display:grid;place-items:center;width:28px;height:28px;padding:0;border:0;
  border-radius:50%;background:var(--accent);color:var(--accent-ink);cursor:pointer!important}
.nc-send[disabled]{opacity:.35;cursor:default!important}
.nc-send svg,.nc-drop svg{width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:2.2;
  stroke-linecap:round;stroke-linejoin:round}
.nc-drop{flex:none;display:grid;place-items:center;width:28px;height:28px;padding:0;border:0;
  border-radius:50%;background:transparent;color:var(--ink-2);cursor:pointer!important}
.nc-drop:hover{background:var(--line-2);color:var(--ink)}
.nc-said{padding:4px 9px 4px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.nc-note{display:block;font-size:12px;line-height:16px;color:var(--ink-2)}
.nc.is-busy .nc-box{opacity:.72}
.nc.is-failed .nc-box{border-color:var(--bad)}
.nc.is-failed .nc-note{color:var(--bad)}
@media print{.nc-layer{display:none!important}}
"""

# ES5 on purpose, like the kit's page script: it runs in whatever WebView the
# page is opened in. No network, no storage: the sandbox allows neither.
BRIDGE_JS: Final[str] = r"""
(function(){
var d=document,root=d.documentElement,up=window.parent;
if(!up||up===window)return;
var mode="view",layer=null,draft=null,sent=0,byNumber={};
var labels={placeholder:"Add a comment…",add:"Add comment",pending:"Not sent yet",sent:"Sent",
  failed:"Not sent. Try again.",remove:"Remove comment"};
function post(m){try{up.postMessage(m,"*");}catch(e){}}
function squeeze(s,max){s=String(s||"").replace(/\s+/g," ").replace(/^ | $/g,"");
  return s.length>max?s.slice(0,max-1)+"…":s;}
function textOf(el,max){return squeeze(el.innerText||el.textContent||"",max);}
function meta(name){
  var m=d.querySelector('meta[name="'+name+'"]');return m?m.getAttribute("content")||"":"";}
function near(el,sel){return el&&el.closest?el.closest(sel):null;}
function carrier(el){
  while(el&&el.nodeType===1&&el!==d.body&&el!==root){if(textOf(el,2))return el;el=el.parentNode;}
  return null;}
function narrow(el,x,y){
  // A click on the air inside a long block means the part next to it.
  for(var depth=0;depth<12&&textOf(el,400).length>200;depth++){
    var best=null,gap=1e9,kids=el.children;
    for(var i=0;i<kids.length;i++){
      if(!textOf(kids[i],2))continue;
      var r=kids[i].getBoundingClientRect();if(!r.width&&!r.height)continue;
      var off=(y<r.top?r.top-y:y>r.bottom?y-r.bottom:0)+(x<r.left?r.left-x:x>r.right?x-r.right:0);
      if(off<gap){gap=off;best=kids[i];}
    }
    if(!best||gap>48)break;
    el=best;
  }
  return el;}
function whereOf(el){
  var out=[],type=meta("dodaios-node-type"),hit;
  hit=near(el,"[data-at]");if(hit)out.push(hit.getAttribute("data-at"));
  hit=near(el,"[data-i]");if(hit&&type==="slides")out.push("/slides/"+hit.getAttribute("data-i"));
  hit=near(el,".scene");
  if(hit&&type==="motion")out.push("/scenes/"+Array.prototype.indexOf.call(d.querySelectorAll(".scene"),hit));
  hit=near(el,"[data-id]");if(hit)out.push("#"+hit.getAttribute("data-id"));
  var cell=near(el,"td,th");
  if(cell){
    var row=cell.parentNode,table=near(cell,"table"),head=table&&table.tHead&&table.tHead.rows[0];
    var col=head&&head.cells[cell.cellIndex]?textOf(head.cells[cell.cellIndex],60):"",first="";
    for(var i=0;row&&row.cells&&i<row.cells.length;i++){
      first=textOf(row.cells[i],60);if(first)break;}
    if(col||first)out.push((col||"?")+" × "+(first||"?"));
  }
  var heads=d.querySelectorAll("h1,h2,h3"),last=null;
  for(var j=0;j<heads.length;j++){
    if(heads[j]===el||heads[j].contains(el))continue;
    if(heads[j].compareDocumentPosition(el)&4)last=heads[j];
  }
  if(last&&textOf(last,2))out.push("§ "+textOf(last,80));
  return out.join(", ").slice(0,300);}
// Only the two constant icons below are ever written as markup.
var TICK="M3 8.5 6.5 12 13 4.5",CROSS="M4 4l8 8M12 4l-8 8";
function icon(button,path){
  button.innerHTML='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="'+path+'"/></svg>';}
function inLayer(t){return !!(layer&&t&&t.nodeType===1&&layer.contains(t));}
function ensureLayer(){
  if(layer)return layer;
  layer=d.createElement("div");layer.className="nc-layer";layer.setAttribute("data-node-comments","");
  ["click","dblclick","mousedown","pointerdown","touchstart","keydown","keyup","keypress","wheel"]
    .forEach(function(t){layer.addEventListener(t,function(e){e.stopPropagation();});});
  d.body.appendChild(layer);return layer;}
function dropDraft(){
  if(draft&&draft.node.parentNode)draft.node.parentNode.removeChild(draft.node);draft=null;}
function grow(field){
  field.style.height="28px";field.style.height=Math.min(120,field.scrollHeight)+"px";}
function settle(c,note,cls){
  c.node.className=c.node.className.replace(/ is-(busy|failed|sent)/g,"")+(cls?" "+cls:"");
  c.note.textContent=note||"";c.note.hidden=!note;}
function send(c){
  var text=c.field.value.replace(/^\s+|\s+$/g,"");
  if(!text||c.busy)return;
  c.busy=true;c.field.disabled=true;c.button.disabled=true;settle(c,"","is-busy");
  byNumber[c.n]=c;
  post({type:"dodaios-node-comment",n:c.n,text:text.slice(0,2000),quote:c.quote,where:c.where});}
function open(e){
  var el=carrier(e.target),x=e.pageX,y=e.pageY,kept=draft&&!draft.busy?draft.field.value:"";
  if(draft&&draft.busy)return;
  if(el)el=narrow(el,e.clientX,e.clientY);
  dropDraft();
  var c={n:sent+1,busy:false,quote:el?textOf(el,240):"",where:el?whereOf(el):""};
  c.node=d.createElement("div");c.node.className="nc";c.node.setAttribute("data-n",String(c.n));
  var pin=d.createElement("span");pin.className="nc-pin";pin.textContent=String(c.n);
  var box=d.createElement("div");box.className="nc-box";
  var body=d.createElement("div");body.style.flex="1";body.style.minWidth="0";
  c.field=d.createElement("textarea");c.field.rows=1;c.field.maxLength=2000;
  c.field.placeholder=labels.placeholder;c.field.setAttribute("aria-label",labels.placeholder);
  c.field.style.display="block";c.field.style.width="100%";c.field.value=kept;
  c.note=d.createElement("span");c.note.className="nc-note";c.note.hidden=true;
  c.note.setAttribute("role","status");
  c.button=d.createElement("button");c.button.type="button";c.button.className="nc-send";
  c.button.setAttribute("aria-label",labels.add);c.button.title=labels.add;c.button.disabled=!kept;
  icon(c.button,TICK);
  body.appendChild(c.field);body.appendChild(c.note);box.appendChild(body);box.appendChild(c.button);
  c.node.appendChild(pin);c.node.appendChild(box);
  c.node.style.left=x+"px";c.node.style.top=y+"px";
  var room=(window.innerWidth||root.clientWidth)-(x-(window.pageXOffset||0));
  if(room<400&&x>room)c.node.className+=" nc-left";
  ensureLayer().appendChild(c.node);
  c.field.addEventListener("input",function(){
    grow(c.field);c.button.disabled=!c.field.value.replace(/\s+/g,"");
    if(/ is-failed/.test(c.node.className))settle(c,"","");});
  c.field.addEventListener("keydown",function(k){
    if(k.key==="Enter"&&!k.shiftKey&&!k.isComposing){k.preventDefault();send(c);}
    else if(k.key==="Escape"){k.preventDefault();dropDraft();}});
  c.button.addEventListener("click",function(){send(c);});
  draft=c;grow(c.field);
  try{c.field.focus({preventScroll:true});}catch(err){c.field.focus();}}
function remove(c){
  if(c.node.parentNode)c.node.parentNode.removeChild(c.node);
  delete byNumber[c.n];post({type:"dodaios-node-comment-remove",n:c.n});}
function hold(c){
  // The app holds the comment until "Send": it reads as said, with a way back.
  var said=d.createElement("div");said.className="nc-said";said.textContent=c.field.value;
  c.field.parentNode.replaceChild(said,c.field);
  var drop=d.createElement("button");drop.type="button";drop.className="nc-drop";
  drop.setAttribute("aria-label",labels.remove);drop.title=labels.remove;
  icon(drop,CROSS);
  drop.addEventListener("click",function(){if(!c.done)remove(c);});
  c.button.parentNode.replaceChild(drop,c.button);c.button=drop;
  c.held=true;c.busy=false;settle(c,labels.pending,"");sent=Math.max(sent,c.n);
  if(draft===c)draft=null;}
function answered(n,state){
  var c=byNumber[n];if(!c)return;
  if(state==="pending"){if(!c.held)hold(c);}
  else if(state==="sent"){
    if(!c.held)hold(c);
    c.done=true;if(c.button.parentNode)c.button.parentNode.removeChild(c.button);
    settle(c,labels.sent,"is-sent");delete byNumber[n];
  }else if(c.held){settle(c,labels.failed,"is-failed");}
  else{
    c.busy=false;c.field.disabled=false;c.button.disabled=false;settle(c,labels.failed,"is-failed");
    try{c.field.focus({preventScroll:true});}catch(err){c.field.focus();}
  }}
function setMode(next,given){
  if(given&&typeof given==="object"){
    for(var k in labels){if(typeof given[k]==="string"&&given[k])labels[k]=given[k].slice(0,120);}
  }
  mode=next==="comment"?"comment":"view";
  if(mode==="comment"){root.setAttribute("data-node-mode","comment");}
  else{root.removeAttribute("data-node-mode");if(draft&&!draft.busy)dropDraft();}}
function guard(e){
  if(mode!=="comment"||inLayer(e.target))return;
  e.stopPropagation();
  if(e.type==="click"){e.preventDefault();open(e);}}
["click","dblclick","mousedown","pointerdown","touchstart"].forEach(function(t){
  window.addEventListener(t,guard,true);});
window.addEventListener("message",function(e){
  if(e.source!==up)return;
  var m=e.data;if(!m||typeof m!=="object")return;
  if(m.type==="dodaios-node-mode")setMode(m.mode,m.labels);
  else if(m.type==="dodaios-node-comment-state")answered(Number(m.n),m.state);});
function ready(){
  post({type:"dodaios-node-ready",node:meta("dodaios-node"),kind:meta("dodaios-node-type")});}
if(d.readyState==="loading"){d.addEventListener("DOMContentLoaded",ready);}else{ready();}
})();
"""

__all__ = [
    "BRIDGE_CSS",
    "BRIDGE_JS",
    "COMMENT_MESSAGE",
    "COMMENT_REMOVE_MESSAGE",
    "COMMENT_STATE_MESSAGE",
    "MAX_COMMENT_CHARS",
    "MAX_QUOTE_CHARS",
    "MAX_WHERE_CHARS",
    "MODE_MESSAGE",
    "READY_MESSAGE",
]
