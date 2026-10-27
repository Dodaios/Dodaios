import{c as m}from"./index-DHS1QMpG.js";/**
 * @license lucide-react v0.445.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const h=m("History",[["path",{d:"M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8",key:"1357e3"}],["path",{d:"M3 3v5h5",key:"1xhq8a"}],["path",{d:"M12 7v5l4 2",key:"1fdv2h"}]]),i="jarvis-native-drop",u=2e3;function d(){const n=window;return!!(n.__JARVIS_EMBEDDED_DESKTOP||n.pywebview)}function E(n={}){if(!d())return Promise.resolve(null);const c=n.timeoutMs??u;return new Promise(s=>{let t;const o=w=>{const e=w.detail,a=Array.isArray(e==null?void 0:e.paths)?e.paths:[],r=Array.isArray(e==null?void 0:e.names)?e.names:[];a.length!==0&&(n.name&&r.length>0&&!r.includes(n.name)||(window.removeEventListener(i,o),t!==void 0&&window.clearTimeout(t),s({paths:a,names:r})))};window.addEventListener(i,o),t=window.setTimeout(()=>{window.removeEventListener(i,o),s(null)},c)})}export{h as H,d as i,E as w};
