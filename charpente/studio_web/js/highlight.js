// Syntax highlighting for the editor: a small tokenizer per language, no dependency. Pure: text in, tokens / HTML lines out.
import { escapeHtml } from "./util.js";

const CPP_KEYWORDS = "alignas alignof asm auto break case catch class concept const consteval constexpr constinit const_cast continue co_await co_return co_yield decltype default delete do dynamic_cast else enum explicit export extern false final for friend goto if inline mutable namespace new noexcept nullptr operator override private protected public register reinterpret_cast requires return sizeof static static_assert static_cast struct switch template this thread_local throw true try typedef typeid typename union using virtual volatile while";
const CPP_TYPES = "bool char char8_t char16_t char32_t double float int long short signed unsigned void wchar_t size_t ssize_t ptrdiff_t intptr_t uintptr_t int8_t int16_t int32_t int64_t uint8_t uint16_t uint32_t uint64_t std string vector map set array unique_ptr shared_ptr optional variant";
const PY_KEYWORDS = "and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield";
const PY_BUILTINS = "True False None self cls print len range list dict set tuple str int float bool open super";
export const DSL_NAMES = {
  classes: ["Workspace", "Target", "Kind", "Language", "Rule", "Toolchain"],
  methods: ["sources", "exclude", "kind", "standard", "uses", "uses_public", "include_dirs", "public_include_dirs", "define", "defines", "public_defines",
    "options", "option", "configurations", "platforms", "requires", "kit", "package_settings", "platform_settings", "output_prefix", "output_extension",
    "compile_flags", "link_flags", "link_libraries", "language", "when", "overlay", "harmony", "android", "ios", "embedded", "hook", "rule"],
};

const words = (list) => `\\b(?:${list.trim().split(/\s+/).join("|")})\\b`;

const STRING_DQ = String.raw`"(?:\\.|[^"\\\n])*"?`;
const STRING_SQ = String.raw`'(?:\\.|[^'\\\n])*'?`;
const NUMBER = String.raw`\b(?:0[xX][0-9a-fA-F_']+|0[bB][01_']+|\d[\d_']*(?:\.\d*)?(?:[eE][+-]?\d+)?)[uUlLfFjJ]*\b`;

function languages() {
  return {
    cpp: [
      ["comment", String.raw`//[^\n]*|/\*[\s\S]*?(?:\*/|(?![\s\S]))`],
      ["pre", String.raw`^[ \t]*#[ \t]*\w+`],
      ["string", `${STRING_DQ}|${STRING_SQ}`],
      ["number", NUMBER],
      ["keyword", words(CPP_KEYWORDS)],
      ["type", words(CPP_TYPES)],
      ["fn", String.raw`\b[A-Za-z_]\w*(?=\s*\()`],
    ],
    python: [
      ["comment", String.raw`#[^\n]*`],
      ["string", String.raw`(?:[rRbBfFuU]{1,2})?(?:"""[\s\S]*?(?:"""|(?![\s\S]))|'''[\s\S]*?(?:'''|(?![\s\S])))|(?:[rRbBfFuU]{1,2})?(?:${STRING_DQ}|${STRING_SQ})`],
      ["deco", String.raw`^[ \t]*@\w[\w.]*`],
      ["number", NUMBER],
      ["keyword", words(PY_KEYWORDS)],
      ["type", words(PY_BUILTINS)],
      ["fn", String.raw`\b[A-Za-z_]\w*(?=\s*\()`],
    ],
    json: [
      ["key", String.raw`"(?:\\.|[^"\\\n])*"(?=\s*:)`],
      ["string", STRING_DQ],
      ["number", String.raw`-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b`],
      ["keyword", String.raw`\b(?:true|false|null)\b`],
    ],
    toml: [
      ["comment", String.raw`#[^\n]*`],
      ["heading", String.raw`^[ \t]*\[\[?[^\]\n]+\]\]?`],
      ["string", `${STRING_DQ}|${STRING_SQ}`],
      ["number", NUMBER],
      ["keyword", String.raw`\b(?:true|false)\b`],
      ["key", String.raw`^[ \t]*[\w.-]+(?=\s*=)`],
    ],
    markdown: [
      ["heading", String.raw`^#{1,6}[^\n]*`],
      ["comment", String.raw`^(?:\`\`\`|~~~)[^\n]*`],
      ["string", String.raw`\`[^\`\n]+\``],
      ["keyword", String.raw`^[ \t]*(?:[-*+]|\d+\.)(?=\s)`],
    ],
    cmake: [
      ["comment", String.raw`#[^\n]*`],
      ["string", STRING_DQ],
      ["var", String.raw`\$\{[^}\n]*\}`],
      ["keyword", String.raw`\b(?:if|elseif|else|endif|foreach|endforeach|while|endwhile|function|endfunction|macro|endmacro|return)\b`],
      ["fn", String.raw`\b[A-Za-z_]\w*(?=\s*\()`],
    ],
    shell: [
      ["comment", String.raw`#[^\n]*`],
      ["string", `${STRING_DQ}|${STRING_SQ}`],
      ["var", String.raw`\$\{?\w+\}?`],
      ["keyword", words("if then else elif fi for do done while case esac function return exit")],
    ],
    yaml: [
      ["comment", String.raw`#[^\n]*`],
      ["string", `${STRING_DQ}|${STRING_SQ}`],
      ["key", String.raw`^[ \t-]*[\w.-]+(?=\s*:)`],
      ["number", NUMBER],
      ["keyword", String.raw`\b(?:true|false|null)\b`],
    ],
    glsl: [
      ["comment", String.raw`//[^\n]*|/\*[\s\S]*?(?:\*/|(?![\s\S]))`],
      ["pre", String.raw`^[ \t]*#[ \t]*\w+`],
      ["number", NUMBER],
      ["keyword", words("if else for while do return break continue discard in out inout uniform layout struct const precision highp mediump lowp void")],
      ["type", words("float int uint bool vec2 vec3 vec4 ivec2 ivec3 ivec4 mat2 mat3 mat4 sampler2D samplerCube")],
      ["fn", String.raw`\b[A-Za-z_]\w*(?=\s*\()`],
    ],
  };
}

const ALIASES = { c: "cpp", java: "cpp", kotlin: "cpp", swift: "cpp", typescript: "cpp", javascript: "cpp", groovy: "cpp", charpente: "python", powershell: "shell" };
const compiled = new Map();
let dslPattern = null;

/** Replace the names highlighted specially in `.charpente` files (called with the server's DSL schema when it arrives). */
export function setDslNames(classes, methods) {
  dslPattern = { classes, methods };
  compiled.delete("charpente");
}

function build(lang) {
  if (compiled.has(lang)) return compiled.get(lang);
  const rules = [...(languages()[ALIASES[lang] || lang] || [])];
  if (lang === "charpente") {
    const names = dslPattern || DSL_NAMES;
    rules.unshift(["dsl", String.raw`(?<=\.)(?:${names.methods.join("|")})(?=\s*\()`]);
    rules.unshift(["type", words(names.classes.join(" "))]);
  }
  const regex = rules.length ? new RegExp(rules.map(([, source]) => `(${source})`).join("|"), "gm") : null;
  const result = { rules, regex };
  compiled.set(lang, result);
  return result;
}

/** [{type, text}] covering the whole text; `type` is "" for plain text. Concatenating the texts gives back the input. */
export function tokenize(text, lang) {
  const { rules, regex } = build(lang);
  if (!regex) return [{ type: "", text }];
  const tokens = [];
  let last = 0;
  regex.lastIndex = 0;
  let match;
  while ((match = regex.exec(text)) !== null) {
    if (match[0] === "") {
      regex.lastIndex++;
      continue;
    }
    if (match.index > last) tokens.push({ type: "", text: text.slice(last, match.index) });
    let group = 1;
    while (match[group] === undefined) group++;
    tokens.push({ type: rules[group - 1][0], text: match[0] });
    last = match.index + match[0].length;
  }
  if (last < text.length) tokens.push({ type: "", text: text.slice(last) });
  return tokens;
}

/** One HTML string per line (a token that spans lines, like a block comment, is closed and reopened at each line break). */
export function highlightLines(text, lang) {
  const lines = [""];
  for (const token of tokenize(text, lang)) {
    const pieces = token.text.split("\n");
    pieces.forEach((piece, index) => {
      if (index > 0) lines.push("");
      if (piece === "") return;
      const escaped = escapeHtml(piece);
      lines[lines.length - 1] += token.type ? `<span class="tok-${token.type}">${escaped}</span>` : escaped;
    });
  }
  return lines;
}
