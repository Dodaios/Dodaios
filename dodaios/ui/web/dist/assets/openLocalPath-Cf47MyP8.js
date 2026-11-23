import{g as n}from"./index-qt2Sny3X.js";/**
 * @license lucide-react v0.445.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const r=n("File",[["path",{d:"M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z",key:"1rqfz7"}],["path",{d:"M14 2v4a2 2 0 0 0 2 2h4",key:"tnqrlb"}]]);async function s(t){if(!t)return!1;try{const a=await fetch("/api/settings/open-path",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path:t})});if(!a.ok)return!1;const e=await a.json().catch(()=>null);return(e==null?void 0:e.opened)===!0}catch{return!1}}export{r as F,s as o};
