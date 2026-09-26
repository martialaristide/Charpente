// Both languages are complete, and every key the code uses exists.
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { MESSAGES, getLang, setLang, t } from "../../charpente/studio_web/js/i18n.js";

const WEB = new URL("../../charpente/studio_web/", import.meta.url);

function files(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) files(path, out);
    else out.push(path);
  }
  return out;
}

test("French and English have exactly the same keys", () => {
  const en = Object.keys(MESSAGES.en).sort();
  const fr = Object.keys(MESSAGES.fr).sort();
  assert.deepEqual(fr.filter((k) => !en.includes(k)), [], "keys only in French");
  assert.deepEqual(en.filter((k) => !fr.includes(k)), [], "keys only in English");
});

test("no translation is empty and placeholders match between languages", () => {
  for (const key of Object.keys(MESSAGES.en)) {
    assert.ok(MESSAGES.en[key].trim() && MESSAGES.fr[key].trim(), key);
    const names = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    assert.deepEqual(names(MESSAGES.fr[key]), names(MESSAGES.en[key]), `placeholders of ${key}`);
  }
});

test("every literal key used with t(...) or data-i18n exists", () => {
  const missing = [];
  const known = new Set(Object.keys(MESSAGES.en));
  const root = new URL(".", WEB).pathname.replace(/^\/([A-Za-z]:)/, "$1");
  for (const path of files(root)) {
    if (!/\.(js|html)$/.test(path)) continue;
    const text = readFileSync(path, "utf8");
    for (const match of text.matchAll(/\bt\(\s*["']([\w.]+)["']/g)) if (!known.has(match[1])) missing.push(`${path}: ${match[1]}`);
    for (const match of text.matchAll(/data-i18n(?:-[a-z-]+)?="([\w.]+)"/g)) if (!known.has(match[1])) missing.push(`${path}: ${match[1]}`);
  }
  assert.deepEqual(missing, []);
});

test("keys built from a variable have all their values translated", () => {
  const groups = {
    "connection.": ["connecting", "open", "closed"], "status.": ["building", "ok", "upToDate", "failed"], "severity.": ["error", "warning", "information", "hint"],
    "tab.": ["files", "targets", "options", "packages", "build", "problems", "graph", "profile", "git", "devices", "debug", "terminal", "ai"], "theme.": ["auto", "light", "dark"],
  };
  for (const [prefix, names] of Object.entries(groups)) for (const name of names) {
    assert.ok(MESSAGES.en[prefix + name], prefix + name);
    assert.ok(MESSAGES.fr[prefix + name], prefix + name);
  }
});

test("t() interpolates, falls back to English, then to the key", () => {
  setLang("en");
  assert.equal(t("editor.saved", { name: "a.cpp" }), "Saved a.cpp");
  assert.equal(t("editor.saved"), "Saved {name}");
  assert.equal(t("no.such.key"), "no.such.key");
  setLang("fr");
  assert.equal(t("editor.saved", { name: "a.cpp" }), "a.cpp enregistré");
  assert.equal(getLang(), "fr");
  setLang("xx");
  assert.equal(getLang(), "fr");
  setLang("en");
});
