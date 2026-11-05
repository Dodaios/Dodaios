import test from "node:test";
import assert from "node:assert/strict";
import {inspectPage} from "../../dodaios/assets/chrome-extension/page.mjs";
import {webcrypto} from "node:crypto";

const store = {}, calls = [], tabs = new Map();
let nextTab = 40, idleState = "active", onTarget = null;
let page = {url: "https://example.com/", identity: "", blocked: false, observation_id: "fresh"};
const event = () => ({addListener() {}});
const listeners = {};
const captured = (name) => ({addListener(listener) { listeners[name] = listener; }});
const downloadItems = new Map();
let failCancel = false;
const storage = {setAccessLevel: async () => {}, get: async (key) => ({[key]: store[key]}),
  set: async (value) => Object.assign(store, value), remove: async (key) => { delete store[key]; }};
globalThis.chrome = {
  storage: {local: storage, session: storage},
  idle: {queryState: async () => idleState},
  tabs: {
    create: async (value) => { const tab = {id: nextTab++, windowId: 1, active: true, url: value.url}; tabs.set(tab.id, tab); return tab; },
    get: async (id) => { if (!tabs.has(id)) throw new Error("missing"); return tabs.get(id); },
    update: async (id, value) => { Object.assign(tabs.get(id), value); calls.push(["navigate", id, value]); },
    remove: async (id) => { tabs.delete(id); calls.push(["remove", id]); },
    onRemoved: event(),
  },
  windows: {get: async () => ({focused: true, state: "normal"}), update: async () => {}},
  debugger: {
    attach: async (target) => { calls.push(["attach", target.tabId]); },
    detach: async (target) => { calls.push(["detach", target.tabId]); },
    sendCommand: async (target, method, args) => {
      calls.push([method, target.tabId, args]);
      // Chrome 156 refuses these to extensions; they used to break every ensure.
      if (method === "Page.setDownloadBehavior") throw new Error("Cannot not access browser-level commands");
      if (method.startsWith("Browser.")) throw new Error(`'${method}' wasn't found`);
      if (method === "Page.getFrameTree") return {frameTree: {frame: {id: "main"}}};
      if (method === "Page.createIsolatedWorld") return {executionContextId: 1};
      if (method === "Runtime.evaluate") {
        const mode = JSON.parse(args.expression.match(/\}\)\(("[^"]+")/)[1]);
        if (mode === "target") {
          onTarget?.();
          return {result: {value: {x: 10, y: 10, href: "", target: "", editable: true}}};
        }
        return {result: {value: {...page}}};
      }
      if (method === "Page.captureScreenshot") return {data: "fake-jpeg"};
      return {};
    }, onDetach: event(), onEvent: captured("debugger.onEvent"),
  },
  downloads: {
    onCreated: captured("downloads.onCreated"),
    search: async (query) => [...downloadItems.values()].filter((item) => (query.id === undefined || item.id === query.id)
      && (query.url === undefined || item.url === query.url)
      && (query.startedAfter === undefined || item.startTime === undefined || item.startTime > query.startedAfter))
      .sort((a, b) => String(b.startTime).localeCompare(String(a.startTime))).slice(0, query.limit),
    cancel: async (id) => { calls.push(["downloads.cancel", id]); if (failCancel) throw new Error("cancel failed"); },
    removeFile: async (id) => { calls.push(["downloads.removeFile", id]); },
    erase: async (query) => { calls.push(["downloads.erase", query.id]); return [query.id]; },
  },
  declarativeNetRequest: {updateSessionRules: async (value) => { calls.push(["rules", value]); }},
  runtime: {id: "test-extension", getURL: (path) => `chrome-extension://test-extension/${path}`, onMessage: event(), onStartup: event()},
  alarms: {onAlarm: event(), create: async () => {}, clear: async () => {}},
};
const {dispatch} = await import("../../dodaios/assets/chrome-extension/background.mjs");

async function session(domains = ["example.com"]) {
  const id = nextTab.toString(16).padStart(32, "0");
  const result = await dispatch({op: "ensure", args: {session_id: id, allowed_domains: domains}});
  const call = (op, args = {}) => dispatch({op, args: {session_id: id, ...args}});
  return {id, tabId: Number(result.target), call};
}

test("ensure creates a visible owned tab and installs redirect-blocking rules before debugger attachment", async () => {
  const start = calls.length;
  const current = await session();
  assert.equal(tabs.get(current.tabId).active, true);
  const created = calls.slice(start);
  const rule = created.find(([name]) => name === "rules")[1].addRules[0];
  assert.deepEqual(rule.condition.tabIds, [current.tabId]);
  assert.deepEqual(rule.condition.resourceTypes, ["main_frame", "sub_frame"]);
  assert.deepEqual(rule.condition.excludedRequestDomains, ["example.com"]);
  assert.ok(created.findIndex(([name]) => name === "rules") < created.findIndex(([name]) => name === "attach"));
  await current.call("shutdown");
  assert.equal(tabs.has(current.tabId), false);
});

test("actions never attach to unrelated tabs or accept arbitrary CDP", async () => {
  await assert.rejects(dispatch({op: "action", args: {session_id: "a".repeat(32), action: {navigate: {url: "https://example.com"}}, tabId: 1}}));
  const current = await session();
  await assert.rejects(current.call("Runtime.evaluate", {expression: "untrusted"}));
  await assert.rejects(current.call("action", {action: {evaluate: {expression: "untrusted"}}}));
  assert.equal(calls.some(([op, id]) => op === "attach" && id === 1), false);
  await current.call("shutdown");
});

test("stale account or page invalidates previously approved actions", async () => {
  const current = await session();
  page = {url: "https://example.com/", identity: "@original", blocked: false, observation_id: "fresh"};
  await current.call("observe");
  page.identity = "@different";
  const before = calls.length;
  await assert.rejects(current.call("action", {action: {click: {index: 1}}, expected_url: page.url,
    expected_identity: "@original", observation_id: "fresh"}));
  assert.equal(calls.slice(before).some(([op]) => op.startsWith("Input.")), false);
  await current.call("shutdown");
});

test("a dispatched action consumes its observation and cannot be replayed", async () => {
  const current = await session();
  page = {url: "https://example.com/", identity: "", blocked: false, observation_id: "fresh"};
  await current.call("observe");
  const action = {action: {click: {index: 1}}, expected_url: page.url, observation_id: "fresh"};
  await current.call("action", action);
  const before = calls.length;
  await assert.rejects(current.call("action", action));
  assert.equal(calls.slice(before).some(([op]) => op.startsWith("Input.")), false);
  await current.call("shutdown");
});

test("an account switch during target lookup stops the click before mousePressed", async () => {
  const current = await session();
  page = {url: "https://example.com/", identity: "@original", blocked: false, observation_id: "fresh"};
  await current.call("observe");
  onTarget = () => { page.identity = "@changed"; };
  const before = calls.length;
  try {
    await assert.rejects(current.call("action", {action: {click: {index: 1}}, expected_url: page.url,
      expected_identity: "@original", observation_id: "fresh"}));
    assert.equal(calls.slice(before).some(([op, _id, args]) => op === "Input.dispatchMouseEvent" && args.type === "mousePressed"), false);
  } finally { onTarget = null; await current.call("shutdown"); }
});

test("a locked desktop blocks inspection and screenshots without opening another browser", async () => {
  const current = await session();
  idleState = "locked";
  const before = calls.length;
  try {
    await assert.rejects(current.call("observe"));
    await assert.rejects(current.call("snapshot"));
    assert.equal(calls.slice(before).some(([op]) => op === "Page.captureScreenshot" || op === "Runtime.evaluate"), false);
  } finally { idleState = "active"; await current.call("shutdown"); }
});

test("manual takeover detaches and blocks all model observations and credentials", async () => {
  const current = await session();
  await current.call("takeover", {enabled: true});
  assert.ok(calls.some(([op, id]) => op === "detach" && id === current.tabId));
  await assert.rejects(current.call("observe"));
  await assert.rejects(current.call("snapshot"));
  await assert.rejects(current.call("action", {manual: true, action: {text: {text: "private"}}}));
  assert.equal(calls.some(([op]) => op === "Input.insertText"), false);
  await current.call("shutdown");
});

test("authentication pages never produce screenshots", async () => {
  const current = await session();
  page = {url: "https://example.com/login", blocked: true};
  const before = calls.length;
  const result = await current.call("snapshot");
  assert.equal(result.state.login_required, true);
  assert.equal(result.frame, undefined);
  assert.equal(calls.slice(before).some(([op]) => op === "Page.captureScreenshot"), false);
  await current.call("shutdown");
});

test("DOM password detection returns before reading page text or input values", () => {
  const password = {type: "password", getBoundingClientRect: () => ({width: 20, height: 20}),
    get value() { throw new Error("A password value must never be read"); }};
  globalThis.location = new URL("https://example.com/form");
  globalThis.getComputedStyle = () => ({visibility: "visible", display: "block"});
  globalThis.document = {querySelectorAll: () => [password], get body() { throw new Error("Page text was read during login"); }};
  assert.deepEqual(inspectPage("observe"), {blocked: true, url: "https://example.com/form"});
  delete globalThis.document; delete globalThis.location; delete globalThis.getComputedStyle;
});

test("pointer cleanup does not inspect the login page", () => {
  let removed = false;
  globalThis.document = {getElementById: () => ({remove: () => { removed = true; }}),
    querySelectorAll: () => { throw new Error("No login inspection during pointer removal"); }};
  assert.deepEqual(inspectPage("clear"), {});
  assert.equal(removed, true);
  delete globalThis.document;
});

test("ensure attaches on Chrome 156, which refuses browser-level download commands to extensions", async () => {
  const start = calls.length;
  const current = await session();
  assert.equal(calls.slice(start).some(([op]) => op.endsWith("setDownloadBehavior")), false);
  await current.call("shutdown");
});

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const downloadCalls = (start) => calls.slice(start).filter(([op]) => op.startsWith("downloads."));

test("a download started by an owned tab is cancelled and erased; the user's own downloads are untouched", async () => {
  const current = await session();
  const start = calls.length;
  try {
    listeners["debugger.onEvent"]({tabId: current.tabId}, "Page.downloadWillBegin", {url: "https://example.com/owned.zip"});
    const owned = {id: 7, url: "https://example.com/owned.zip", finalUrl: "https://example.com/owned.zip", state: "in_progress"};
    downloadItems.set(owned.id, owned);
    listeners["downloads.onCreated"](owned);
    // The same file downloaded by the user in a normal tab, and an unrelated download.
    listeners["debugger.onEvent"]({tabId: 999}, "Page.downloadWillBegin", {url: "https://example.com/user.zip"});
    listeners["downloads.onCreated"]({id: 8, url: "https://example.com/user.zip", state: "in_progress"});
    listeners["downloads.onCreated"]({id: 9, url: "https://example.com/other.zip", state: "in_progress"});
    await settle(); await settle();
    assert.deepEqual(downloadCalls(start), [["downloads.cancel", 7], ["downloads.erase", 7]]);
  } finally { downloadItems.clear(); await current.call("shutdown"); }
});

test("an owned-tab download that already finished, or was announced after it was created, loses its file", async () => {
  const current = await session();
  const start = calls.length;
  try {
    const finished = {id: 11, url: "https://example.com/tiny.txt", finalUrl: "https://example.com/tiny.txt", state: "complete"};
    downloadItems.set(finished.id, finished);
    listeners["downloads.onCreated"](finished);
    listeners["debugger.onEvent"]({tabId: current.tabId}, "Page.downloadWillBegin", {url: finished.url});
    await settle(); await settle();
    assert.deepEqual(downloadCalls(start), [["downloads.cancel", 11], ["downloads.removeFile", 11], ["downloads.erase", 11]]);
  } finally { downloadItems.clear(); await current.call("shutdown"); }
});

test("downloads in manual takeover belong to the user and are not cancelled", async () => {
  const current = await session();
  await current.call("takeover", {enabled: true});
  const start = calls.length;
  listeners["debugger.onEvent"]({tabId: current.tabId}, "Page.downloadWillBegin", {url: "https://example.com/manual.pdf"});
  listeners["downloads.onCreated"]({id: 12, url: "https://example.com/manual.pdf", state: "in_progress"});
  await settle(); await settle();
  assert.deepEqual(downloadCalls(start), []);
  await current.call("shutdown");
});

test("one owned-tab announcement stops one download; a failed cancel still removes the file", async () => {
  const current = await session();
  const start = calls.length;
  failCancel = true;
  try {
    listeners["debugger.onEvent"]({tabId: current.tabId}, "Page.downloadWillBegin", {url: "https://example.com/report.pdf"});
    const owned = {id: 21, url: "https://example.com/report.pdf", state: "complete"};
    downloadItems.set(owned.id, owned);
    listeners["downloads.onCreated"](owned);
    // The user downloads the same file right after; it is not the agent's.
    listeners["downloads.onCreated"]({id: 22, url: "https://example.com/report.pdf", state: "in_progress"});
    await settle(); await settle();
    assert.deepEqual(downloadCalls(start), [["downloads.cancel", 21], ["downloads.removeFile", 21], ["downloads.erase", 21]]);
  } finally { failCancel = false; downloadItems.clear(); await current.call("shutdown"); }
});

test("repeated owned-tab downloads of one URL are all stopped, and an older user download is not claimed", async () => {
  const current = await session();
  const start = calls.length;
  try {
    // The user started this download in another tab before the owned tab announced the same URL.
    const older = {id: 31, url: "https://example.com/twice.zip", state: "in_progress", startTime: new Date(Date.now() - 1500).toISOString()};
    downloadItems.set(older.id, older);
    // Two announcements arrive before Chrome creates either download item.
    listeners["debugger.onEvent"]({tabId: current.tabId}, "Page.downloadWillBegin", {url: "https://example.com/twice.zip"});
    listeners["debugger.onEvent"]({tabId: current.tabId}, "Page.downloadWillBegin", {url: "https://example.com/twice.zip"});
    await settle(); await settle();
    for (const id of [32, 33]) {
      const owned = {id, url: "https://example.com/twice.zip", state: "in_progress", startTime: new Date().toISOString()};
      downloadItems.set(id, owned);
      listeners["downloads.onCreated"](owned);
    }
    await settle(); await settle();
    const stopped = downloadCalls(start).filter(([op]) => op === "downloads.cancel").map(([, id]) => id);
    assert.deepEqual(stopped, [32, 33]);
  } finally { downloadItems.clear(); await current.call("shutdown"); }
});

test("observe works where crypto.randomUUID is unavailable (non-secure about:blank)", () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  // Only getRandomValues, as in Chrome 156's extension-created about:blank tab.
  Object.defineProperty(globalThis, "crypto", {configurable: true,
    value: {getRandomValues: (bytes) => webcrypto.getRandomValues(bytes)}});
  globalThis.location = new URL("about:blank");
  globalThis.getComputedStyle = () => ({visibility: "visible", display: "block"});
  globalThis.NodeFilter = {SHOW_TEXT: 4};
  globalThis.innerWidth = 800; globalThis.innerHeight = 600;
  globalThis.document = {title: "", querySelectorAll: () => [], querySelector: () => null,
    body: {}, documentElement: {}, createTreeWalker: () => ({nextNode: () => null})};
  try {
    const first = inspectPage("observe");
    assert.match(first.observation_id, /^[0-9a-f-]{32,36}$/);
    assert.notEqual(inspectPage("observe").observation_id, first.observation_id);
  } finally {
    Object.defineProperty(globalThis, "crypto", original);
    delete globalThis.__jarvisOwnedTab;
    for (const key of ["document", "location", "getComputedStyle", "NodeFilter", "innerWidth", "innerHeight"]) delete globalThis[key];
  }
});
