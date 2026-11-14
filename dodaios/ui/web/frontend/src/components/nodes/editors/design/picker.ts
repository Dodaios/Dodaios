/**
 * The small script the Visuals editor puts into its preview frame.
 *
 * The preview is the design's real page (`POST /api/nodes/{id}/preview`),
 * framed with scripts allowed and no same-origin access, so the app cannot
 * reach into it. This script is the frame's half of a tiny protocol, in
 * `postMessage`s tagged `source: "dodaios-design"`:
 *
 * frame → editor
 * * `ready`: loaded; the editor answers with `state`.
 * * `select {path}`: the reader clicked an element (`path` = element-child
 *   indexes from `<main class="design">`, see `designDoc.ts`), or `null`.
 * * `text {path, html}`: the reader typed into an element in place (after
 *   a double-click) and left it; `html` is its new inline markup.
 * * `scroll {y}`: where the page is scrolled, so a redraw keeps the place.
 * * `key {key, meta, ctrl, shift, alt}`: an editor shortcut pressed while
 *   the frame had the focus (undo, redo, delete, duplicate, move, escape),
 *   which would otherwise never reach the editor.
 *
 * editor → frame
 * * `state {selected, scrollY}`: after a redraw, the place and selection.
 * * `select {path}`: the layers list or the inspector picked an element.
 *
 * A click selects the LAYER the editor lists: a drawing (`<svg>`) as a
 * whole, and a text with inline marks as one text. Links do not navigate
 * and the page's own controls do not react while editing.
 */
export const PICKER_SOURCE = "dodaios-design";

export type PickerMessage =
  | { source: typeof PICKER_SOURCE; type: "ready" }
  | { source: typeof PICKER_SOURCE; type: "select"; path: number[] | null }
  | { source: typeof PICKER_SOURCE; type: "text"; path: number[]; html: string }
  | { source: typeof PICKER_SOURCE; type: "scroll"; y: number }
  | {
      source: typeof PICKER_SOURCE;
      type: "key";
      key: string;
      meta: boolean;
      ctrl: boolean;
      shift: boolean;
      alt: boolean;
    };

/** A message from the frame, checked field by field (it comes from page code). */
export function readPickerMessage(data: unknown): PickerMessage | null {
  if (!data || typeof data !== "object") return null;
  const message = data as Record<string, unknown>;
  if (message.source !== PICKER_SOURCE) return null;
  const isPath = (value: unknown): value is number[] =>
    Array.isArray(value) && value.length <= 64 && value.every((step) => Number.isInteger(step) && step >= 0);
  switch (message.type) {
    case "ready":
      return { source: PICKER_SOURCE, type: "ready" };
    case "select":
      return message.path === null || isPath(message.path)
        ? { source: PICKER_SOURCE, type: "select", path: message.path as number[] | null }
        : null;
    case "text":
      return isPath(message.path) && typeof message.html === "string" && message.html.length <= 200_000
        ? { source: PICKER_SOURCE, type: "text", path: message.path, html: message.html }
        : null;
    case "scroll":
      return typeof message.y === "number" && Number.isFinite(message.y)
        ? { source: PICKER_SOURCE, type: "scroll", y: message.y }
        : null;
    case "key":
      return typeof message.key === "string" && message.key.length <= 20
        ? {
            source: PICKER_SOURCE,
            type: "key",
            key: message.key,
            meta: message.meta === true,
            ctrl: message.ctrl === true,
            shift: message.shift === true,
            alt: message.alt === true,
          }
        : null;
    default:
      return null;
  }
}

/**
 * The frame's script. Plain ES5 in one string: it runs inside the node page,
 * next to the page's own scripts, without any build step. `accent` is the
 * app's selection colour.
 */
export function pickerScript(accent: string): string {
  const colour = JSON.stringify(accent);
  const source = JSON.stringify(PICKER_SOURCE);
  return `(function(){
var root=document.querySelector("main.design");if(!root)return;
var TAG=${source},C=${colour},editing=null,before="",selected=null;
var INLINE=/^(b|strong|i|em|u|s|small|mark|span|a|sub|sup|code|br|abbr|q|cite|time|wbr|del|ins|kbd|var|bdi|bdo)$/;
function send(m){m.source=TAG;try{parent.postMessage(m,"*");}catch(e){}}
function pathOf(el){var p=[];while(el&&el!==root){var up=el.parentElement;if(!up)return null;
p.unshift(Array.prototype.indexOf.call(up.children,el));el=up;}return el===root?p:null;}
function at(path){var n=root;for(var i=0;n&&i<path.length;i++){n=n.children[path[i]];}return n||null;}
function tag(el){return (el.localName||"").toLowerCase();}
function isText(el){if(el.namespaceURI==="http://www.w3.org/2000/svg")return false;
if(/^(img|hr|br|style)$/.test(tag(el)))return false;
for(var i=0;i<el.children.length;i++){var c=el.children[i];if(!INLINE.test(tag(c)))return false;
if(!/^(br|wbr)$/.test(tag(c))&&!isText(c))return false;}return true;}
function layer(el){if(!el||!root.contains(el)||el===root)return null;
var svg=el.closest&&el.closest("svg");if(svg&&root.contains(svg))el=svg;
while(el.parentElement&&el.parentElement!==root&&INLINE.test(tag(el))&&isText(el.parentElement))el=el.parentElement;
return el;}
function box(width,style){var b=document.createElement("div");b.setAttribute("aria-hidden","true");
b.style.cssText="position:fixed;pointer-events:none;z-index:2147483647;display:none;box-sizing:border-box;border-radius:3px;outline:"+width+"px "+style+" "+C+";outline-offset:1px";
document.body.appendChild(b);return b;}
var hoverBox=box(1,"dashed"),selBox=box(2,"solid");
function place(b,el){if(!el||!el.isConnected){b.style.display="none";return;}var r=el.getBoundingClientRect();
b.style.display="block";b.style.left=r.left+"px";b.style.top=r.top+"px";b.style.width=r.width+"px";b.style.height=r.height+"px";}
function show(path,reveal){selected=path?at(path):null;place(selBox,selected);
if(reveal&&selected&&selected.getBoundingClientRect){var r=selected.getBoundingClientRect();
if(r.bottom<0||r.top>innerHeight)selected.scrollIntoView({block:"center"});place(selBox,selected);}}
var hovered=null;
document.addEventListener("mouseover",function(e){if(editing)return;hovered=layer(e.target);place(hoverBox,hovered&&hovered!==selected?hovered:null);},true);
document.addEventListener("mouseleave",function(){hovered=null;place(hoverBox,null);});
function stop(e){e.preventDefault();e.stopPropagation();}
document.addEventListener("click",function(e){if(editing&&editing.contains(e.target))return;stop(e);
if(editing)finish(true);var el=layer(e.target);show(el?pathOf(el):null,false);place(hoverBox,null);
send({type:"select",path:el?pathOf(el):null});},true);
document.addEventListener("submit",stop,true);
document.addEventListener("dblclick",function(e){var el=layer(e.target);if(!el||!isText(el))return;stop(e);start(el);},true);
function start(el){if(editing===el)return;if(editing)finish(true);editing=el;before=el.innerHTML;
el.setAttribute("contenteditable","true");el.style.outline="none";el.focus();place(hoverBox,null);
show(pathOf(el),false);}
function finish(keep){var el=editing;if(!el)return;editing=null;el.removeAttribute("contenteditable");
el.style.outline="";if(!el.getAttribute("style"))el.removeAttribute("style");
if(!keep){el.innerHTML=before;return;}
if(el.innerHTML!==before){var p=pathOf(el);if(p)send({type:"text",path:p,html:el.innerHTML});}}
document.addEventListener("focusout",function(e){if(editing&&e.target===editing)finish(true);},true);
document.addEventListener("paste",function(e){if(!editing)return;e.preventDefault();
var t=(e.clipboardData&&e.clipboardData.getData("text/plain"))||"";document.execCommand("insertText",false,t);},true);
document.addEventListener("keydown",function(e){var mod=e.metaKey||e.ctrlKey,k=e.key;
if(editing){if(k==="Escape"){stop(e);finish(false);return;}
if(k==="Enter"&&!e.shiftKey){stop(e);editing.blur();return;}
if(k==="Enter"&&e.shiftKey){stop(e);document.execCommand("insertLineBreak");}
return;}
if(k==="Enter"&&selected&&isText(selected)){stop(e);start(selected);return;}
var ours=(mod&&/^[zZyYdD]$/.test(k))||k==="Delete"||k==="Backspace"||k==="Escape"||(e.altKey&&/^Arrow(Up|Down)$/.test(k));
if(!ours)return;stop(e);send({type:"key",key:k,meta:e.metaKey,ctrl:e.ctrlKey,shift:e.shiftKey,alt:e.altKey});},true);
var ticking=false;function moved(){if(ticking)return;ticking=true;requestAnimationFrame(function(){ticking=false;
place(selBox,selected);place(hoverBox,hovered&&hovered!==selected?hovered:null);send({type:"scroll",y:scrollY});});}
addEventListener("scroll",moved,true);addEventListener("resize",moved);
addEventListener("message",function(e){if(e.source!==parent)return;var m=e.data;if(!m||m.source!==TAG)return;
if(m.type==="state"){if(typeof m.scrollY==="number")scrollTo(0,m.scrollY);show(m.selected||null,false);}
else if(m.type==="select"){show(m.path||null,true);}});
send({type:"ready"});
})();`;
}
