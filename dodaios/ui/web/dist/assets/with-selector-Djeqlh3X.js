import{e1 as I,cW as M}from"./index-LKdwk8bH.js";var R={exports:{}},b={},x={exports:{}},j={};/**
 * @license React
 * use-sync-external-store-shim.production.js
 *
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */var D;function U(){if(D)return j;D=1;var n=I();function S(e,r){return e===r&&(e!==0||1/e===1/r)||e!==e&&r!==r}var m=typeof Object.is=="function"?Object.is:S,h=n.useState,p=n.useEffect,E=n.useLayoutEffect,y=n.useDebugValue;function w(e,r){var u=r(),o=h({inst:{value:u,getSnapshot:r}}),t=o[0].inst,f=o[1];return E(function(){t.value=u,t.getSnapshot=r,l(t)&&f({inst:t})},[e,u,r]),p(function(){return l(t)&&f({inst:t}),e(function(){l(t)&&f({inst:t})})},[e]),y(u),u}function l(e){var r=e.getSnapshot;e=e.value;try{var u=r();return!m(e,u)}catch{return!0}}function i(e,r){return r()}var a=typeof window>"u"||typeof window.document>"u"||typeof window.document.createElement>"u"?i:w;return j.useSyncExternalStore=n.useSyncExternalStore!==void 0?n.useSyncExternalStore:a,j}var O;function C(){return O||(O=1,x.exports=U()),x.exports}/**
 * @license React
 * use-sync-external-store-shim/with-selector.production.js
 *
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */var g;function G(){if(g)return b;g=1;var n=I(),S=C();function m(i,a){return i===a&&(i!==0||1/i===1/a)||i!==i&&a!==a}var h=typeof Object.is=="function"?Object.is:m,p=S.useSyncExternalStore,E=n.useRef,y=n.useEffect,w=n.useMemo,l=n.useDebugValue;return b.useSyncExternalStoreWithSelector=function(i,a,e,r,u){var o=E(null);if(o.current===null){var t={hasValue:!1,value:null};o.current=t}else t=o.current;o=w(function(){function V(c){if(!_){if(_=!0,v=c,c=r(c),u!==void 0&&t.hasValue){var s=t.value;if(u(s,c))return d=s}return d=c}if(s=d,h(v,c))return s;var q=r(c);return u!==void 0&&u(s,q)?(v=c,s):(v=c,d=q)}var _=!1,v,d,W=e===void 0?null:e;return[function(){return V(a())},W===null?void 0:function(){return V(W())}]},[a,e,r,u]);var f=p(i,o[0],o[1]);return y(function(){t.hasValue=!0,t.value=f},[f]),l(f),f},b}var z;function L(){return z||(z=1,R.exports=G()),R.exports}var $=L();const F=M($);export{C as r,F as u,$ as w};
