/**
 * Pure rendering helpers for the phone timeline: one row of the folded lead
 * conversation becomes one HTML string. Kept framework-free so the bundle
 * stays tiny and the output is testable as text.
 */
import type { TimelineRow } from "./api";

export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Paragraphs and line breaks only; the phone never renders markup from the model. */
export function formatText(text: string): string {
  return escapeHtml(text.trim())
    .split(/\n{2,}/)
    .map((paragraph) => `<p>${paragraph.replace(/\n/g, "<br>")}</p>`)
    .join("");
}

export function formatTime(tsMs: number, now = Date.now(), locale = "en"): string {
  if (!tsMs) return "";
  const date = new Date(tsMs);
  const sameDay = new Date(now).toDateString() === date.toDateString();
  if (sameDay) return date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  return date.toLocaleDateString(locale, { month: "short", day: "numeric" });
}

type Translate = (key: string, fills?: Record<string, string | number>) => string;

export function renderRow(row: TimelineRow, t: Translate, now = Date.now(), locale = "en"): string {
  const time = `<time class="row-time">${escapeHtml(formatTime(row.ts_ms, now, locale))}</time>`;
  switch (row.kind) {
    case "user":
      return `<li class="row row-user" data-id="${escapeHtml(row.id)}"><div class="bubble">${formatText(row.text)}</div>${time}</li>`;
    case "assistant":
      return `<li class="row row-assistant" data-id="${escapeHtml(row.id)}"><div class="bubble">${formatText(row.text)}</div>${time}</li>`;
    case "approval": {
      const open = row.decision == null;
      const name = row.name ? `<span class="card-name">${escapeHtml(row.name)}</span>` : "";
      const body = row.text ? `<p class="card-text">${escapeHtml(row.text)}</p>` : "";
      const actions = open
        ? `<div class="card-actions"><button type="button" class="btn btn-primary" data-approve="${escapeHtml(row.approval_id ?? "")}" data-decision="allow">${escapeHtml(t("approve"))}</button><button type="button" class="btn btn-quiet" data-approve="${escapeHtml(row.approval_id ?? "")}" data-decision="deny">${escapeHtml(t("deny"))}</button></div>`
        : `<p class="card-decided">${escapeHtml(t(row.decision === "deny" ? "decided_deny" : "decided_allow"))}</p>`;
      return `<li class="row row-card ${open ? "is-open" : "is-settled"}" data-id="${escapeHtml(row.id)}"><div class="card"><p class="card-title">${escapeHtml(t("waiting_you"))}${name}</p>${body}${actions}</div></li>`;
    }
    case "question": {
      const hint = row.answered ? "" : `<p class="card-hint">${escapeHtml(t("question_hint"))}</p>`;
      return `<li class="row row-card ${row.answered ? "is-settled" : "is-open"}" data-id="${escapeHtml(row.id)}"><div class="card"><p class="card-title">${escapeHtml(t("question"))}</p><p class="card-text">${escapeHtml(row.text)}</p>${hint}</div></li>`;
    }
    case "error":
      return `<li class="row row-notice is-error" data-id="${escapeHtml(row.id)}"><p>${escapeHtml(row.text)}</p></li>`;
    case "notice":
    default:
      return `<li class="row row-notice" data-id="${escapeHtml(row.id)}"><p>${formatText(row.text)}</p>${time}</li>`;
  }
}

export function renderRows(rows: TimelineRow[], t: Translate, now = Date.now(), locale = "en"): string {
  if (!rows.length) return `<li class="row row-empty"><p>${escapeHtml(t("empty"))}</p></li>`;
  return rows.map((row) => renderRow(row, t, now, locale)).join("");
}
