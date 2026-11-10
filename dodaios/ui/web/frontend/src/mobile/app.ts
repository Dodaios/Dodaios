/**
 * The phone companion: the lead's one conversation, read, typed into and
 * approved from a phone. Framework-free on purpose (see m/index.html).
 *
 * Screens: pairing (no token, or the desktop revoked this phone) and the
 * conversation. The conversation polls the folded timeline — quickly while a
 * turn runs or something waits for the person, slowly when idle, never while
 * the page is hidden — and the service worker nudges it when a push arrives.
 */
import { ApiError, type MobileApi, type Timeline, Unpaired } from "./api";
import { blobToPcm16k, canRecord, startRecording, type Recorder } from "./audio";
import { renderRows } from "./rows";
import { language, t } from "./strings";

const POLL_ACTIVE_MS = 2500;
const POLL_IDLE_MS = 7000;

export interface AppOptions {
  root: HTMLElement;
  api: MobileApi;
  /** `#pair=CODE` from the opening URL (consumed once). */
  pairingCode?: string;
  /** The service worker registration, when the context is secure. */
  registration?: ServiceWorkerRegistration | null;
  now?: () => number;
}

interface State {
  screen: "pairing" | "chat";
  assistant: string;
  pushKey: string;
  pushOn: boolean;
  timeline: Timeline | null;
  busy: string;
  note: string;
  recording: Recorder | null;
}

function el<K extends keyof HTMLElementTagNameMap>(root: ParentNode, selector: string): HTMLElementTagNameMap[K] | null {
  return root.querySelector(selector) as HTMLElementTagNameMap[K] | null;
}

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export class PhoneApp {
  private readonly state: State = {
    screen: "pairing",
    assistant: "",
    pushKey: "",
    pushOn: false,
    timeline: null,
    busy: "",
    note: "",
    recording: null,
  };
  private timer: number | null = null;
  private lastSeq = -1;
  private readonly now: () => number;

  constructor(private readonly options: AppOptions) {
    this.now = options.now ?? (() => Date.now());
  }

  async start(): Promise<void> {
    this.options.root.addEventListener("click", (event) => this.onClick(event));
    this.options.root.addEventListener("submit", (event) => this.onSubmit(event));
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") void this.refresh(true);
      else this.stopPolling();
    });
    navigator.serviceWorker?.addEventListener?.("message", (event: MessageEvent) => {
      if ((event.data as { type?: string } | null)?.type === "refresh") void this.refresh(true);
    });
    if (this.options.pairingCode) {
      await this.pair(this.options.pairingCode);
      return;
    }
    if (this.options.api.token) {
      await this.enterChat();
      return;
    }
    this.renderPairing();
  }

  // ---------------------------------------------------------------- pairing

  private async pair(code: string): Promise<void> {
    this.state.busy = "pairing";
    this.renderPairing();
    try {
      const result = await this.options.api.pair(code, this.deviceName());
      this.state.assistant = result.assistant_name;
      this.state.note = "";
      await this.enterChat();
    } catch (cause) {
      this.state.note = cause instanceof ApiError && cause.message ? cause.message : t("pair_failed");
      this.state.busy = "";
      this.renderPairing();
    }
  }

  private deviceName(): string {
    const ua = navigator.userAgent || "";
    if (/iPhone/i.test(ua)) return "iPhone";
    if (/iPad/i.test(ua)) return "iPad";
    if (/Android/i.test(ua)) return "Android phone";
    return t("device_default_name");
  }

  private renderPairing(): void {
    this.state.screen = "pairing";
    this.stopPolling();
    const secure = typeof window !== "undefined" ? window.isSecureContext : true;
    this.options.root.innerHTML = `
      <section class="screen screen-pair">
        <img class="pair-mark" src="/m/icon-192.png" alt="" width="72" height="72">
        <h1>${t("pairing_title")}</h1>
        <p class="lede">${t("pairing_body")}</p>
        <form class="pair-form" data-form="pair">
          <label class="sr-only" for="pair-code">${t("enter_code")}</label>
          <input id="pair-code" name="code" inputmode="text" autocomplete="one-time-code" autocapitalize="characters" spellcheck="false" maxlength="14" placeholder="${t("enter_code")}" ${this.state.busy ? "disabled" : ""}>
          <button type="submit" class="btn btn-primary" ${this.state.busy ? "disabled" : ""}>${this.state.busy ? t("pairing_wait") : t("pair_action")}</button>
        </form>
        ${this.state.note ? `<p class="note is-error" role="alert">${this.escape(this.state.note)}</p>` : ""}
        ${secure ? "" : `<p class="note">${t("needs_https")}</p>`}
      </section>`;
  }

  // ------------------------------------------------------------------- chat

  private async enterChat(): Promise<void> {
    try {
      const me = await this.options.api.me();
      this.state.assistant = me.assistant_name;
      this.state.pushKey = me.push_key;
      this.state.pushOn = me.push_subscribed;
      document.title = me.assistant_name || document.title;
    } catch (cause) {
      if (cause instanceof Unpaired) {
        this.state.note = t("unpaired");
        this.renderPairing();
        return;
      }
      this.state.note = t("load_failed");
    }
    this.state.screen = "chat";
    this.renderChat();
    await this.refresh(true);
  }

  private renderChat(): void {
    const online = this.state.timeline !== null;
    this.options.root.innerHTML = `
      <header class="bar">
        <span class="dot ${this.state.timeline?.running ? "is-live" : online ? "is-ok" : ""}" aria-hidden="true"></span>
        <h1 class="bar-title">${this.escape(this.state.assistant || t("title"))}</h1>
        <button type="button" class="icon-btn" data-action="menu" aria-label="${t("menu")}">···</button>
      </header>
      <div class="menu" data-menu hidden>
        <button type="button" class="menu-item" data-action="toggle-push">${this.state.pushOn ? t("notifications_off") : t("notifications_on")}</button>
        <button type="button" class="menu-item is-danger" data-action="unpair">${t("unpair")}</button>
      </div>
      <p class="status" data-status>${this.escape(this.statusLine())}</p>
      <main class="timeline-wrap"><ul class="timeline" data-timeline></ul></main>
      ${this.state.note ? `<p class="note is-error" role="alert" data-note>${this.escape(this.state.note)}</p>` : ""}
      <form class="composer" data-form="send">
        <textarea name="text" rows="1" placeholder="${t("placeholder")}" aria-label="${t("placeholder")}"></textarea>
        ${canRecord() ? `<button type="button" class="icon-btn ${this.state.recording ? "is-recording" : ""}" data-action="record" aria-label="${this.state.recording ? t("stop") : t("record")}">${this.state.recording ? "■" : "●"}</button>` : ""}
        <button type="submit" class="btn btn-primary" data-send>${t("send")}</button>
      </form>`;
    this.paintTimeline(true);
  }

  private statusLine(): string {
    const timeline = this.state.timeline;
    if (this.state.busy === "transcribing") return t("transcribing");
    if (this.state.recording) return t("recording");
    if (!timeline) return t("loading");
    if (timeline.pending_approvals.length) return t("approvals_waiting", { count: timeline.pending_approvals.length });
    if (timeline.waiting) return t("needs_you");
    if (timeline.running) return t("running");
    return "";
  }

  private paintTimeline(force = false): void {
    const list = el<"ul">(this.options.root, "[data-timeline]");
    const status = el<"p">(this.options.root, "[data-status]");
    if (status) status.textContent = this.statusLine();
    const timeline = this.state.timeline;
    if (!list || !timeline) return;
    if (!force && timeline.last_seq === this.lastSeq) return;
    const wrap = list.parentElement;
    const atBottom = !wrap || wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight < 80;
    list.innerHTML = renderRows(timeline.rows, t, this.now(), language());
    this.lastSeq = timeline.last_seq;
    if (atBottom && wrap) wrap.scrollTop = wrap.scrollHeight;
  }

  async refresh(immediate = false): Promise<void> {
    if (this.state.screen !== "chat") return;
    this.stopPolling();
    if (immediate || this.state.timeline === null) {
      try {
        this.state.timeline = await this.options.api.lead();
        if (this.state.note === t("load_failed")) this.state.note = "";
        this.paintTimeline();
      } catch (cause) {
        if (cause instanceof Unpaired) {
          this.state.note = t("unpaired");
          this.renderPairing();
          return;
        }
        this.setNote(t("offline"));
      }
    }
    if (document.visibilityState === "hidden") return;
    const active = Boolean(this.state.timeline?.running || this.state.timeline?.waiting);
    this.timer = window.setTimeout(() => void this.refresh(true), active ? POLL_ACTIVE_MS : POLL_IDLE_MS);
  }

  private stopPolling(): void {
    if (this.timer !== null) window.clearTimeout(this.timer);
    this.timer = null;
  }

  private setNote(text: string): void {
    this.state.note = text;
    const note = el<"p">(this.options.root, "[data-note]");
    if (note) {
      note.textContent = text;
      note.hidden = !text;
    } else if (text && this.state.screen === "chat") {
      this.renderChat();
    }
  }

  // ---------------------------------------------------------------- actions

  private onSubmit(event: Event): void {
    const form = event.target as HTMLFormElement;
    if (form.dataset.form === "pair") {
      event.preventDefault();
      const input = form.elements.namedItem("code") as HTMLInputElement | null;
      const code = (input?.value ?? "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
      if (code) void this.pair(code);
    } else if (form.dataset.form === "send") {
      event.preventDefault();
      void this.sendTyped(form);
    }
  }

  private async sendTyped(form: HTMLFormElement): Promise<void> {
    const area = form.elements.namedItem("text") as HTMLTextAreaElement | null;
    const text = (area?.value ?? "").trim();
    if (!text || this.state.busy) return;
    this.state.busy = "sending";
    const button = el<"button">(form, "[data-send]");
    if (button) button.disabled = true;
    try {
      await this.options.api.sendMessage(text);
      if (area) area.value = "";
      this.setNote("");
      await this.refresh(true);
    } catch (cause) {
      this.setNote(cause instanceof Unpaired ? t("unpaired") : (cause as Error).message || t("send_failed"));
    } finally {
      this.state.busy = "";
      if (button) button.disabled = false;
    }
  }

  private onClick(event: Event): void {
    const target = (event.target as HTMLElement).closest<HTMLElement>("[data-action],[data-approve]");
    if (!target) return;
    if (target.dataset.approve !== undefined) {
      void this.decide(target.dataset.approve, target.dataset.decision === "deny" ? "deny" : "allow");
      return;
    }
    switch (target.dataset.action) {
      case "menu": {
        const menu = el<"div">(this.options.root, "[data-menu]");
        if (menu) menu.hidden = !menu.hidden;
        break;
      }
      case "toggle-push":
        void this.togglePush();
        break;
      case "unpair":
        void this.unpair();
        break;
      case "record":
        void this.toggleRecording();
        break;
      default:
        break;
    }
  }

  private async decide(approvalId: string, decision: "allow" | "deny"): Promise<void> {
    try {
      await this.options.api.decide(approvalId, decision);
      await this.refresh(true);
    } catch (cause) {
      this.setNote(cause instanceof ApiError ? cause.message : t("send_failed"));
      await this.refresh(true);
    }
  }

  private async togglePush(): Promise<void> {
    const menu = el<"div">(this.options.root, "[data-menu]");
    if (menu) menu.hidden = true;
    const registration = this.options.registration;
    if (!registration || !("pushManager" in registration) || !this.state.pushKey) {
      this.setNote(t("notifications_unavailable"));
      return;
    }
    try {
      if (this.state.pushOn) {
        const existing = await registration.pushManager.getSubscription();
        await existing?.unsubscribe();
        await this.options.api.unsubscribePush();
        this.state.pushOn = false;
      } else {
        const permission = await Notification.requestPermission();
        if (permission !== "granted") {
          this.setNote(t("notifications_denied"));
          return;
        }
        const subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(this.state.pushKey) as BufferSource,
        });
        await this.options.api.subscribePush(subscription.toJSON());
        this.state.pushOn = true;
      }
      this.setNote("");
      this.renderChat();
    } catch (cause) {
      this.setNote(cause instanceof ApiError ? cause.message : t("notifications_unavailable"));
    }
  }

  private async unpair(): Promise<void> {
    if (!window.confirm(t("unpair_confirm"))) return;
    try {
      await this.options.api.unpair();
    } catch {
      /* the token is forgotten locally either way */
    }
    this.state.note = t("unpaired_done");
    this.renderPairing();
  }

  private async toggleRecording(): Promise<void> {
    if (this.state.recording) {
      const recorder = this.state.recording;
      this.state.recording = null;
      this.state.busy = "transcribing";
      this.renderChat();
      try {
        const blob = await recorder.stop();
        const pcm = await blobToPcm16k(blob);
        const result = await this.options.api.voiceNote(pcm, language());
        this.setNote("");
        void result;
      } catch (cause) {
        this.setNote(cause instanceof ApiError ? cause.message : t("voice_failed"));
      } finally {
        this.state.busy = "";
        this.renderChat();
        await this.refresh(true);
      }
      return;
    }
    try {
      this.state.recording = await startRecording();
      this.renderChat();
    } catch {
      this.setNote(t("microphone_denied"));
    }
  }

  private escape(text: string): string {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
}
