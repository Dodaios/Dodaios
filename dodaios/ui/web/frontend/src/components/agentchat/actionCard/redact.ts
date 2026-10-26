/**
 * The disclosure text of a card whose event predates the backend's masked
 * `detail` (dodaios/agent_chat/approval_card.py). Same rule as there: a field
 * named like a secret is masked whole, and anything shaped like a credential
 * inside other text is masked in place. Over-masking is fine; leaking is not.
 */

const MASK = "••••••";
const SECRET_KEY = /(pass(word|wd|phrase)?|secret|token|api[_-]?key|apikey|(?<![a-z])auth(orization)?(?![a-z])|cookie|credential|private[_-]?key|session[_-]?key|(?<![a-z])otp(?![a-z])|pin[_-]?code)/i;
const SHAPES: RegExp[] = [
  /\bsk-(?:proj-|ant-|or-|live-)?[A-Za-z0-9_-]{20,}\b/g,
  /\b(?:AIza[0-9A-Za-z_-]{30,}|xai-[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{16,}|xox[abprs]-[A-Za-z0-9-]{10,})\b/g,
  /\b[Bb]earer\s+[A-Za-z0-9._-]{16,}\b/g,
  /\beyJ[A-Za-z0-9_-]{6,}\.eyJ[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\b/g,
  /-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----/g,
  /\b[0-9a-fA-F]{64,}\b/g,
  /\b[A-Za-z0-9+/]{64,}={0,2}/g,
];
const LABELLED = /(\b(?:api[_-]?key|secret(?:[_-]?key)?|password|passwd|pwd|access[_-]?token|auth[_-]?token|client[_-]?secret)\b['"]?\s*[:=]\s*)['"]?[^\s'"]{6,}/gi;

export function maskText(text: string): string {
  let out = text.replace(LABELLED, `$1${MASK}`);
  for (const shape of SHAPES) out = out.replace(shape, MASK);
  return out;
}

function mask(value: unknown, depth = 0): unknown {
  if (depth > 8) return MASK;
  if (Array.isArray(value)) return value.slice(0, 200).map((v) => mask(v, depth + 1));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([k, v]) => [
      k, SECRET_KEY.test(k) && typeof v === "string" && v.trim() ? MASK : mask(v, depth + 1),
    ]));
  }
  return typeof value === "string" ? maskText(value) : value;
}

/** The exact command (or the whole request as JSON), secrets masked. */
export function maskedRequest(input: unknown): string {
  if (input && typeof input === "object" && !Array.isArray(input)) {
    const raw = (input as Record<string, unknown>).command;
    if (typeof raw === "string" && raw.trim()) return maskText(raw).slice(0, 4000);
    if (Array.isArray(raw) && raw.length) return maskText(raw.map(String).join(" ")).slice(0, 4000);
    if (Object.keys(input).length === 0) return "";
  }
  if (input === null || input === undefined || input === "") return "";
  try {
    return maskText(JSON.stringify(mask(input), null, 2)).slice(0, 4000);
  } catch {
    return "";
  }
}
