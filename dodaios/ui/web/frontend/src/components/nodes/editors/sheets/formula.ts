/**
 * Column formulas and totals, computed in the editor the way the page computes them.
 *
 * The authority is Python (`parse_formula`, `evaluate`, `_formula_order` and
 * `_total` in `dodaios/nodes/kinds/sheets.py`): it refuses a formula outside
 * the grammar when the spec is saved, and computes the values the page shows.
 * The editor needs the same values while the person types (a formula column
 * must update as its inputs change, and a refused formula must be caught
 * before the save fails), so the grammar and the arithmetic are mirrored
 * here: numbers, the row's other column keys, + - * / // % ** with Python's
 * precedence (** binds tighter than a unary minus on its left and groups to
 * the right), parentheses, and round, abs, min, max, sum. A missing input, a
 * division by zero or an overflow leaves the cell empty, never an error.
 *
 * There are no per-cell formulas: see the module comment of `sheets.py`.
 */
import { MAX_FORMULA_CHARS, isNumber, isNumericType, type Row, type SheetColumn, type TotalKind } from "./model";

export type FormulaNode =
  | { kind: "num"; value: number }
  | { kind: "name"; name: string }
  | { kind: "neg"; operand: FormulaNode }
  | { kind: "bin"; op: string; left: FormulaNode; right: FormulaNode }
  | { kind: "call"; name: string; args: FormulaNode[] };

/** name -> [fewest, most] arguments. */
const FUNCTIONS: Record<string, [number, number]> = {
  round: [1, 2],
  abs: [1, 1],
  min: [1, 30],
  max: [1, 30],
  sum: [1, 30],
};

const MAX_NODES = 120;
const MAX_EXPONENT = 64;

export class FormulaError extends Error {
  constructor(message = "formula") {
    super(message);
    this.name = "FormulaError";
  }
}

type Token = { type: "num"; value: number } | { type: "name"; value: string } | { type: "op"; value: string };

function tokenize(text: string): Token[] {
  const tokens: Token[] = [];
  const pattern = /\s*(?:(\d[\d_]*\.?[\d_]*(?:e[+-]?\d+)?|\.\d[\d_]*(?:e[+-]?\d+)?)|([A-Za-z_\p{L}][\w\p{L}\p{N}]*)|(\*\*|\/\/|[-+*/%(),]))/uy;
  let at = 0;
  while (at < text.length) {
    if (/^\s+$/.test(text.slice(at))) break;
    pattern.lastIndex = at;
    const match = pattern.exec(text);
    if (!match) throw new FormulaError();
    at = pattern.lastIndex;
    if (match[1] !== undefined) {
      const raw = match[1];
      if (/_$|__|_\.|\._/.test(raw)) throw new FormulaError();
      const value = Number(raw.replace(/_/g, ""));
      if (!Number.isFinite(value)) throw new FormulaError();
      tokens.push({ type: "num", value });
    } else if (match[2] !== undefined) tokens.push({ type: "name", value: match[2] });
    else tokens.push({ type: "op", value: match[3] });
  }
  return tokens;
}

/** A formula as a checked tree; `FormulaError` when it is outside the grammar. */
export function parseFormula(expression: string): FormulaNode {
  const text = expression.trim();
  if (!text || text.length > MAX_FORMULA_CHARS) throw new FormulaError();
  const tokens = tokenize(text);
  let at = 0;
  let nodes = 0;
  const peek = () => tokens[at];
  const isOp = (value: string) => peek()?.type === "op" && peek().value === value;
  const made = (node: FormulaNode): FormulaNode => {
    nodes += 1;
    if (nodes > MAX_NODES) throw new FormulaError();
    return node;
  };

  const expr = (): FormulaNode => {
    let left = term();
    while (isOp("+") || isOp("-")) {
      const op = tokens[at++].value as string;
      left = made({ kind: "bin", op, left, right: term() });
    }
    return left;
  };
  const term = (): FormulaNode => {
    let left = unary();
    while (isOp("*") || isOp("/") || isOp("//") || isOp("%")) {
      const op = tokens[at++].value as string;
      left = made({ kind: "bin", op, left, right: unary() });
    }
    return left;
  };
  const unary = (): FormulaNode => {
    if (isOp("-")) {
      at += 1;
      return made({ kind: "neg", operand: unary() });
    }
    if (isOp("+")) {
      at += 1;
      return unary();
    }
    return power();
  };
  const power = (): FormulaNode => {
    const base = atom();
    if (isOp("**")) {
      at += 1;
      return made({ kind: "bin", op: "**", left: base, right: unary() });
    }
    return base;
  };
  const atom = (): FormulaNode => {
    const token = tokens[at++];
    if (!token) throw new FormulaError();
    if (token.type === "num") return made({ kind: "num", value: token.value });
    if (token.type === "name") {
      if (isOp("(")) {
        at += 1;
        const known = FUNCTIONS[token.value];
        if (!known) throw new FormulaError();
        const args: FormulaNode[] = [];
        if (!isOp(")")) {
          args.push(expr());
          while (isOp(",")) {
            at += 1;
            if (isOp(")")) break; // Python allows a trailing comma
            args.push(expr());
          }
        }
        if (!isOp(")")) throw new FormulaError();
        at += 1;
        if (args.length < known[0] || args.length > known[1]) throw new FormulaError();
        return made({ kind: "call", name: token.value, args });
      }
      return made({ kind: "name", name: token.value });
    }
    if (token.value === "(") {
      const inner = expr();
      if (!isOp(")")) throw new FormulaError();
      at += 1;
      return inner;
    }
    throw new FormulaError();
  };

  const tree = expr();
  if (at !== tokens.length) throw new FormulaError();
  return tree;
}

/** The column keys a formula reads (function names are not among them). */
export function formulaNames(tree: FormulaNode): string[] {
  const found: string[] = [];
  const walk = (node: FormulaNode) => {
    if (node.kind === "name") {
      if (!found.includes(node.name)) found.push(node.name);
    } else if (node.kind === "neg") walk(node.operand);
    else if (node.kind === "bin") {
      walk(node.left);
      walk(node.right);
    } else if (node.kind === "call") node.args.forEach(walk);
  };
  walk(tree);
  return found;
}

class NoValue extends Error {}

/** Round half away from zero, from the number's shortest written form (as Python's Decimal does). */
export function roundHalfAway(value: number, places = 0): number {
  const digits = Math.trunc(Math.max(-10, Math.min(10, places)));
  const size = Math.abs(value);
  const written = String(size);
  let rounded: number;
  if (written.includes("e")) {
    const scale = 10 ** digits;
    rounded = Math.round(size * scale) / scale;
  } else {
    rounded = Number(`${Math.round(Number(`${written}e${digits}`))}e${-digits}`);
  }
  return value < 0 ? -rounded : rounded;
}

function walk(node: FormulaNode, values: Row): number {
  switch (node.kind) {
    case "num":
      return node.value;
    case "name": {
      const value = values[node.name];
      if (!isNumber(value)) throw new NoValue();
      return value;
    }
    case "neg":
      return -walk(node.operand, values);
    case "bin": {
      const a = walk(node.left, values);
      const b = walk(node.right, values);
      switch (node.op) {
        case "+":
          return a + b;
        case "-":
          return a - b;
        case "*":
          return a * b;
        case "/":
          if (b === 0) throw new NoValue();
          return a / b;
        case "//":
          if (b === 0) throw new NoValue();
          return Math.floor(a / b);
        case "%":
          if (b === 0) throw new NoValue();
          return a - b * Math.floor(a / b);
        default: {
          if (Math.abs(b) > MAX_EXPONENT) throw new NoValue();
          if (a === 0 && b < 0) throw new NoValue();
          const result = a ** b;
          if (Number.isNaN(result)) throw new NoValue(); // a root of a negative number
          return result;
        }
      }
    }
    case "call": {
      const args = node.args.map((arg) => walk(arg, values));
      switch (node.name) {
        case "round":
          return roundHalfAway(args[0], args[1] ?? 0);
        case "abs":
          return Math.abs(args[0]);
        case "min":
          return Math.min(...args);
        case "max":
          return Math.max(...args);
        default:
          return args.reduce((total, value) => total + value, 0);
      }
    }
  }
}

/** The formula's value for one row, or null for an empty cell. */
export function evaluate(tree: FormulaNode, values: Row): number | null {
  let result: number;
  try {
    result = walk(tree, values);
  } catch (error) {
    if (error instanceof NoValue) return null;
    throw error;
  }
  if (!Number.isFinite(result)) return null;
  if (Math.abs(result) < 1e21) result = Number(result.toFixed(10));
  return result === 0 ? 0 : result;
}

export interface FormulaProblem {
  /** The formula column's key. */
  key: string;
  reason: "grammar" | "unknown" | "cycle";
  /** The name a formula used that is no other column's key. */
  name?: string;
}

export interface FormulaPlan {
  order: Array<[string, FormulaNode]>;
  problems: FormulaProblem[];
}

/** The formula columns in the order they can be computed, and what is wrong with any. */
export function formulaPlan(columns: readonly SheetColumn[]): FormulaPlan {
  const keys = new Set(columns.map((column) => column.key));
  const trees = new Map<string, FormulaNode>();
  const needs = new Map<string, string[]>();
  const problems: FormulaProblem[] = [];
  for (const column of columns) {
    if (!column.formula) continue;
    let tree: FormulaNode;
    try {
      tree = parseFormula(column.formula);
    } catch {
      problems.push({ key: column.key, reason: "grammar" });
      continue;
    }
    const names = formulaNames(tree);
    const bad = names.find((name) => name === column.key || !keys.has(name));
    if (bad !== undefined) {
      problems.push({ key: column.key, reason: "unknown", name: bad });
      continue;
    }
    trees.set(column.key, tree);
    needs.set(column.key, names);
  }
  const order: Array<[string, FormulaNode]> = [];
  const state = new Map<string, number>();
  const cyclic = new Set<string>();
  const visit = (key: string): boolean => {
    if (state.get(key) === 2) return true;
    if (state.get(key) === 1) return false;
    state.set(key, 1);
    for (const name of needs.get(key) ?? []) {
      if (trees.has(name) && !visit(name)) {
        cyclic.add(key);
        state.set(key, 2);
        return false;
      }
    }
    state.set(key, 2);
    order.push([key, trees.get(key) as FormulaNode]);
    return true;
  };
  for (const key of trees.keys()) visit(key);
  for (const key of cyclic) problems.push({ key, reason: "cycle" });
  return { order: order.filter(([key]) => !cyclic.has(key)), problems };
}

/** The rows with their formula cells computed (rows without formulas are returned as they are). */
export function computeRows(rows: readonly Row[], plan: FormulaPlan): Row[] {
  if (!plan.order.length) return rows as Row[];
  return rows.map((row) => {
    const full: Row = { ...row };
    for (const [key, tree] of plan.order) {
      const value = evaluate(tree, full);
      if (value === null) delete full[key];
      else full[key] = value;
    }
    return full;
  });
}

/** Whether a total means something for a column of this kind (`_read` in `sheets.py`). */
export function totalAllowed(total: TotalKind, kind: string): boolean {
  return total === "count" || isNumericType(kind) || kind === "check";
}

/** A column's total over the given rows, or null when there is nothing to total. */
export function columnTotal(total: TotalKind, kind: string, key: string, rows: readonly Row[]): number | null {
  const cells = rows.map((row) => row[key]);
  let values: number[];
  let filled: number;
  if (kind === "check") {
    values = cells.filter((cell): cell is boolean => typeof cell === "boolean").map((cell) => (cell ? 1 : 0));
    filled = cells.filter((cell) => cell === true).length;
  } else {
    values = cells.filter(isNumber);
    filled = cells.filter((cell) => cell !== undefined && cell !== "").length;
  }
  if (total === "count") return filled;
  if (!values.length) return null;
  if (total === "sum") return values.reduce((a, b) => a + b, 0);
  if (total === "avg") return values.reduce((a, b) => a + b, 0) / values.length;
  return total === "min" ? Math.min(...values) : Math.max(...values);
}
