// UMSN-IDE Web — 엄슨 편집기 한 탭.
//
// 투명한 <textarea> 를 색칠한 <pre> 위에 겹친다. 글자 입력·한글 IME·되돌리기는 브라우저의
// textarea 가 그대로 하고, 색칠은 언어 서비스 워커(pyumsn.highlight_spans)의 결과로 그린다.
// 새 결과가 올 때까지는 바뀐 곳 앞뒤의 옛 색칠을 밀어서 그대로 쓰므로 깜빡이지 않는다.

const INDENT = "    ";
const WORD_BEFORE = /(?:\.\.[가-힣]*|[\w가-힣$]+[!?]?)$/u;

function escapeHtml(text) {
  return text.replace(/[&<>]/g, (c) => (c === "&" ? "&amp;" : c === "<" ? "&lt;" : "&gt;"));
}

// (줄 1부터, 코드포인트 칸 0부터) → UTF-16 위치
function lineStarts(text) {
  const starts = [0];
  for (let i = 0; i < text.length; i++) if (text.charCodeAt(i) === 10) starts.push(i + 1);
  return starts;
}

function cpToUnits(text, lineStart, cp) {
  let i = lineStart;
  while (cp > 0 && i < text.length) {
    const c = text.charCodeAt(i);
    i += c >= 0xd800 && c <= 0xdbff ? 2 : 1;
    cp--;
  }
  return i;
}

export class Editor {
  constructor(host, options = {}) {
    this.options = options;
    this.root = document.createElement("div");
    this.root.className = "editor";
    this.root.innerHTML = `
      <div class="ed-scroll">
        <div class="ed-content">
          <pre class="ed-gutter" aria-hidden="true"></pre>
          <div class="ed-body">
            <div class="ed-curline" aria-hidden="true"></div>
            <pre class="ed-hl" aria-hidden="true"></pre>
            <textarea class="ed-input" spellcheck="false" autocapitalize="off" autocomplete="off"
              autocorrect="off" wrap="off" aria-label="엄슨 코드"></textarea>
          </div>
        </div>
      </div>`;
    host.appendChild(this.root);
    this.scroller = this.root.querySelector(".ed-scroll");
    this.gutter = this.root.querySelector(".ed-gutter");
    this.body = this.root.querySelector(".ed-body");
    this.hl = this.root.querySelector(".ed-hl");
    this.curline = this.root.querySelector(".ed-curline");
    this.ta = this.root.querySelector(".ed-input");

    this.text = "";
    this.spans = [];     // [시작, 끝, 분류]
    this.problems = [];  // {start, end, msg, suggestion, line, col}
    this.marks = [];     // 찾기 결과 [시작, 끝]
    this.currentMark = -1;
    this.version = 0;
    this.lineCount = 0;
    this.composing = false;

    this.ta.addEventListener("input", () => this._onInput());
    this.ta.addEventListener("keydown", (e) => this._onKey(e));
    this.ta.addEventListener("compositionstart", () => { this.composing = true; });
    this.ta.addEventListener("compositionend", () => { this.composing = false; this._onInput(); });
    for (const ev of ["keyup", "click", "select", "focus"]) {
      this.ta.addEventListener(ev, () => this._onCursor());
    }
    document.addEventListener("selectionchange", () => {
      if (document.activeElement === this.ta) this._onCursor();
    });
    this.ta.addEventListener("mousemove", (e) => this._onHover(e));
    this.ta.addEventListener("mouseleave", () => this.options.onHover && this.options.onHover(null));
    this.ta.addEventListener("contextmenu", (e) => this._onContextMenu(e));
    this.ta.addEventListener("scroll", () => { this.ta.scrollTop = 0; this.ta.scrollLeft = 0; });
  }

  // ---- 값 -------------------------------------------------------------
  getValue() { return this.ta.value; }

  setValue(text) {
    this.ta.value = text;
    this.spans = [];
    this.problems = [];
    this.text = text;
    this.version++;
    this._render();
    this._requestAnalysis();
  }

  focus() { this.ta.focus({ preventScroll: true }); this.ensureCaretVisible(); }
  show(on) { this.root.hidden = !on; if (on) this._render(); }
  destroy() { this.root.remove(); }

  // ---- 색칠 -----------------------------------------------------------
  // 워커가 돌려준 결과. text 가 지금 내용과 다르면 (그 사이 또 고쳤으면) 버린다.
  applyAnalysis(text, result) {
    if (text !== this.ta.value) return;
    const starts = lineStarts(text);
    const at = (line, col) => {
      const ls = starts[Math.min(Math.max(line, 1), starts.length) - 1];
      return cpToUnits(text, ls, col);
    };
    this.spans = result.spans.map(([cat, l1, c1, l2, c2]) => [at(l1, c1), at(l2, c2), cat]);
    this.problems = result.problems
      .filter((p) => p[0] != null)
      .map(([line, col, length, msg, suggestion]) => {
        const start = at(line, col || 0);
        return { start, end: Math.max(start + 1, cpToUnits(text, start, length || 1)), msg, suggestion, line, col: (col || 0) + 1 };
      });
    this._render();
    if (this.options.onProblems) this.options.onProblems(this.problems, result.problems);
  }

  setMarks(marks, current = -1) {
    this.marks = marks;
    this.currentMark = current;
    this._render();
  }

  _shiftRanges(oldText, newText) {
    let p = 0;
    const max = Math.min(oldText.length, newText.length);
    while (p < max && oldText.charCodeAt(p) === newText.charCodeAt(p)) p++;
    let s = 0;
    while (s < max - p && oldText.charCodeAt(oldText.length - 1 - s) === newText.charCodeAt(newText.length - 1 - s)) s++;
    const oldEnd = oldText.length - s;
    const delta = newText.length - oldText.length;
    const move = (start, end) => {
      if (end <= p) return [start, end];
      if (start >= oldEnd) return [start + delta, end + delta];
      return null;
    };
    this.spans = this.spans.flatMap(([a, b, c]) => { const r = move(a, b); return r ? [[r[0], r[1], c]] : []; });
    this.problems = this.problems.flatMap((pr) => {
      const r = move(pr.start, pr.end);
      return r ? [{ ...pr, start: r[0], end: r[1] }] : [];
    });
    this.marks = [];
  }

  _render() {
    const text = this.ta.value;
    const n = text.length;
    const cls = new Array(n);
    for (const [a, b, c] of this.spans) for (let i = Math.max(0, a); i < Math.min(b, n); i++) cls[i] = c;
    const flags = new Uint8Array(n);
    for (const pr of this.problems) for (let i = pr.start; i < Math.min(pr.end, n); i++) flags[i] |= 1;
    this.marks.forEach(([a, b], k) => {
      for (let i = a; i < Math.min(b, n); i++) flags[i] |= k === this.currentMark ? 4 : 2;
    });
    let html = "";
    let i = 0;
    while (i < n) {
      const c = cls[i];
      const f = flags[i];
      let j = i + 1;
      while (j < n && cls[j] === c && flags[j] === f && text.charCodeAt(j) !== 10) j++;
      if (text.charCodeAt(i) === 10) j = i + 1;
      const piece = escapeHtml(text.slice(i, j));
      const names = [];
      if (c) names.push("t-" + c);
      if (f & 1) names.push("t-problem");
      if (f & 2) names.push("t-find");
      if (f & 4) names.push("t-find-cur");
      html += names.length ? `<span class="${names.join(" ")}">${piece}</span>` : piece;
      i = j;
    }
    this.hl.innerHTML = html + "\n ";
    const lines = lineStarts(text).length;
    if (lines !== this.lineCount) {
      this.lineCount = lines;
      let g = "";
      for (let k = 1; k <= lines; k++) g += k + "\n";
      this.gutter.textContent = g;
    }
    this._onCursor();
  }

  _requestAnalysis() {
    clearTimeout(this._timer);
    const delay = this.ta.value.length > 20000 ? 250 : 80;
    this._timer = setTimeout(() => this.options.analyze && this.options.analyze(this), delay);
  }

  _onInput() {
    const text = this.ta.value;
    this._shiftRanges(this.text, text);
    this.text = text;
    this.version++;
    this._render();
    this._requestAnalysis();
    this.ensureCaretVisible();
    if (this.options.onChange) this.options.onChange(this);
    if (!this.composing && this.options.onTyped) this.options.onTyped(this);
  }

  // ---- 커서·좌표 ------------------------------------------------------
  metrics() {
    const style = getComputedStyle(this.ta);
    const lh = parseFloat(style.lineHeight);
    const padTop = parseFloat(style.paddingTop);
    const padLeft = parseFloat(style.paddingLeft);
    if (!this._ctx) this._ctx = document.createElement("canvas").getContext("2d");
    this._ctx.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    return { lh, padTop, padLeft, ctx: this._ctx };
  }

  lineCol(pos = this.ta.selectionStart) {
    const before = this.ta.value.slice(0, pos);
    const line = before.split("\n").length;
    const col = [...before.slice(before.lastIndexOf("\n") + 1)].length + 1;
    return { line, col };
  }

  // 편집기 안의 (x, y) 픽셀 → 글자 위치
  posFromPoint(clientX, clientY) {
    const { lh, padTop, padLeft, ctx } = this.metrics();
    const rect = this.ta.getBoundingClientRect();
    const y = clientY - rect.top - padTop;
    const x = clientX - rect.left - padLeft;
    const text = this.ta.value;
    const starts = lineStarts(text);
    const line = Math.floor(y / lh);
    if (line < 0 || line >= starts.length) return -1;
    const start = starts[line];
    const end = line + 1 < starts.length ? starts[line + 1] - 1 : text.length;
    const lineText = text.slice(start, end).replace(/\t/g, INDENT);
    let w = 0;
    for (let i = 0; i < lineText.length; i++) {
      const cw = ctx.measureText(lineText[i]).width;
      if (x < w + cw) return start + i;
      w += cw;
    }
    return -1;
  }

  caretPixel() {
    const { lh, padTop, padLeft, ctx } = this.metrics();
    const pos = this.ta.selectionEnd;
    const text = this.ta.value;
    const ls = text.lastIndexOf("\n", pos - 1) + 1;
    const line = text.slice(0, pos).split("\n").length - 1;
    const x = padLeft + ctx.measureText(text.slice(ls, pos).replace(/\t/g, INDENT)).width;
    return { x, y: padTop + line * lh, lh };
  }

  ensureCaretVisible() {
    const { x, y, lh } = this.caretPixel();
    const sc = this.scroller;
    const gutterW = this.gutter.offsetWidth;
    if (y < sc.scrollTop) sc.scrollTop = y - 4;
    else if (y + lh > sc.scrollTop + sc.clientHeight) sc.scrollTop = y + lh - sc.clientHeight + 4;
    const left = x + gutterW;
    if (left < sc.scrollLeft + gutterW + 8) sc.scrollLeft = Math.max(0, x - 24);
    else if (left > sc.scrollLeft + sc.clientWidth - 16) sc.scrollLeft = left - sc.clientWidth + 48;
  }

  _onCursor() {
    const { lh, padTop } = this.metrics();
    const { line, col } = this.lineCol();
    this.curline.style.top = `${padTop + (line - 1) * lh}px`;
    this.curline.style.height = `${lh}px`;
    if (this.options.onCursor) this.options.onCursor(this, line, col);
  }

  goto(line, col = 1) {
    const starts = lineStarts(this.ta.value);
    const ls = starts[Math.min(Math.max(line, 1), starts.length) - 1];
    const pos = cpToUnits(this.ta.value, ls, Math.max(col - 1, 0));
    this.ta.focus({ preventScroll: true });
    this.ta.setSelectionRange(pos, pos);
    this.ensureCaretVisible();
    const sc = this.scroller;
    const { y } = this.caretPixel();
    sc.scrollTop = Math.max(0, y - sc.clientHeight / 3);
    this._onCursor();
  }

  select(start, end, focus = true) {
    if (focus) this.ta.focus({ preventScroll: true });
    this.ta.setSelectionRange(start, end);
    this.ensureCaretVisible();
  }

  problemAt(pos) {
    return this.problems.find((p) => pos >= p.start && pos < p.end) || null;
  }

  _onHover(e) {
    if (!this.options.onHover) return;
    const pos = this.posFromPoint(e.clientX, e.clientY);
    this.options.onHover(pos >= 0 ? this.problemAt(pos) : null, e);
  }

  _onContextMenu(e) {
    const pos = this.posFromPoint(e.clientX, e.clientY);
    const problem = pos >= 0 ? this.problemAt(pos) : null;
    if (problem && problem.suggestion && this.options.onProblemMenu) {
      e.preventDefault();
      this.options.onProblemMenu(this, problem, e);
    }
  }

  // ---- 편집 (되돌리기가 되도록 execCommand 사용) ----------------------
  replaceRange(start, end, text, selectInserted = false) {
    this.ta.focus({ preventScroll: true });
    this.ta.setSelectionRange(start, end);
    let ok = false;
    try { ok = document.execCommand("insertText", false, text); } catch (err) { ok = false; }
    if (!ok || this.ta.value.slice(start, start + text.length) !== text) {
      this.ta.setRangeText(text, start, end, "end");
      this._onInput();
    }
    if (selectInserted) this.ta.setSelectionRange(start, start + text.length);
  }

  insert(text) {
    this.replaceRange(this.ta.selectionStart, this.ta.selectionEnd, text);
  }

  wordBeforeCaret() {
    const pos = this.ta.selectionStart;
    const ls = this.ta.value.lastIndexOf("\n", pos - 1) + 1;
    const m = this.ta.value.slice(ls, pos).match(WORD_BEFORE);
    return m ? { word: m[0], start: pos - m[0].length, end: pos } : { word: "", start: pos, end: pos };
  }

  _selectedLines() {
    const v = this.ta.value;
    const s = this.ta.selectionStart;
    let e = this.ta.selectionEnd;
    if (e > s && v[e - 1] === "\n") e--;
    const start = v.lastIndexOf("\n", s - 1) + 1;
    let end = v.indexOf("\n", e);
    if (end < 0) end = v.length;
    return { start, end, lines: v.slice(start, end).split("\n") };
  }

  _editLines(fn) {
    const { start, end, lines } = this._selectedLines();
    const out = fn(lines);
    const text = out.join("\n");
    if (text === lines.join("\n")) return;
    this.replaceRange(start, end, text);
    this.ta.setSelectionRange(start, start + text.length);
  }

  indent() { this._editLines((ls) => ls.map((l) => (l.trim() ? INDENT + l : l))); }

  dedent() {
    this._editLines((ls) => ls.map((l) => l.replace(/^( {1,4}|\t)/, "")));
  }

  toggleComment() {
    this._editLines((ls) => {
      const code = ls.filter((l) => l.trim());
      const allCommented = code.length && code.every((l) => /^\s*#/.test(l));
      if (allCommented) return ls.map((l) => l.replace(/^(\s*)# ?/, "$1"));
      const pad = Math.min(...code.map((l) => l.match(/^\s*/)[0].length));
      return ls.map((l) => (l.trim() ? l.slice(0, pad) + "# " + l.slice(pad) : l));
    });
  }

  _onKey(e) {
    if (e.isComposing || e.keyCode === 229) return;
    if (this.options.onKey && this.options.onKey(this, e)) { e.preventDefault(); return; }
    const mod = e.ctrlKey || e.metaKey;
    const v = this.ta.value;
    const s = this.ta.selectionStart;
    const multi = v.slice(s, this.ta.selectionEnd).includes("\n");
    if (e.key === "Tab" && !mod && !e.altKey) {
      e.preventDefault();
      if (e.shiftKey) this.dedent();
      else if (multi) this.indent();
      else {
        const ls = v.lastIndexOf("\n", s - 1) + 1;
        const col = [...v.slice(ls, s)].length;
        this.insert(" ".repeat(4 - (col % 4)));
      }
    } else if (e.key === "Enter" && !mod && !e.altKey && !e.shiftKey) {
      e.preventDefault();
      const ls = v.lastIndexOf("\n", s - 1) + 1;
      const before = v.slice(ls, s);
      let indent = before.match(/^[ \t]*/)[0];
      const code = before.replace(/#.*$/, "").trimEnd();
      if (/(\.\.한|:)$/.test(code)) indent += INDENT;
      else if (/^\s*(엄슨한|엄슨멈춰|엄슨계속|엄|엄슨던져)(\s|$)/.test(code) && indent.length >= 4) {
        indent = indent.slice(0, indent.length - 4);
      }
      this.insert("\n" + indent);
    } else if (e.key === "Backspace" && !mod && s === this.ta.selectionEnd && s > 0) {
      const ls = v.lastIndexOf("\n", s - 1) + 1;
      const before = v.slice(ls, s);
      if (before.length >= 4 && /^ +$/.test(before)) {
        e.preventDefault();
        const cut = before.length % 4 || 4;
        this.replaceRange(s - cut, s, "");
      }
    } else if (mod && (e.key === "/" || e.code === "Slash")) {
      e.preventDefault();
      this.toggleComment();
    } else if (mod && e.key === "]") {
      e.preventDefault();
      this.indent();
    } else if (mod && e.key === "[") {
      e.preventDefault();
      this.dedent();
    }
  }
}
