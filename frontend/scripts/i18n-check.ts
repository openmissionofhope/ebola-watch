// Translation catalog tooling (run with: node --experimental-strip-types scripts/i18n-check.ts <command>).
//
//   extract           write src/i18n/ui.en.json: every t("...") / <T k="..."> key in src/
//   check             compare each locale with the English sources: missing entries,
//                     placeholder mismatches (an error), entries no longer used
//   coverage <dir>    list backend sentences in a static export (data/ directory)
//                     that no template in src/i18n/server.en.json matches
//
// Exit status 1 on placeholder mismatches or when ui.en.json is out of date.

import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { Translator, compileTemplate, placeholders, type Catalog } from "../src/i18n/engine.ts";

const ROOT = new URL("..", import.meta.url).pathname;
const SRC = join(ROOT, "src");
const I18N = join(SRC, "i18n");

function walk(dir: string, filter: (f: string) => boolean): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p, filter) : filter(p) ? [p] : [];
  });
}

function unescape(s: string): string {
  return s.replace(/\\(["'`\\])/g, "$1").replace(/\\n/g, "\n");
}

export function extractKeys(): string[] {
  const keys = new Set<string>();
  const call = /\bt\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|`((?:[^`\\$]|\\.)*)`)/g;
  const comp = /<T\s+k=(?:"((?:[^"\\]|\\.)*)"|\{\s*"((?:[^"\\]|\\.)*)"\s*\})/g;
  for (const file of walk(SRC, (f) => /\.(tsx?|ts)$/.test(f) && !f.includes(`${I18N}/`))) {
    const text = readFileSync(file, "utf8");
    for (const m of text.matchAll(call)) keys.add(unescape(m[1] ?? m[2] ?? m[3]));
    for (const m of text.matchAll(comp)) keys.add(unescape(m[1] ?? m[2]));
  }
  return [...keys].sort();
}

function readJson<T>(path: string): T {
  return JSON.parse(readFileSync(path, "utf8")) as T;
}

function namedParams(s: string): string[] {
  return [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
}

function check(): number {
  const ui = extractKeys();
  const saved = readJson<string[]>(join(I18N, "ui.en.json"));
  let errors = 0;
  if (JSON.stringify(saved) !== JSON.stringify(ui)) {
    console.error("src/i18n/ui.en.json is out of date: run `npm run i18n:extract`");
    errors++;
  }
  const server = Object.keys(readJson<Record<string, string>>(join(I18N, "server.en.json")));
  for (const key of server) {
    if (/\{[ndts]\d+\}/.test(key) && !compileTemplate(key)) console.error(`invalid template: ${key}`);
  }
  for (const file of readdirSync(join(I18N, "locales")).filter((f) => f.endsWith(".json")).sort()) {
    const cat = readJson<Catalog>(join(I18N, "locales", file));
    const lang = file.replace(".json", "");
    const missingUi = ui.filter((k) => !(k in (cat.ui ?? {})));
    const missingServer = server.filter((k) => !(k in (cat.server ?? {})));
    const unusedUi = Object.keys(cat.ui ?? {}).filter((k) => !ui.includes(k));
    const unusedServer = Object.keys(cat.server ?? {}).filter((k) => !server.includes(k));
    for (const [k, v] of Object.entries(cat.ui ?? {})) {
      if (JSON.stringify(namedParams(k)) !== JSON.stringify(namedParams(v))) {
        console.error(`${lang} ui placeholder mismatch: ${JSON.stringify(k)} -> ${JSON.stringify(v)}`);
        errors++;
      }
    }
    for (const [k, v] of Object.entries(cat.server ?? {})) {
      if (JSON.stringify(placeholders(k)) !== JSON.stringify(placeholders(v))) {
        console.error(`${lang} server placeholder mismatch: ${JSON.stringify(k)} -> ${JSON.stringify(v)}`);
        errors++;
      }
    }
    console.log(`${lang}: ui ${ui.length - missingUi.length}/${ui.length}, server ${server.length - missingServer.length}/${server.length}` +
      (unusedUi.length + unusedServer.length ? `, ${unusedUi.length + unusedServer.length} unused` : ""));
    if (process.env.VERBOSE) {
      for (const k of missingUi) console.log(`  missing ui: ${k}`);
      for (const k of missingServer) console.log(`  missing server: ${k}`);
      for (const k of [...unusedUi, ...unusedServer]) console.log(`  unused: ${k}`);
    }
  }
  return errors;
}

// Fields of the public API whose values are sentences written by the backend.
const TEXT_FIELDS = new Set([
  "explanation", "text", "description", "confidence_reasons", "concerns", "note", "notes", "message", "reason",
  "assumptions", "interval", "method", "unit", "summary", "assessment", "caveats", "calibration_note", "label",
  "model_reasons", "scenario_definitions", "status_message",
]);
const SKIP_FIELDS = new Set(["citation", "source", "sources", "attribution", "terms_note", "access_method", "homepage", "url", "institution", "license", "title", "path_names", "corridor"]);

function coverage(dir: string): void {
  const templates = Object.keys(readJson<Record<string, string>>(join(I18N, "server.en.json")));
  const identity = new Translator({ server: Object.fromEntries(templates.map((k) => [k, k])) }, { number: (s) => s, date: (s) => s, place: (s) => s });
  const misses = new Map<string, string>();
  const visit = (v: unknown, field: string, parent: string, file: string) => {
    if (typeof v === "string") {
      const text = TEXT_FIELDS.has(field) || (field === "name" && parent === "outbreak");
      if (text && /[a-z]{3}/.test(v) && v.includes(" ") && identity.match(v) === null) misses.set(v, `${file}:${field}`);
    } else if (Array.isArray(v)) v.forEach((x) => visit(x, field, parent, file));
    else if (v && typeof v === "object") {
      for (const [k, x] of Object.entries(v)) {
        if (SKIP_FIELDS.has(k) || k === "parameters" || k === "geometry" || k === "line") continue;
        visit(x, field === "scenario_definitions" ? field : k, field, file);
      }
    }
  };
  for (const file of walk(dir, (f) => f.endsWith(".json") && !f.endsWith("index.json") && !f.includes("/geometry/"))) {
    visit(readJson(file), "", "", relative(dir, file));
  }
  for (const file of walk(dir, (f) => f.endsWith(".md"))) {
    // the dashboard translates report lines segment by segment around **bold** markers
    for (const raw of readFileSync(file, "utf8").split("\n")) {
      const line = raw.replace(/^#+\s+|^\s*-\s+|^\s+/, "");
      for (const segment of line.split(/\*\*(.+?)\*\*/)) {
        const s = segment.trim();
        if (s && /[a-z]{3}/i.test(s) && identity.match(s) === null) misses.set(s, relative(dir, file));
      }
    }
  }
  const sorted = [...misses.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  for (const [text, where] of sorted) console.log(`${where}\t${text}`);
  console.error(`${sorted.length} sentences without a matching template`);
}

const [cmd, arg] = process.argv.slice(2);
if (cmd === "extract") {
  const keys = extractKeys();
  writeFileSync(join(I18N, "ui.en.json"), JSON.stringify(keys, null, 1) + "\n");
  console.log(`${keys.length} interface strings`);
} else if (cmd === "check") {
  process.exit(check() ? 1 : 0);
} else if (cmd === "coverage" && arg) {
  coverage(arg);
} else {
  console.error("usage: i18n-check.ts extract | check | coverage <data dir>");
  process.exit(2);
}
