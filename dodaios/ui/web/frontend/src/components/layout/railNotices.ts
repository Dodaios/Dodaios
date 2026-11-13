import { useEffect } from "react";

import { usePluginAttention, type PluginAttentionItem } from "@/hooks/usePluginAttention";
import { fill, useT } from "@/i18n";
import { prettyProviderName } from "@/lib/prettyProviderName";

import { useStatusLightStore, watchStatusLight, type StatusLightData, type StatusRow } from "./statusLightStore";

/**
 * The notices on the rail beside the conversation: only what needs the person.
 *
 * A notice is one thing the person has to do something about, said in words:
 * a connection that ended, a service an agent needs connected, a provider
 * that stopped working, an agent that asks. Each names its subject (whose logo or face the tile shows), what is
 * asked (the badge on the tile's corner), and where a click leads.
 *
 * What is NOT a notice, on purpose: work that merely runs, a provider that is
 * throttled for a moment, a health finding nobody can act on, and anything the
 * assistant made. The rail is on screen all day; a tile there has to be worth
 * a click every time, or the person stops reading the rail.
 *
 * This module only folds data into notices. Drawing them (logos, faces, the
 * sign-in a reconnect runs) is `RailNoticeTiles`, loaded once there is one.
 */

/** What a notice asks of the person; the badge on the tile says it. */
export type NoticeAsk =
  | "reconnect" | "connect" | "question" | "approval" | "credential" | "proposal" | "takeover" | "waiting" | "trouble";

/** Whose notice it is; the tile draws this subject's logo or face. */
export type NoticeMark =
  | { type: "plugin"; id: string }
  /** A command-line tool the assistant can use (GitHub's `gh`), not a coding agent. */
  | { type: "tool"; id: string }
  | { type: "provider"; id: string }
  | { type: "cli"; id: string }
  | { type: "agent"; id: string }
  /** No logo and no face to show: a plain sign for the kind of thing it is. */
  | { type: "glyph"; glyph: "agent" | "terminal" | "mission" };

/** Where a click on a notice leads. */
export type NoticeTarget =
  | { type: "reconnect"; pluginId: string }
  | { type: "plugin"; pluginId: string }
  | { type: "keys" }
  | { type: "row"; row: StatusRow };

export interface RailNotice {
  key: string;
  ask: NoticeAsk;
  /** `needs`: someone waits for the person. `trouble`: something stopped working. */
  tone: "needs" | "trouble";
  mark: NoticeMark;
  /** The subject's name ("Gmail", "Claude Code"), for the logo's fallback letters. */
  subject: string;
  /** One sentence that says what happened ("Gmail is disconnected"). */
  title: string;
  /** What it is about, or what to do; may be empty. */
  detail: string;
  /** What a click does, as two or three words ("Reconnect"). */
  action: string;
  /** How many things of the same subject stand behind this one notice. */
  count: number;
  target: NoticeTarget;
}

/** How many notices the rail shows before the rest moves behind a count. */
export const NOTICES_SHOWN = 4;

const ASK_OF_KIND: Record<string, NoticeAsk> = {
  question: "question",
  approval: "approval",
  credential: "credential",
  proposal: "proposal",
  browser_takeover: "takeover",
  pane: "waiting",
  mission: "waiting",
};

/** A provider failure as a trouble class: a bad key is a login problem, no credit is a limit. */
const STATUS_CLASS: Record<string, string> = { bad_key: "auth", no_credits: "quota", model_unavailable: "model_unavailable" };
const KNOWN_CLASSES = ["quota", "auth", "model_unavailable"];
/** A provider that is only slowed down for a moment recovers by itself: not worth a tile. */
const PASSING_CLASSES = ["rate_limit"];

type Translate = (key: string) => string;

/** A card of an agent (a question, an approval, a login it needs, a change it proposes). */
function cardNotice(row: StatusRow, rows: StatusRow[], t: Translate): RailNotice {
  const ask = ASK_OF_KIND[row.kind] ?? "question";
  const name = row.agent_name || t("rail_notice.an_agent");
  const more = rows.length - 1;
  return {
    key: row.link.agent_id ? `agent:${row.link.agent_id}` : `${row.kind}:${row.id}`,
    ask,
    tone: "needs",
    mark: row.link.agent_id ? { type: "agent", id: row.link.agent_id } : { type: "glyph", glyph: "agent" },
    subject: name,
    title: fill(t(`rail_notice.${ask}_title`), { who: name }),
    detail: more > 0 ? [row.title, fill(t("rail_notice.and_more"), { count: more })].filter(Boolean).join(" · ") : row.title,
    action: t(`rail_notice.${ask}_action`),
    count: rows.length,
    target: { type: "row", row },
  };
}

/** An agent asks for a service to be connected: the service's own mark, and the card as the place to do it. */
function connectNotice(row: StatusRow, connect: NonNullable<StatusRow["connect"]>, t: Translate): RailNotice {
  const who = row.agent_name || t("rail_notice.an_agent");
  const service = connect.label || connect.id;
  return {
    key: `connect:${connect.kind}:${connect.id}`,
    ask: "connect",
    tone: "needs",
    mark: connect.kind === "cli" ? { type: "tool", id: connect.id } : { type: "plugin", id: connect.id },
    subject: service,
    title: fill(t("rail_notice.connect_title"), { who, service }),
    detail: connect.why || fill(t("rail_notice.connect_detail"), { service }),
    action: t("rail_notice.connect_action"),
    count: 1,
    target: { type: "row", row },
  };
}

/** A coding agent in the Agentic IDE that stopped and waits for the person. */
function paneNotice(row: StatusRow, t: Translate): RailNotice {
  const name = row.agent_label || t("rail_notice.a_coding_agent");
  // "T2 · Library": the pane's own name and where it works. An older backend sends only the title.
  const where = row.name ? [row.name, row.workspace].filter(Boolean).join(" · ") : row.title;
  return {
    key: `pane:${row.id}`,
    ask: "waiting",
    tone: "needs",
    mark: row.agent ? { type: "cli", id: row.agent } : { type: "glyph", glyph: "terminal" },
    subject: name,
    title: fill(t("rail_notice.waiting_title"), { who: name }),
    detail: where,
    action: t("rail_notice.waiting_action"),
    count: 1,
    target: { type: "row", row },
  };
}

function missionNotice(row: StatusRow, t: Translate): RailNotice {
  return {
    key: `mission:${row.id}`,
    ask: "waiting",
    tone: "needs",
    mark: { type: "glyph", glyph: "mission" },
    subject: t("rail_notice.mission_title"),
    title: t("rail_notice.mission_title"),
    detail: row.title,
    action: t("rail_notice.mission_action"),
    count: 1,
    target: { type: "row", row },
  };
}

/** What waits on the person: one notice per agent, however many cards it has open. */
function needsNotices(rows: StatusRow[], t: Translate): RailNotice[] {
  // A Map keeps the order its keys first came in: the longest wait stays first.
  const groups = new Map<string, StatusRow[]>();
  for (const row of rows) {
    const alone = row.kind === "pane" || row.kind === "mission" || !row.link.agent_id;
    // A service to connect is its own notice: it shows that service, not the agent that asks.
    const key = row.connect ? `connect:${row.connect.kind}:${row.connect.id}`
      : alone ? `${row.kind}:${row.id}` : `agent:${row.link.agent_id}`;
    const group = groups.get(key);
    if (group) group.push(row);
    else groups.set(key, [row]);
  }
  return [...groups.values()].map((group) => {
    const first = group[0];
    if (first.connect) return connectNotice(first, first.connect, t);
    if (first.kind === "pane") return paneNotice(first, t);
    if (first.kind === "mission") return missionNotice(first, t);
    return cardNotice(first, group, t);
  });
}

/** Connections that ended first (one click reconnects them), then plugins that report an error. */
function pluginNotices(items: PluginAttentionItem[], t: Translate): RailNotice[] {
  const ended = (item: PluginAttentionItem) => (item.status === "needs_reauth" ? 0 : 1);
  return items.filter((item) => item.id).sort((a, b) => ended(a) - ended(b)).map((item): RailNotice => {
    const name = item.name || item.id;
    const reconnect = item.status === "needs_reauth";
    return {
      key: `plugin:${item.id}`,
      ask: reconnect ? "reconnect" : "trouble",
      tone: "trouble",
      mark: { type: "plugin", id: item.id },
      subject: name,
      title: fill(t(reconnect ? "rail_notice.reconnect_title" : "rail_notice.plugin_error_title"), { who: name }),
      detail: fill(t(reconnect ? "rail_notice.reconnect_detail" : "rail_notice.plugin_error_detail"), { who: name }),
      action: t(reconnect ? "rail_notice.reconnect_action" : "rail_notice.plugin_error_action"),
      count: 1,
      target: reconnect ? { type: "reconnect", pluginId: item.id } : { type: "plugin", pluginId: item.id },
    };
  });
}

/** "OpenAI GPT-Live (ChatGPT subscription)" is the provider and, in brackets, which access to it. */
function splitName(name: string): { name: string; access: string } {
  const match = /^(.+?)\s*\(([^()]+)\)$/.exec(name);
  return match ? { name: match[1], access: match[2] } : { name, access: "" };
}

/** Providers that stopped working: one notice per provider, whatever reported it. */
function providerNotices(light: StatusLightData, t: Translate): RailNotice[] {
  const seen = new Map<string, RailNotice>();
  const add = (id: string, label: string, cls: string, account: string) => {
    if (PASSING_CLASSES.includes(cls) || seen.has(id)) return;
    const { name, access } = splitName(label);
    const problem = t(`rail_notice.provider_${KNOWN_CLASSES.includes(cls) ? cls : "other"}`);
    seen.set(id, {
      key: `provider:${id}`,
      ask: "trouble",
      tone: "trouble",
      mark: { type: "provider", id },
      subject: name,
      title: fill(t("rail_notice.provider_title"), { who: name, problem }),
      detail: [access || account, t("rail_notice.provider_detail")].filter(Boolean).join(" · "),
      action: t("rail_notice.provider_action"),
      count: 1,
      target: { type: "keys" },
    });
  };
  for (const seat of light.trouble) add(seat.provider, seat.label || prettyProviderName(seat.provider), seat.class, seat.account);
  for (const finding of light.findings) {
    // A finding without a provider is a health check nobody can act on from here.
    if (!finding.provider) continue;
    add(finding.provider_id || finding.provider, finding.provider, STATUS_CLASS[finding.status ?? ""] ?? "other", "");
  }
  return [...seen.values()];
}

/**
 * Everything that needs the person, most pressing first: who waits for an
 * answer, then the connections that ended, then the providers in trouble.
 */
export function railNotices(light: StatusLightData | null, plugins: PluginAttentionItem[], t: Translate): RailNotice[] {
  const needs = light ? needsNotices(light.needs_you, t) : [];
  // An agent already asks for this plugin: one tile for it, the one that leads to the card.
  const asked = new Set(needs.flatMap((notice) => (notice.ask === "connect" && notice.mark.type === "plugin" ? [notice.mark.id] : [])));
  return [
    ...needs,
    ...pluginNotices(plugins, t).filter((notice) => notice.mark.type !== "plugin" || !asked.has(notice.mark.id)),
    ...(light ? providerNotices(light, t) : []),
  ];
}

/** The rail's notices, kept fresh while the window is in sight. */
export function useRailNotices(): RailNotice[] {
  const t = useT();
  const light = useStatusLightStore((s) => s.light);
  const plugins = usePluginAttention();
  useEffect(() => watchStatusLight(), []);
  return railNotices(light, plugins.items, t);
}
