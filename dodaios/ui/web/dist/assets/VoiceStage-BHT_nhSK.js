const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["assets/VoiceWorkTrace-BPjjhx2c.js","assets/index-CnoYQJnv.js","assets/modulepreload-polyfill-B5Qt9EMX.js","assets/index-23Jq7HVI.css","assets/WorkTrace-BjiQbool.js","assets/CompanionMark-BthsYYxT.js","assets/appearance-BvqWk9Y7.js","assets/CompanionMark-Baq9f70I.css","assets/ChatMarkdown-BUA2p_Fk.js","assets/traceEntries-CD0G0PWv.js","assets/branding-DPYmWunV.js","assets/vercel-yVSLLUvO.js","assets/pluginLogos-BL-Klizn.js","assets/toolIdentity-BypzoDfW.js","assets/zai-BlqJku11.js","assets/vultr-Blq-qyVO.js","assets/McpLogo-DfDyYD9W.js","assets/terminal-BhbrcW1x.js","assets/wrench-4voHCwJ8.js","assets/compass-BdAmhiQb.js","assets/sparkles-B_iuIkpi.js","assets/plug-CVsvEVcL.js","assets/workflow-D34yE8VP.js","assets/book-open-CeV4YjuR.js","assets/file-text-BlaF3_4v.js","assets/mail-3Cu7zHaG.js","assets/code-xml-CnUkpOf1.js","assets/pen-line-Bb-BqIlc.js","assets/keyboard-BaIj5pqO.js","assets/app-window-CVeZNszm.js","assets/chartSpec-wYX2m_Gn.js","assets/index-J2JBhCQb.js","assets/AgentMark-BA0VRYMJ.js","assets/ProviderLogo-BtwCZiH-.js","assets/server-CteCtxJx.js","assets/CodeBlock-CYXOEg-Y.js","assets/circle-alert-R9Pr-8w2.js","assets/turnError-BDp6L_Fq.js","assets/AgentChatStoreContext-DNvMpBuo.js","assets/ChatPromptCard-rxrDpeus.js","assets/customConnector-B9HX78Md.js","assets/ChatPromptCard-CDERdhS6.css","assets/lock-CGm5zkpk.js","assets/AgentSwatch-ByX8bkLM.js","assets/AgentSwatch-chhgn_XX.css","assets/clock-3-CZOeO1Rp.js","assets/corner-down-left-BPfgZcsx.js","assets/skip-forward-DsgoUwzL.js","assets/turnError-DDogL3YG.css","assets/pencil-ChcGXLGn.js","assets/folder-search-2PMasjyL.js","assets/WorkTrace-BefAWNxz.css","assets/VoiceComposer-BmUt-bgB.js","assets/AgentComposer-1Ix8HkFP.js","assets/arrow-down-CusGUBsm.js","assets/format-CsMfhQ-Z.js","assets/AgentRoutineDetail-50QtDVyt.js","assets/switch-DI_da_PB.js","assets/assistantStatus-BQdEuIZQ.js","assets/data-BdK4cQ4C.js","assets/societyChatGroups-zkfRUJ1n.js","assets/select-CffAKHk2.js","assets/combobox-imiJotqe.js","assets/rotate-cw-B0Uo8CVo.js","assets/eye-off-CN6U7VHg.js","assets/eye-Db6aHhna.js","assets/useModelMenuData-B3l3NSDV.js","assets/agentProviderPrefs-B85mVpcF.js","assets/circle-pause-B3cjqlEL.js","assets/boardInsights-D1zNHBY8.js","assets/prettyProviderName-ClA0unVn.js","assets/BuiltByBadge-DuGl3EOK.js","assets/useSelfBuild-HAn-0PAo.js","assets/selfBuildFocus-1bZPK5SI.js","assets/play-BXhfZd6M.js","assets/pause-Cz0QxXYi.js","assets/folder-D0oa0grk.js","assets/bot-Oqenvf-M.js","assets/film-m3YkmzMD.js","assets/star-B-pGEkYH.js","assets/appshotApi-BklOgPoR.js","assets/audio-lines-Cc62kEJU.js","assets/arrow-up-5OI9nI0G.js","assets/gauge-CsW6ckMQ.js","assets/notebook-pen-CUxGMC5P.js","assets/AgentComposer-D6KMp5ym.css","assets/useVoiceEngineDisplay-DEvrOKHT.js"])))=>i.map(i=>d[i]);
import{r as h,j as o,e as B,ck as ne,cQ as se,cR as U,cS as re,cT as ie,cU as le,_ as G,u as ce,d as V,aG as z,c4 as ue,cV as he,cW as de,bY as fe,f as pe}from"./index-CnoYQJnv.js";import{u as me}from"./assistantStatus-BQdEuIZQ.js";import{u as xe,S as ve}from"./AgentComposer-1Ix8HkFP.js";import{u as we}from"./useWakeWord-DofN74-u.js";import{S as ge}from"./scroll-area-D41pd4i_.js";import{G as be}from"./Greeting-B0E-v9kx.js";import{r as Se}from"./useWebglSurface-ER8cznmO.js";import{L as X}from"./LookSlot-pfZ1GpGi.js";const ye=`
attribute vec2 aPos;
varying vec2 vUv;
void main() {
  vUv = aPos * 0.5 + 0.5;
  gl_Position = vec4(aPos, 0.0, 1.0);
}
`,ke=`
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
varying vec2 vUv;
uniform vec2 uRes;
uniform float uTime;
uniform float uLevel;
uniform float uPulse;
uniform float uPower;
uniform float uLight;
uniform float uSpan;
uniform float uThink;
uniform float uSweep;
uniform float uSweepVel;
uniform vec3 uColor;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

// Value noise over a lattice wrapped at 289 cells: still continuous (the
// wrap happens on whole lattice points), and the hash never sees a number
// large enough to lose its precision, however long a call runs.
float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = p - i;
  i = mod(i, 289.0);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = hash(i);
  float b = hash(mod(i + vec2(1.0, 0.0), 289.0));
  float c = hash(mod(i + vec2(0.0, 1.0), 289.0));
  float d = hash(mod(i + vec2(1.0, 1.0), 289.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

// One comet along x moving at velocity v: the same falloff on both sides
// of the head, the side behind it stretched by its speed. Every length is a
// continuous function of v, so at a turn the tail shrinks into a round
// head and regrows on the other side — it never flips over in one frame
// (a sign(v) switch did exactly that, a visible hitch at both ends).
float comet(float x, float head, float v, float base, float stretch) {
  float o = x - head;
  float len = base + stretch * max(0.0, o > 0.0 ? -v : v);
  return exp(-pow(abs(o) / len, 1.5));
}

float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 4; i++) {
    v += a * noise(p);
    p = p * 2.03 + vec2(1.7, 9.2);
    a *= 0.5;
  }
  return v;
}

void main() {
  vec2 uv = vUv;
  float aspect = uRes.x / max(uRes.y, 1.0);
  float x = (uv.x - 0.5) * aspect;
  float y = uv.y;
  float t = uTime;

  vec2 q = vec2(
    fbm(vec2(x * 0.9 - t * 0.11, t * 0.07)),
    fbm(vec2(x * 0.9 + 3.1 + t * 0.09, 1.7 - t * 0.05))
  );
  float crest = fbm(vec2(x * 1.1 + q.x * 1.6 - t * 0.06, q.y * 1.4 + t * 0.12));

  float dx = (uv.x - 0.5) / uSpan;
  float dome = exp(-dx * dx * 1.4);

  // Thinking: two comets mirrored about the middle, each with a tail that
  // stretches with its speed. Screen-blended, not summed, so where they
  // cross the light swells instead of blowing out.
  // The turn points stay clear of the side fade, so a head is never
  // dimmed or cut off by the edge while it slows down and turns.
  float reach = min(uSpan * 0.95, 0.34);
  float width = uSpan * 0.14;
  float h1 = 0.5 + reach * uSweep;
  float h2 = 0.5 - reach * uSweep;
  float b1 = comet(uv.x, h1, uSweepVel, width, uSpan * 0.55);
  float b2 = comet(uv.x, h2, -uSweepVel, width, uSpan * 0.55);
  float lateral = 1.0 - (1.0 - b1) * (1.0 - b2);
  float beams = lateral * uThink;
  float beam = beams * (exp(-y / 0.13) + 0.4 * exp(-y / 0.4));
  float headWidth = width * 0.6;
  float heads = (exp(-pow((uv.x - h1) / headWidth, 2.0)) + exp(-pow((uv.x - h2) / headWidth, 2.0))) * uThink;
  float hot = heads * exp(-y / 0.06);

  // Where they meet: a pillar of light shoots up through the middle and a
  // wide bloom lifts the whole haze for a moment.
  float meet = uThink * exp(-pow(uSweep / 0.22, 2.0));
  float pillar = exp(-pow((uv.x - 0.5) / (uSpan * 0.1), 2.0)) * exp(-y / (0.18 + 0.6 * meet)) * meet;
  float bloom = exp(-pow((uv.x - 0.5) / (uSpan * 0.7), 2.0)) * exp(-y / 0.45) * meet;
  float flare = pillar + 0.5 * bloom;

  // Sparks: one candidate per cell of a grid that scrolls upward; about
  // half the cells hold one, each twinkling on its own, lit only above a
  // comet or its tail and fading as it rises.
  vec2 sp = vec2(x * 16.0, y * 6.0 - t * 1.4);
  vec2 cell = mod(floor(sp), 289.0);
  vec2 f = fract(sp);
  float r = hash(cell);
  vec2 at = 0.2 + 0.6 * vec2(hash(cell + vec2(3.1, 1.7)), hash(cell + vec2(7.7, 5.3)));
  vec2 d = (f - at) / vec2(16.0, 6.0);
  float twinkle = 0.55 + 0.45 * sin(t * 7.0 + r * 40.0);
  float spark = exp(-dot(d, d) / (0.009 * 0.009)) * step(0.55, r) * twinkle;
  float sparks = spark * lateral * exp(-y / 0.38) * uThink;

  float h = (1.0 + 0.6 * beams + 0.8 * meet) * (0.34 + 0.42 * uLevel) * (0.6 + 0.8 * crest) * (0.3 + 0.7 * dome);
  float body = exp(-pow(y / max(h, 0.02), 1.35) * 1.7);

  float rays = smoothstep(0.2, 0.85, fbm(vec2(x * 2.6 + q.x * 2.2, y * 0.9 - t * 0.35)));
  float shimmer = 0.75 + 0.5 * rays;

  float core = exp(-y / (0.05 + 0.1 * uPulse)) * dome;

  float a = body * shimmer * (0.3 + 0.7 * dome) + core * (0.2 + 0.6 * uPulse)
    + beam * 0.8 + hot * 0.9 + flare * 0.9 + sparks * 1.4;
  a *= (0.3 + 0.7 * uPower) * (0.65 + 0.55 * uLevel);
  a *= smoothstep(0.0, 0.12, uv.x) * (1.0 - smoothstep(0.88, 1.0, uv.x)) * (1.0 - smoothstep(0.45, 1.0, y));

  float lift = clamp(
    core * 0.8 + beam * 0.5 + hot * 1.2 + flare + sparks * 2.0 + rays * body * 0.35,
    0.0,
    1.0
  );
  vec3 deep = uColor * (0.75 + 0.25 * uLight);
  // Highlights go toward a cool white, so the hottest light stays blue-born.
  vec3 bright = mix(uColor, vec3(0.82, 0.93, 1.0), 0.6 - 0.4 * uLight);
  vec3 col = mix(deep, bright, lift);

  a = a * (0.55 - 0.2 * uLight);
  a += (hash(gl_FragCoord.xy + fract(t)) - 0.5) / 255.0;
  a = clamp(a, 0.0, 1.0);
  gl_FragColor = vec4(col * a, a);
}
`,_e=.5,Ee=900,Re=520;function K(t,e,s){const a=t.createShader(e);return a?(t.shaderSource(a,s),t.compileShader(a),!t.getShaderParameter(a,t.COMPILE_STATUS)&&!t.isContextLost()?(console.warn("[voice-glow] shader failed to compile:",t.getShaderInfoLog(a)),t.deleteShader(a),null):a):null}function Te(t){let e=null;try{e=t.getContext("webgl",{alpha:!0,premultipliedAlpha:!0,antialias:!1,depth:!1,stencil:!1,preserveDrawingBuffer:!1,powerPreference:"low-power"})}catch(u){return console.warn("[voice-glow] WebGL context unavailable:",u),null}if(!e||e.isContextLost())return null;const s=K(e,e.VERTEX_SHADER,ye),a=K(e,e.FRAGMENT_SHADER,ke),n=e.createProgram();if(!s||!a||!n)return null;if(e.attachShader(n,s),e.attachShader(n,a),e.linkProgram(n),e.deleteShader(s),e.deleteShader(a),!e.getProgramParameter(n,e.LINK_STATUS))return e.isContextLost()||console.warn("[voice-glow] shader program failed to link:",e.getProgramInfoLog(n)),e.deleteProgram(n),null;const i=e.createBuffer();e.bindBuffer(e.ARRAY_BUFFER,i),e.bufferData(e.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),e.STATIC_DRAW);const c=e.getAttribLocation(n,"aPos"),m=e,l=u=>m.getUniformLocation(n,u),x=l("uRes"),v=l("uTime"),f=l("uLevel"),y=l("uPulse"),w=l("uPower"),g=l("uLight"),p=l("uSpan"),d=l("uColor"),b=l("uThink"),T=l("uSweep"),M=l("uSweepVel");let j=1,A=1;return{resize(u,R){const k=Math.min(_e,Ee/Math.max(u,1)),E=Math.max(1,Math.round(u*k)),_=Math.max(1,Math.round(R*k));return j=Math.max(u,1),A=Math.max(R,1),t.width===E&&t.height===_?!1:(t.width=E,t.height=_,!0)},render(u){!e||e.isContextLost()||(e.viewport(0,0,t.width,t.height),e.useProgram(n),e.bindBuffer(e.ARRAY_BUFFER,i),e.enableVertexAttribArray(c),e.vertexAttribPointer(c,2,e.FLOAT,!1,0,0),e.uniform2f(x,j,A),e.uniform1f(v,u.time),e.uniform1f(f,u.level),e.uniform1f(y,u.pulse),e.uniform1f(w,u.power),e.uniform1f(b,u.think),e.uniform1f(T,u.sweep),e.uniform1f(M,u.sweepVel),e.uniform1f(g,u.light?1:0),e.uniform1f(p,Math.min(.45,Re/j)),e.uniform3f(d,u.color[0]/255,u.color[1]/255,u.color[2]/255),e.clearColor(0,0,0,0),e.clear(e.COLOR_BUFFER_BIT),e.drawArrays(e.TRIANGLES,0,3))},dispose(){!e||e.isContextLost()||(e.deleteBuffer(i),e.deleteProgram(n))}}}const je=.06,Ae=.45,Le=.12,Me=.03,Pe=.18,D=(t,e,s,a)=>t+(e-t)*(1-Math.exp(-s/a));function J(){let t=0,e=0,s=0;return{step(a,n){const i=Number.isFinite(n)?Math.min(1,Math.max(0,n)):0;return t=D(t,i,a,i>t?je:Ae),e=D(e,t,a,Le),s=D(s,i,a,i>s?Me:Pe),{level:Math.pow(e,.7),pulse:Math.pow(s,.7)}}}}function Y({active:t,thinking:e=!1,className:s}){const[a,n]=h.useState(Ne);return o.jsx("div",{"aria-hidden":!0,"data-testid":"voice-glow","data-renderer":a?"webgl":"css",className:B("pointer-events-none absolute inset-x-0 bottom-0 h-[38vh] overflow-hidden",s),children:a?o.jsx(Ie,{active:t,thinking:e,onUnavailable:()=>n(!1)}):o.jsx(We,{active:t,thinking:e})})}function Ne(){return typeof window<"u"&&typeof window.WebGLRenderingContext<"u"}function Z(){return typeof window.matchMedia=="function"&&window.matchMedia("(prefers-reduced-motion: reduce)").matches}function ee(t){return Math.max(se.current??0,ne(t))}const Fe=.5,Ce=.35,Ve=1.4,te=2.1;function ae(t,e){return t*(.24+.08*Math.sin(e))}const I=new Map;function Ie({active:t,thinking:e,onUnavailable:s}){const a=h.useRef(null),n=h.useRef(t),i=h.useRef(e),c=h.useRef(()=>{}),m=h.useRef(s);return h.useEffect(()=>{m.current=s},[s]),h.useEffect(()=>{n.current=t,i.current=e,c.current()},[t,e]),h.useEffect(()=>{const l=a.current;if(!l)return;const x=I.get(l);x!==void 0&&(window.clearTimeout(x),I.delete(l));const v=Te(l);if(!v){m.current();return}const f=Z(),y=J();let w={level:0,pulse:0},g=12,p=0,d=0,b=0,T=0,M=[61,139,255],j=!1,A=0,u=-1,R=0,k=!1;const E=()=>{const S=getComputedStyle(l).getPropertyValue("--accent-rgb").trim().split(/[\s,]+/).map(Number);S.length>=3&&S.slice(0,3).every(Number.isFinite)&&(M=[S[0],S[1],S[2]]),j=l.closest(".dark")===null},_=()=>v.render({time:g,level:Math.max(w.level,ae(d,T)),pulse:w.pulse,think:d,sweep:Math.sin(b),sweepVel:Math.cos(b),power:p,light:j,color:M}),r=S=>{const L=u<0?0:Math.min(.1,(S-u)/1e3);u=S;const C=n.current;w=y.step(L,C?ee(S):0),p+=((C?1:0)-p)*(1-Math.exp(-L/Fe));const $=C&&i.current;if(d+=(($?1:0)-d)*(1-Math.exp(-L/Ce)),d<.002&&!$?(d=0,b=0):(b+=L*Ve,T+=L*te),g+=L*(.55+Math.max(w.level,d*.3)*1.4),A+=L,A>.5&&(A=0,E()),!C&&p<.002&&d===0&&w.level<.002&&w.pulse<.002){p=0,w={level:0,pulse:0},_(),k=!1;return}_(),R=requestAnimationFrame(r)},F=()=>{if(f||typeof requestAnimationFrame>"u"){p=n.current?1:0,d=n.current&&i.current?1:0,E(),_();return}k||(k=!0,u=-1,R=requestAnimationFrame(r))};c.current=F;const H=()=>{const S=l.getBoundingClientRect();v.resize(S.width,S.height)&&!k&&_()};E(),H(),_(),F();const P=typeof ResizeObserver<"u"?new ResizeObserver(H):null;P==null||P.observe(l);const N=typeof MutationObserver<"u"?new MutationObserver(()=>{E(),k||_()}):null;N==null||N.observe(document.documentElement,{attributes:!0,attributeFilter:["class","style","data-theme"]});const q=S=>{S.preventDefault(),cancelAnimationFrame(R),k=!1,m.current()};return l.addEventListener("webglcontextlost",q),()=>{c.current=()=>{},cancelAnimationFrame(R),k=!1,P==null||P.disconnect(),N==null||N.disconnect(),l.removeEventListener("webglcontextlost",q),v.dispose(),I.set(l,window.setTimeout(()=>{I.delete(l),Se(l)},0))}},[]),o.jsx("canvas",{ref:a,className:"absolute inset-0 h-full w-full"})}function We({active:t,thinking:e}){const s=h.useRef([]);return h.useEffect(()=>{const a=s.current.filter(f=>f!==null);if(!t||Z()||typeof requestAnimationFrame>"u"){a.forEach(f=>{f.style.opacity=t?"0.7":"0.3",f.style.transform="translateX(-50%)"});return}const n=J();let i=-1,c=0;const m=W.map(f=>f.phase),l=W.map(f=>f.phase*2);let x=0;const v=f=>{const y=i<0?0:Math.min(.1,(f-i)/1e3);i=f,x+=y*te;const w=Math.max(n.step(y,ee(f)).level,ae(e?1:0,x));W.forEach((g,p)=>{const d=a[p];if(!d)return;m[p]+=y*g.speed*(1+w*1.2),l[p]+=y*g.speed*1.3;const b=Math.sin(m[p])*(g.drift+w*5),T=.5+.5*Math.sin(l[p]);d.style.opacity=Math.min(1,.5+w*.45+T*.08).toFixed(3),d.style.transform=`translateX(calc(-50% + ${b.toFixed(2)}%)) scale(${(1+w*.1).toFixed(3)}, ${(1+w*g.lift).toFixed(3)})`}),c=requestAnimationFrame(v)};return c=requestAnimationFrame(v),()=>cancelAnimationFrame(c)},[t,e]),o.jsx(o.Fragment,{children:W.map((a,n)=>o.jsx("div",{ref:i=>{s.current[n]=i},className:B("absolute bottom-0 origin-bottom will-change-[transform,opacity]",!t&&"transition-[opacity,transform] duration-700 ease-out"),style:{left:`${a.x}%`,width:a.width,height:a.height,transform:"translateX(-50%)",opacity:.3,background:Be(a.alpha)}},n))})}const W=[{x:50,width:"min(760px, 90%)",height:"100%",alpha:.26,speed:.35,phase:0,drift:2,lift:.3},{x:40,width:"min(420px, 55%)",height:"80%",alpha:.22,speed:.6,phase:2.1,drift:5,lift:.5},{x:60,width:"min(420px, 55%)",height:"75%",alpha:.2,speed:.75,phase:4.2,drift:5,lift:.55}];function Be(t){return`radial-gradient(ellipse 50% 70% at 50% 100%, ${[[1,0],[.86,12],[.66,24],[.45,36],[.27,48],[.14,59],[.06,69],[.02,78],[0,88]].map(([s,a])=>`rgb(var(--accent-rgb) / ${(t*s).toFixed(3)}) ${a}%`).join(", ")})`}function Ge(t,e,s=""){var m,l;const a=h.useSyncExternalStore(U,re),n=h.useSyncExternalStore(U,()=>ie(s)),i=h.useSyncExternalStore(U,le),c=h.useRef(null);if(c.current&&c.current.text!==t&&(c.current=null),n){let x=n.text===t?n.chars:0;if(n.text!==t){const v=Math.min(n.chars,t.length);for(;x<v&&n.text[x]===t[x];)x++;const f=t.charCodeAt(x-1);f>=55296&&f<=56319&&x--}c.current={id:-1,text:t,chars:x}}else!c.current&&e&&i&&s.startsWith(`live:${i}:`)&&(c.current={id:-1,text:t,chars:0});return(a==null?void 0:a.text)===t&&(a.id===((m=c.current)==null?void 0:m.id)||e&&a.state!=="ended"&&a.state!=="cancelled")&&(c.current={id:a.id,text:t,chars:a.chars}),(n==null?void 0:n.text)===t?n.chars:((l=c.current)==null?void 0:l.chars)??null}const Ue=()=>G(()=>import("./VoiceWorkTrace-BPjjhx2c.js"),__vite__mapDeps([0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51])).then(t=>({default:t.VoiceWorkTrace})),De=h.lazy(Ue);function oe(t,e,s){return s?!0:t.length===0?!1:t.some(n=>n.status==="error"||n.kind!=="brain"&&n.kind!=="note")||(e??0)>=1e3}function Oe({steps:t,live:e=!1,durationMs:s,className:a}){return oe(t,s,e)?o.jsx(h.Suspense,{fallback:null,children:o.jsx(De,{steps:t,live:e,durationMs:s,className:a})}):null}const He=h.lazy(()=>G(()=>import("./VoiceComposer-BmUt-bgB.js"),__vite__mapDeps([52,1,2,3,53,54,38,55,56,57,58,59,60,61,62,63,64,65,66,67,68,47,69,70,71,72,73,74,75,32,15,14,33,34,39,13,12,11,16,17,18,19,20,21,22,23,24,25,26,27,28,29,40,41,43,6,5,7,44,76,77,8,9,10,30,31,35,36,78,79,80,81,82,83,84,85,86])).then(t=>({default:t.VoiceComposer}))),qe=h.lazy(()=>G(()=>import("./AgentComposer-1Ix8HkFP.js").then(t=>t.x),__vite__mapDeps([53,1,2,3,54,38,55,56,57,58,59,60,61,62,63,64,65,66,67,68,47,69,70,71,72,73,74,75,32,15,14,33,34,39,13,12,11,16,17,18,19,20,21,22,23,24,25,26,27,28,29,40,41,43,6,5,7,44,76,77,8,9,10,30,31,35,36,78,79,80,81,82,83,84,85])).then(t=>({default:t.MessageAttachments})));function Q({hint:t,onExit:e}){return o.jsx(h.Suspense,{fallback:o.jsx("div",{className:"h-[72px] w-full"}),children:o.jsx(He,{hint:t,onExit:e})})}const $e=h.lazy(()=>G(()=>import("./ChatMarkdown-BUA2p_Fk.js").then(t=>t.b),__vite__mapDeps([8,1,2,3,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36])).then(t=>({default:t.ChatMarkdown})));function ot({onExit:t}={}){const e=ce(),s=V(r=>r.assistantName),a=V(r=>r.voiceState),n=z(r=>r.transcript),i=z(r=>r.liveReply),c=V(r=>r.transcription),m=V(r=>r.transcriptionFinal),{connected:l,warming:x}=ue(),{active:v,connecting:f}=me(),{config:y}=we(),w=(y==null?void 0:y.phrase.trim())||"",g=h.useMemo(()=>n.filter(r=>r.who!=="steps"||oe(r.steps,r.durationMs,r.live)),[n]),p=c&&!m?c:"",d=g[g.length-1],b=i&&!((d==null?void 0:d.who)==="assistant"&&d.text.startsWith(i))?i:"",T=g.length>0||!!p||!!b,M=!b&&(d==null?void 0:d.who)==="assistant",j=g.some(r=>r.who==="steps"&&r.live),{rootRef:A,contentRef:u,atEnd:R,jumpToEnd:k,follow:E}=xe();h.useLayoutEffect(E,[E,g,p,b]);const _=Xe({connected:l,warming:x,connecting:f,voiceState:a,wakePhrase:w,t:e});return T?o.jsxs("div",{className:"relative flex min-h-0 flex-1 flex-col items-center overflow-hidden","data-testid":"voice-stage","data-empty":"false",children:[o.jsx(X,{state:a??"idle",className:"absolute inset-x-0 bottom-0 h-[38vh] w-full",children:o.jsx(Y,{active:v,thinking:a==="thinking"})}),o.jsx(ge,{ref:A,className:"relative min-h-0 w-full flex-1","data-testid":"voice-transcript",children:o.jsxs("div",{ref:u,className:"mx-auto flex w-full max-w-[720px] flex-col gap-6 px-6 pb-6 pt-8","aria-live":"polite",children:[g.map((r,F)=>r.who==="steps"?o.jsx("div",{className:"max-w-[85%] pl-1","data-testid":"transcript-steps",children:o.jsx(Oe,{steps:r.steps,live:r.live,durationMs:r.durationMs,model:he(r.steps),compact:!0,defaultOpen:r.live})},r.id):r.kind===de&&r.markdown?o.jsx(ze,{title:r.text,markdown:r.markdown},r.id):o.jsx(O,{who:r.who==="user"?e("home.transcript_you"):s,text:r.text,attachments:r.attachments,lineId:r.id,user:r.who==="user",playbackEligible:v&&M&&F===g.length-1},r.id)),p&&o.jsx(O,{who:e("home.transcript_you"),text:p,user:!0,live:!0}),b&&o.jsx(O,{who:s,text:b,user:!1,live:!0,playbackEligible:v}),v&&(a==="thinking"||a==="speaking")&&!j&&o.jsx("div",{className:"pl-0.5","data-testid":"voice-turn-indicator","aria-hidden":!0,children:o.jsx(fe,{size:48,state:a==="speaking"?"talking":"working"})})]})}),o.jsxs("div",{className:"relative w-full max-w-[720px] px-6 pb-4 pt-2",children:[!R&&o.jsx(ve,{onClick:k,testId:"voice-scroll-end"}),o.jsx(Q,{hint:_,onExit:t})]})]}):o.jsxs("div",{className:"relative flex min-h-0 flex-1 flex-col items-center overflow-hidden","data-testid":"voice-stage","data-empty":"true",children:[o.jsx(X,{state:a??"idle",className:"absolute inset-x-0 bottom-0 h-[38vh] w-full",children:o.jsx(Y,{active:v,thinking:a==="thinking"})}),o.jsxs("div",{className:"relative flex w-full max-w-[680px] flex-1 flex-col justify-center gap-7 px-6 pb-[14vh]",children:[o.jsx(be,{subtitle:e("home.voice_subtitle")}),o.jsx(Q,{hint:_,onExit:t})]})]})}function O({who:t,text:e,user:s,live:a=!1,playbackEligible:n=!1,lineId:i="",attachments:c=[]}){const m=Ge(e,!s&&n,i),l=!s&&m!==null;return o.jsxs("div",{className:B("flex",s?"justify-end":"justify-start"),"data-testid":a?s?"transcript-live":"transcript-live-answer":"transcript-line","data-who":s?"user":"assistant",children:[o.jsxs("span",{className:"sr-only",children:[t,": "]}),o.jsxs("div",{className:B("min-w-0 max-w-[80%] whitespace-pre-wrap text-reading",s?"jarvis-user-bubble rounded-[20px] px-4 py-2.5 italic":"text-foreground",a&&!l&&(s?"opacity-70":"text-muted-foreground")),children:[l?o.jsxs(o.Fragment,{children:[o.jsx("span",{"data-testid":"spoken-part",children:e.slice(0,m)}),o.jsx("span",{className:"text-muted-foreground","data-testid":"unspoken-part",children:e.slice(m)})]}):e,s&&c.length>0&&o.jsx(h.Suspense,{fallback:null,children:o.jsx(qe,{files:c})}),a&&!l&&o.jsx("span",{className:"ml-0.5 inline-block h-[1em] w-0.5 translate-y-0.5 animate-pulse bg-current motion-reduce:animate-none","aria-hidden":!0})]})]})}function ze({title:t,markdown:e}){return o.jsx("div",{className:"flex justify-start","data-testid":"transcript-shown","data-who":"assistant",children:o.jsxs("div",{className:"w-full min-w-0 rounded-2xl border border-border bg-card px-4 py-3 text-card-foreground",children:[t&&o.jsx("div",{className:"mb-2 text-sm font-medium text-foreground",children:t}),o.jsx(h.Suspense,{fallback:o.jsx("pre",{className:"whitespace-pre-wrap text-sm",children:e}),children:o.jsx($e,{text:e,className:"prose prose-sm max-w-none overflow-x-auto dark:prose-invert"})})]})})}function Xe({connected:t,warming:e,connecting:s,voiceState:a,wakePhrase:n,t:i}){if(!t)return i(e?"home.hint_warming":"home.hint_offline");if(e)return i("home.hint_warming");if(s)return i("home.hint_connecting");switch(a){case"listening":return i("home.hint_listening");case"thinking":return i("home.hint_thinking");case"speaking":return i("home.hint_speaking");case"paused":return i("home.hint_paused");case"error":return i("home.hint_error");default:return n?pe(i("home.hint_idle"),{wake:n}):i("home.hint_idle_nowake")}}export{O as T,ot as V,Y as a};
