// Completion for the editor: the DSL of `.charpente` files (from the server's schema) and words already in the document.
// Pure: (text, cursor, language, schema) → {from, items}. Compiler-driven completion for C/C++ comes from clangd (lsp.js) when available.

const CPP_WORDS = ("alignas auto bool break case catch char class const constexpr continue default delete do double else enum explicit extern false float for friend if inline int long namespace new noexcept nullptr operator private protected public return short signed sizeof static static_assert struct switch template this throw true try typedef typename union unsigned using virtual void volatile while " +
  "#include #define #ifdef #ifndef #endif #pragma std::string std::vector std::unique_ptr std::shared_ptr std::move size_t uint8_t uint16_t uint32_t uint64_t int8_t int16_t int32_t int64_t").split(" ");
const PY_WORDS = "and as assert class def del elif else except finally for from if import in is lambda not or pass raise return try while with yield True False None".split(" ");

/** The identifier being typed at `offset`: {from, prefix}. `#` and `:` count for C++ names like `#include` and `std::move`. */
export function currentWord(text, offset, lang = "") {
  const pattern = /[A-Za-z0-9_]/;
  let from = offset;
  while (from > 0) {
    const ch = text[from - 1];
    if (pattern.test(ch)) from--;
    else if (lang === "cpp" && ch === "#") from--;
    else if (lang === "cpp" && ch === ":" && text[from - 2] === ":" && from - 2 >= 0 && pattern.test(text[from - 3] || "")) from -= 2; // `std::` continues the name
    else break;
  }
  return { from, prefix: text.slice(from, offset) };
}

/** Variables bound by `with Target("x") as t:` / `with Workspace("y") as ws:` → {t: "Target", ws: "Workspace"}. */
export function dslVariables(text) {
  const vars = {};
  const pattern = /with\s+(Workspace|Target|Rule)\s*\([^\n]*\)\s+as\s+(\w+)/g;
  let match;
  while ((match = pattern.exec(text)) !== null) vars[match[2]] = match[1];
  return vars;
}

function documentWords(text, prefix) {
  const found = new Set();
  const pattern = /[A-Za-z_][A-Za-z0-9_]{2,}/g;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    if (match[0] !== prefix) found.add(match[0]);
  }
  return found;
}

function rank(items, prefix) {
  const lower = prefix.toLowerCase();
  const matching = items.filter((item) => item.label.toLowerCase().startsWith(lower) && item.label !== prefix);
  return matching.sort((a, b) => a.label.length - b.label.length || a.label.localeCompare(b.label));
}

export function complete(text, offset, lang, schema = null, limit = 50) {
  const { from, prefix } = currentWord(text, offset, lang);
  const items = [];
  const seen = new Set();
  const add = (label, detail = "", insertText = label, kind = "word") => {
    if (!seen.has(label)) {
      seen.add(label);
      items.push({ label, detail, insertText, kind });
    }
  };

  const isDsl = lang === "charpente";
  const before = text.slice(0, from);
  const afterDot = /(\w+)\.$/.exec(before);

  if (isDsl && afterDot && schema) {
    const owner = afterDot[1];
    if (schema.enums[owner]) {
      for (const member of schema.enums[owner]) add(member, `${owner}`, member, "enum");
    } else {
      const cls = dslVariables(text)[owner];
      const classes = cls ? [cls] : Object.keys(schema.classes);
      for (const name of classes) {
        for (const method of schema.classes[name] || []) add(method.name, `${name}${method.signature}`, `${method.name}(`, "method");
      }
    }
    return { from, items: rank(items, prefix).slice(0, limit) };
  }
  if (afterDot) {
    return { from, items: [] };
  }
  if (isDsl && schema) {
    for (const name of [...Object.keys(schema.classes), ...Object.keys(schema.enums)]) add(name, "charpente", name, "class");
  }
  const builtin = lang === "python" || isDsl ? PY_WORDS : lang === "cpp" || lang === "c" ? CPP_WORDS : [];
  for (const word of builtin) add(word, "", word, "keyword");
  for (const word of documentWords(text, prefix)) add(word, "", word, "word");
  return { from, items: rank(items, prefix).slice(0, limit) };
}
