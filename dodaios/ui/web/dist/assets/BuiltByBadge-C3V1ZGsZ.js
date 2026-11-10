import{c as l,u as c,cY as b,j as t,cZ as h,e as f}from"./index-DvlJANFD.js";import{o as x}from"./selfBuildFocus-D4Y9zzhk.js";/**
 * @license lucide-react v0.445.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const k=l("Link2",[["path",{d:"M9 17H7A5 5 0 0 1 7 7h2",key:"8i5ue5"}],["path",{d:"M15 7h2a5 5 0 1 1 0 10h-2",key:"1b9ql8"}],["line",{x1:"8",x2:"16",y1:"12",y2:"12",key:"1jonct"}]]);/**
 * @license lucide-react v0.445.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const m=l("RotateCw",[["path",{d:"M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8",key:"1p45f6"}],["path",{d:"M21 3v5h-5",key:"1q7to0"}]]);function y({type:r,id:o,compact:a=!1,className:d}){const s=c(),e=b(r,o);if(!e)return null;const n=s("self_build_badge.label"),i=e.state==="trial";return t.jsxs("button",{type:"button","data-testid":"built-by-badge","data-build-id":e.build_id,"data-state":e.state,title:`${s("self_build_badge.title")}${i?` (${s("self_build_badge.trial")})`:""}${e.title?` — ${e.title}`:""}`,"aria-label":n,onClick:u=>{u.stopPropagation(),x(e.build_id)},className:f("inline-flex shrink-0 items-center gap-1 rounded-full border border-border text-xs text-muted-foreground transition-colors","hover:border-border-strong hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",a?"h-5 px-1.5":"h-6 px-2",d),children:[t.jsx(h,{"aria-hidden":!0,className:"h-3 w-3",strokeWidth:1.8}),!a&&t.jsx("span",{className:"truncate",children:n}),i&&!a&&t.jsxs("span",{className:"text-accent",children:["· ",s("self_build_badge.trial")]}),i&&a&&t.jsx("span",{"aria-hidden":!0,className:"h-1.5 w-1.5 rounded-full bg-accent"})]})}export{y as B,k as L,m as R};
