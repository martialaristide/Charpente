// A small code editor: a <textarea> (real editing, undo, IME, accessibility) over a highlighted <pre>, with line numbers, diagnostics,
// completion and hover. It is deliberately not Monaco (see docs/adr/0018): about 300 lines, no dependency, replaceable behind this class.
import { highlightLines } from "./highlight.js";
import { debounce, h, clear } from "./util.js";

const SEVERITY_CLASS = { error: "err", warning: "warn", information: "info", hint: "info" };

/** Where the caret is: {line, column} (1-based) for an offset in `text`. */
export function positionOf(text, offset) {
  const before = text.slice(0, offset);
  const line = before.split("\n").length;
  return { line, column: offset - (before.lastIndexOf("\n") + 1) + 1 };
}

export function offsetOf(text, line, column) {
  const lines = text.split("\n");
  const index = Math.min(Math.max(line - 1, 0), lines.length - 1); // a line past the end means the last line
  let offset = 0;
  for (let i = 0; i < index; i++) offset += lines[i].length + 1;
  return offset + Math.min(Math.max(column - 1, 0), lines[index].length);
}

/** The indentation to start a new line with: that of the current line, one level deeper after `{`, `(`, `[` or a trailing `:`. */
export function newLineIndent(text, offset, unit = "    ") {
  const lineStart = text.lastIndexOf("\n", offset - 1) + 1;
  const line = text.slice(lineStart, offset);
  const indent = /^[ \t]*/.exec(line)[0];
  return /[{(\[:]\s*$/.test(line) ? indent + unit : indent;
}

export class Editor {
  constructor(container, options = {}) {
    this.options = options;
    this.language = "text";
    this.eol = "\n";
    this.diagnostics = [];
    this.breakpoints = new Set(); // 1-based lines with a breakpoint
    this.execLine = null; // 1-based line where the debugger is stopped
    this.popup = null;
    this.popupItems = [];
    this.popupIndex = 0;
    this.popupFrom = 0;

    this.gutter = h("div", { class: "gutter", "aria-hidden": "true" });
    this.highlight = h("pre", { class: "hl", "aria-hidden": "true" });
    this.input = h("textarea", {
      class: "input", spellcheck: "false", autocapitalize: "off", autocomplete: "off", wrap: "off", "aria-label": options.label || "Editor",
    });
    this.popupElement = h("ul", { class: "completion", role: "listbox", hidden: true });
    this.hover = h("div", { class: "hover-tip", role: "tooltip", hidden: true });
    this.root = h("div", { class: "editor" }, this.gutter, h("div", { class: "code-wrap" }, this.highlight, this.input), this.popupElement, this.hover);
    container.append(this.root);

    this.rerender = debounce(() => this.render(), 20);
    this.gutter.addEventListener("mousedown", (event) => {
      const line = Number(event.target.dataset && event.target.dataset.line);
      if (line && this.options.onBreakpoint) {
        event.preventDefault();
        this.options.onBreakpoint(line);
      }
    });
    this.input.addEventListener("input", () => this.onInput());
    this.input.addEventListener("scroll", () => this.syncScroll());
    this.input.addEventListener("keydown", (event) => this.onKey(event));
    this.input.addEventListener("click", () => {
      this.hidePopup();
      this.reportCursor();
    });
    this.input.addEventListener("keyup", (event) => {
      if (!event.key.startsWith("Arrow") && event.key !== "Home" && event.key !== "End") return;
      this.reportCursor();
    });
    this.input.addEventListener("blur", () => setTimeout(() => this.hidePopup(), 120));
    this.input.addEventListener("mousemove", debounce((event) => this.onHover(event), 350));
    this.input.addEventListener("mouseleave", () => (this.hover.hidden = true));
    this.autoComplete = debounce(() => this.triggerCompletion(false), 160);
  }

  // ------------------------------------------------------------------ content
  open({ text, language = "text" }) {
    this.language = language;
    this.eol = text.includes("\r\n") ? "\r\n" : "\n"; // the textarea works in \n: the file's own line endings are put back on save
    this.input.value = text.replace(/\r\n/g, "\n");
    this.diagnostics = [];
    this.input.setSelectionRange(0, 0);
    this.input.scrollTop = 0;
    this.input.scrollLeft = 0;
    this.render();
    this.reportCursor();
  }

  /** The text as it should be written to disk (original line endings). */
  getText() {
    return this.eol === "\r\n" ? this.input.value.replace(/\n/g, "\r\n") : this.input.value;
  }

  setText(text) {
    this.input.value = text.replace(/\r\n/g, "\n");
    this.render();
  }

  focus() {
    this.input.focus();
  }

  setDiagnostics(diagnostics) {
    this.diagnostics = diagnostics;
    this.render();
  }

  setBreakpoints(lines) {
    this.breakpoints = new Set(lines);
    this.render();
  }

  /** Mark the line where the program is stopped (null clears it) and scroll it into view. */
  setExecutionLine(line) {
    this.execLine = line;
    this.render();
    if (line) this.goTo(line, 1, { focus: false });
  }

  goTo(line, column = 1, { focus = true } = {}) {
    const offset = offsetOf(this.input.value, line, column);
    if (focus) this.input.focus();
    this.input.setSelectionRange(offset, offset);
    const lineHeight = this.lineHeight();
    this.input.scrollTop = Math.max(0, (line - 3) * lineHeight);
    this.syncScroll();
    this.reportCursor();
  }

  lineHeight() {
    return parseFloat(getComputedStyle(this.input).lineHeight) || 20;
  }

  charWidth() {
    if (!this._charWidth) {
      const probe = h("span", { class: "hl", style: "position:absolute;visibility:hidden;white-space:pre" }, "0".repeat(50));
      this.root.append(probe);
      this._charWidth = probe.getBoundingClientRect().width / 50 || 8;
      probe.remove();
    }
    return this._charWidth;
  }

  // ------------------------------------------------------------------ rendering
  render() {
    const text = this.input.value;
    const lines = highlightLines(text, this.language);
    const worst = new Map();
    for (const d of this.diagnostics) {
      const rank = { error: 3, warning: 2, information: 1, hint: 0 };
      const current = worst.get(d.line);
      if (current === undefined || rank[d.severity] > rank[current]) worst.set(d.line, d.severity);
    }
    this.highlight.innerHTML =
      lines.map((html, index) => {
        const severity = worst.get(index);
        const classes = [severity ? `ln-${SEVERITY_CLASS[severity]}` : "", this.execLine === index + 1 ? "ln-exec" : ""].filter(Boolean).join(" ");
        return classes ? `<span class="ln ${classes}">${html || " "}</span>` : html;
      }).join("\n") + "\n";
    clear(this.gutter);
    const numbers = [];
    for (let i = 0; i < lines.length; i++) {
      const severity = worst.get(i);
      const classes = [severity ? `mark-${SEVERITY_CLASS[severity]}` : "", this.breakpoints.has(i + 1) ? "bp" : "", this.execLine === i + 1 ? "exec" : ""].filter(Boolean).join(" ");
      numbers.push(h("span", { class: classes, "data-line": i + 1, title: this.messagesOn(i) }, String(i + 1)));
      numbers.push("\n");
    }
    this.gutter.append(...numbers);
    this.syncScroll();
  }

  messagesOn(line) {
    return this.diagnostics.filter((d) => d.line === line).map((d) => d.message).join("\n") || null;
  }

  syncScroll() {
    this.highlight.scrollTop = this.input.scrollTop;
    this.highlight.scrollLeft = this.input.scrollLeft;
    this.gutter.scrollTop = this.input.scrollTop;
  }

  reportCursor() {
    if (this.options.onCursor) this.options.onCursor(positionOf(this.input.value, this.input.selectionStart));
  }

  // ------------------------------------------------------------------ input
  onInput() {
    this.rerender();
    if (this.options.onChange) this.options.onChange(this.input.value);
    this.reportCursor();
    const offset = this.input.selectionStart;
    const before = this.input.value.slice(Math.max(0, offset - 3), offset);
    if (/[A-Za-z_.:>#]{2}$/.test(before) || before.endsWith(".")) this.autoComplete();
    else this.hidePopup();
  }

  insert(text) {
    this.input.focus();
    if (!document.execCommand || !document.execCommand("insertText", false, text)) {
      const { selectionStart: start, selectionEnd: end, value } = this.input;
      this.input.value = value.slice(0, start) + text + value.slice(end);
      this.input.setSelectionRange(start + text.length, start + text.length);
      this.onInput();
    }
  }

  indentUnit() {
    return this.language === "python" || this.language === "charpente" || this.language === "cpp" ? "    " : "  ";
  }

  onKey(event) {
    const mod = event.ctrlKey || event.metaKey;
    if (this.popup) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        this.popupIndex = (this.popupIndex + (event.key === "ArrowDown" ? 1 : -1) + this.popupItems.length) % this.popupItems.length;
        this.paintPopup();
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        this.acceptCompletion();
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        this.hidePopup();
        return;
      }
    }
    if (mod && event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (this.options.onSave) this.options.onSave();
    } else if (mod && event.code === "Space") {
      event.preventDefault();
      this.triggerCompletion(true);
    } else if (event.key === "Tab" && !mod && !event.altKey) {
      event.preventDefault();
      this.indentSelection(event.shiftKey);
    } else if (event.key === "Enter" && !mod && !event.shiftKey && !event.altKey) {
      event.preventDefault();
      this.insert("\n" + newLineIndent(this.input.value, this.input.selectionStart, this.indentUnit()));
    } else if (event.key === "F12" && this.options.onDefinition) {
      event.preventDefault();
      this.options.onDefinition(positionOf(this.input.value, this.input.selectionStart));
    }
  }

  indentSelection(reverse) {
    const { selectionStart: start, selectionEnd: end, value } = this.input;
    const unit = this.indentUnit();
    if (start === end && !reverse) {
      this.insert(unit);
      return;
    }
    const lineStart = value.lastIndexOf("\n", start - 1) + 1;
    const block = value.slice(lineStart, end);
    const changed = block.split("\n").map((line) => {
      if (!reverse) return unit + line;
      return line.startsWith(unit) ? line.slice(unit.length) : line.replace(/^[ \t]{1,4}/, "");
    }).join("\n");
    this.input.setSelectionRange(lineStart, end);
    this.insert(changed);
    this.input.setSelectionRange(lineStart, lineStart + changed.length);
  }

  // ------------------------------------------------------------------ completion
  async triggerCompletion(explicit) {
    if (!this.options.complete) return;
    const offset = this.input.selectionStart;
    let result;
    try {
      result = await this.options.complete(this.input.value, offset, this.language, explicit);
    } catch {
      return;
    }
    if (!result || !result.items.length || this.input.selectionStart !== offset) return this.hidePopup();
    this.popupItems = result.items;
    this.popupFrom = result.from;
    this.popupIndex = 0;
    this.popup = true;
    this.paintPopup();
  }

  paintPopup() {
    clear(this.popupElement);
    this.popupItems.slice(0, 12).forEach((item, index) => {
      const row = h("li", { role: "option", class: index === this.popupIndex ? "selected" : "", "aria-selected": index === this.popupIndex },
        h("span", { class: `kind kind-${item.kind}` }), h("span", { class: "label" }, item.label), h("span", { class: "detail" }, item.detail || ""));
      row.addEventListener("mousedown", (event) => {
        event.preventDefault();
        this.popupIndex = index;
        this.acceptCompletion();
      });
      this.popupElement.append(row);
    });
    const { line, column } = positionOf(this.input.value, this.popupFrom);
    this.popupElement.style.left = `${Math.max(0, this.gutter.offsetWidth + 8 + (column - 1) * this.charWidth() - this.input.scrollLeft)}px`;
    this.popupElement.style.top = `${8 + line * this.lineHeight() - this.input.scrollTop}px`;
    this.popupElement.hidden = false;
  }

  hidePopup() {
    this.popup = null;
    this.popupElement.hidden = true;
  }

  acceptCompletion() {
    const item = this.popupItems[this.popupIndex];
    if (!item) return;
    const end = this.input.selectionStart;
    this.hidePopup();
    this.input.setSelectionRange(this.popupFrom, end);
    this.insert(item.insertText ?? item.label);
  }

  // ------------------------------------------------------------------ hover
  async onHover(event) {
    if (!this.options.hover) return;
    const rect = this.input.getBoundingClientRect();
    const line = Math.floor((event.clientY - rect.top + this.input.scrollTop - 8) / this.lineHeight()) + 1;
    const column = Math.floor((event.clientX - rect.left + this.input.scrollLeft - 8) / this.charWidth()) + 1;
    if (line < 1 || column < 1) return;
    const own = this.diagnostics.filter((d) => d.line === line - 1).map((d) => d.message);
    let text = own.join("\n");
    try {
      const extra = await this.options.hover({ line, column });
      if (extra) text = text ? `${text}\n\n${extra}` : extra;
    } catch {
      /* no language server: diagnostics only */
    }
    if (!text) {
      this.hover.hidden = true;
      return;
    }
    this.hover.textContent = text;
    this.hover.style.left = `${event.clientX - rect.left + 12}px`;
    this.hover.style.top = `${event.clientY - rect.top + 16}px`;
    this.hover.hidden = false;
  }
}
