// UMSN-IDE Web — 화면과 두 워커(언어 서비스, 실행기)를 잇는다.
import { Editor } from "./editor.js";

const STORE_KEY = "umsn-ide-web/v1";
const WORK_PREFIX = "/home/pyodide/work/";
const EXAMPLES = [
  ["안녕", "첫 프로그램, 엄?(input)"],
  ["구구단", "함수와 반복"],
  ["클래스", "엄슨틀(class)"],
  ["넘파이", "numpy"],
  ["판다스", "pandas"],
  ["맷플롯", "matplotlib 그래프"],
  ["티킨터_계산기", "tkinter (데스크톱 전용)"],
];
const WELCOME = `# UMSN-IDE Web 에 오신 것을 환영하슨!  F5 또는 [엄슨!] 버튼으로 실행하세요.
# 단어장(F1)에서 엄슨 단어를 찾아 누르면 코드에 들어갑니다.

엄슨하다 인사..하이름..다..한
    """이름을 받아 인사를 돌려준다."""
    엄슨한 형"안녕, {이름}! 엄슨!"

엄슨마다 번호 엄속 엄범위..하1..고 4..다..한
    어엄슨 번호 ..나머지 2 ..같슨 0..한
        엄!..하번호..고 "짝수"..다
    슨엄..한
        엄!..하번호..고 "홀수"..다

엄!..하인사..하"엄슨"..다..다
`;
const IMAGE_TYPES = { png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif", svg: "image/svg+xml", webp: "image/webp" };

const $ = (sel) => document.querySelector(sel);
const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  for (const kid of kids) node.append(kid);
  return node;
};

// ---------------------------------------------------------------------------
// 상태와 저장
// ---------------------------------------------------------------------------
const state = {
  files: new Map(), // 이름 → {name, kind: "umsn" | "data", text?, bytes?, editor?}
  tabs: [],
  active: null,
  theme: null,
  fontSize: 15,
  root: "./",
  running: false,
  waitingInput: false,
  typeahead: [],
  words: [],
  langReady: false,
  runReady: false,
  interactive: false,
  info: null,
};

function loadStore() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY) || "null"); } catch (err) { return null; }
}

let saveTimer = null;
function saveStore() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const files = {};
    for (const f of state.files.values()) if (f.kind === "umsn") files[f.name] = f.editor ? f.editor.getValue() : f.text;
    const data = { files, tabs: state.tabs, active: state.active, theme: state.theme, fontSize: state.fontSize, args: $("#run-args").value };
    try { localStorage.setItem(STORE_KEY, JSON.stringify(data)); } catch (err) { /* 저장 공간 없음·사생활 보호 모드 */ }
  }, 300);
}

function status(text, bad = false) {
  const node = $("#st-msg");
  node.textContent = text;
  node.classList.toggle("bad", bad);
}

// ---------------------------------------------------------------------------
// 워커
// ---------------------------------------------------------------------------
class PyWorker {
  constructor(role, onEvent, extra = {}) {
    this.role = role;
    this.onEvent = onEvent;
    this.pending = new Map();
    this.nextId = 1;
    this.worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
    this.ready = new Promise((resolve, reject) => { this._resolve = resolve; this._reject = reject; });
    this.worker.onmessage = (e) => this._onMessage(e.data);
    this.worker.onerror = (e) => { this._reject(new Error(e.message || "워커 오류")); onEvent({ type: "fatal", error: e.message || "워커를 시작하지 못했슨" }); };
    this.worker.postMessage({ type: "init", role, root: state.root, webRoot: new URL("./", import.meta.url).href, ...extra });
  }

  _onMessage(msg) {
    if (msg.type === "ready") this._resolve(msg);
    if (msg.type === "fatal") this._reject(new Error(msg.error));
    if (msg.type === "reply") {
      const p = this.pending.get(msg.id);
      this.pending.delete(msg.id);
      if (p) (msg.ok ? p.resolve(msg.result) : p.reject(new Error(msg.error)));
      return;
    }
    this.onEvent(msg);
  }

  async call(op, args = {}) {
    await this.ready;
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker.postMessage({ type: "call", id, op, args });
    });
  }

  post(msg, transfer) { this.worker.postMessage(msg, transfer || []); }
  terminate() { this.worker.terminate(); }
}

let lang = null;
let runner = null;
let stdinBuffer = null;
let interruptBuffer = null;

async function detectRoot() {
  for (const root of ["./", "../"]) {
    try {
      const res = await fetch(root + "pyumsn/__init__.py", { method: "HEAD", cache: "no-cache" });
      if (res.ok) return root;
    } catch (err) { /* 다음 후보 */ }
  }
  throw new Error("pyumsn 패키지 파일을 찾지 못했슨 (pyumsn/ 또는 ../pyumsn/)");
}

function startLang() {
  lang = new PyWorker("lang", (msg) => {
    if (msg.type === "fatal") { status(`언어 서비스 오류: ${msg.error}`, true); }
  });
  lang.ready.then((info) => {
    state.langReady = true;
    state.info = info;
    $("#help-version").textContent = `PyUMSN ${info.version} · 파이썬 ${info.python} · Pyodide ${info.pyodide}`;
    for (const f of state.files.values()) if (f.editor) scheduleAnalysis(f.editor);
    lang.call("words").then((w) => { state.words = w; renderWords(); });
  }).catch((err) => status(`파이썬을 불러오지 못했슨: ${err.message}`, true));
}

function startRunner() {
  state.runReady = false;
  updateRunButtons();
  const extra = {};
  if (window.crossOriginIsolated && typeof SharedArrayBuffer !== "undefined") {
    stdinBuffer = new SharedArrayBuffer(8 + 65536);
    interruptBuffer = new SharedArrayBuffer(4);
    extra.stdinBuffer = stdinBuffer;
    extra.interruptBuffer = interruptBuffer;
  } else {
    stdinBuffer = interruptBuffer = null;
  }
  runner = new PyWorker("run", onRunEvent, extra);
  runner.ready.then((info) => {
    state.runReady = true;
    state.interactive = info.interactive;
    $("#st-engine").textContent = `엄슨 ${info.version} · 파이썬 ${info.python} · Pyodide ${info.pyodide}`;
    $("#st-input").textContent = info.interactive ? "대화형 입력 ✓" : "입력: 미리 적기";
    $("#st-input").title = info.interactive
      ? "실행 중에 엄?(input) 에 바로 답할 수 있슨"
      : "이 브라우저/서버에서는 cross-origin isolation 이 안 되어, 실행 전에 입력 칸에 적어 둔 줄을 엄?(input) 에 차례로 넣슨";
    updateRunButtons();
  }).catch((err) => {
    $("#st-engine").textContent = "실행기 오류";
    status(`실행기를 준비하지 못했슨: ${err.message}`, true);
  });
}

// 언어 서비스는 한 번에 하나씩: 결과가 오기 전에 또 고치면 마지막 것만 다시 보낸다.
let analysisBusy = false;
const analysisQueue = new Set();
function scheduleAnalysis(editor) {
  if (!state.langReady) return;
  analysisQueue.add(editor);
  pumpAnalysis();
}
function pumpAnalysis() {
  if (analysisBusy || !analysisQueue.size) return;
  const editor = analysisQueue.values().next().value;
  analysisQueue.delete(editor);
  const text = editor.getValue();
  analysisBusy = true;
  lang.call("analyze", { src: text })
    .then((result) => editor.applyAnalysis(text, result))
    .catch((err) => status(`검사 오류: ${err.message}`, true))
    .finally(() => { analysisBusy = false; pumpAnalysis(); });
}

// ---------------------------------------------------------------------------
// 파일과 탭
// ---------------------------------------------------------------------------
function activeFile() { return state.files.get(state.active) || null; }
function activeEditor() { const f = activeFile(); return f && f.editor; }

function uniqueName(base, ext = ".umsn") {
  let name = base + ext;
  for (let i = 2; state.files.has(name); i++) name = `${base}_${i}${ext}`;
  return name;
}

function validName(name) {
  return name && !/[\\/:*?"<>|]/.test(name) && name !== "." && name !== ".." && !name.startsWith(".");
}

function ensureEditor(file) {
  if (file.editor) return file.editor;
  const editor = new Editor($("#editors"), {
    analyze: scheduleAnalysis,
    onChange: () => { saveStore(); schedulePythonView(); if (!$("#findbar").hidden) updateFind(false); },
    onCursor: (ed, line, col) => { if (ed === activeEditor()) $("#st-pos").textContent = `줄 ${line}, 칸 ${col}`; },
    onProblems: (problems) => { if (editor === activeEditor()) showProblemCount(problems); },
    onHover: showProblemTooltip,
    onProblemMenu: showProblemMenu,
    onKey: onEditorKey,
    onTyped: (ed) => { const w = ed.wordBeforeCaret().word; if (completeOpen() || w.startsWith("..") ) updateComplete(ed, true); },
  });
  editor.setValue(file.text || "");
  editor.show(false);
  file.editor = editor;
  return editor;
}

function addFile(name, props) {
  const file = { name, ...props };
  state.files.set(name, file);
  renderFiles();
  return file;
}

function openTab(name) {
  const file = state.files.get(name);
  if (!file || file.kind !== "umsn") return;
  ensureEditor(file);
  if (!state.tabs.includes(name)) state.tabs.push(name);
  activate(name);
}

function activate(name) {
  state.active = name;
  for (const f of state.files.values()) if (f.editor) f.editor.show(f.name === name);
  const ed = activeEditor();
  if (ed) {
    ed.focus();
    showProblemCount(ed.problems);
  }
  renderTabs();
  renderFiles();
  schedulePythonView(true);
  closeComplete();
  saveStore();
  document.title = name ? `${name} — UMSN-IDE Web` : "UMSN-IDE Web";
}

function closeTab(name) {
  const i = state.tabs.indexOf(name);
  if (i < 0) return;
  state.tabs.splice(i, 1);
  const file = state.files.get(name);
  if (file && file.editor) { file.text = file.editor.getValue(); file.editor.destroy(); file.editor = null; }
  if (state.active === name) activate(state.tabs[Math.min(i, state.tabs.length - 1)] || null);
  else { renderTabs(); saveStore(); }
}

function deleteFile(name) {
  if (!confirm(`'${name}' 을(를) 지울까요? 되돌릴 수 없슨.`)) return;
  closeTab(name);
  state.files.delete(name);
  renderFiles();
  saveStore();
}

function renameFile(name) {
  const file = state.files.get(name);
  let next = prompt("새 이름", name);
  if (!next || next === name) return;
  next = next.trim();
  if (file.kind === "umsn" && !next.endsWith(".umsn")) next += ".umsn";
  if (!validName(next)) { alert("쓸 수 없는 이름이슨."); return; }
  if (state.files.has(next)) { alert(`'${next}' 은(는) 이미 있슨.`); return; }
  state.files.delete(name);
  file.name = next;
  state.files.set(next, file);
  state.tabs = state.tabs.map((t) => (t === name ? next : t));
  if (state.active === name) state.active = next;
  renderTabs();
  renderFiles();
  saveStore();
}

function newFile() {
  let name = prompt("새 파일 이름", uniqueName("새_엄슨"));
  if (!name) return;
  name = name.trim();
  if (!name.endsWith(".umsn")) name += ".umsn";
  if (!validName(name)) { alert("쓸 수 없는 이름이슨."); return; }
  if (state.files.has(name)) { openTab(name); return; }
  addFile(name, { kind: "umsn", text: "" });
  openTab(name);
}

function renderTabs() {
  const box = $("#tabs");
  box.replaceChildren();
  for (const name of state.tabs) {
    const tab = el("div", { className: "tab" + (name === state.active ? " active" : ""), role: "tab", tabIndex: 0, title: name });
    tab.setAttribute("aria-selected", name === state.active);
    tab.append(el("span", { textContent: name }));
    const close = el("button", { className: "close", textContent: "✕", title: "탭 닫기" });
    close.setAttribute("aria-label", `${name} 탭 닫기`);
    close.onclick = (e) => { e.stopPropagation(); closeTab(name); };
    tab.append(close);
    tab.onclick = () => activate(name);
    tab.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(name); } };
    tab.onauxclick = (e) => { if (e.button === 1) closeTab(name); };
    box.append(tab);
  }
}

function renderFiles() {
  const list = $("#file-list");
  list.replaceChildren();
  const files = [...state.files.values()].sort((a, b) =>
    (a.kind === b.kind ? a.name.localeCompare(b.name, "ko") : a.kind === "umsn" ? -1 : 1));
  for (const f of files) {
    const li = el("li", { className: f.name === state.active ? "active" : "", title: f.name });
    li.append(el("span", { className: "kind", textContent: f.kind === "umsn" ? "엄" : "▤" }));
    li.append(el("span", { className: "name", textContent: f.name }));
    const act = (label, text, fn) => {
      const b = el("button", { className: "act", textContent: text, title: label });
      b.setAttribute("aria-label", `${f.name} ${label}`);
      b.onclick = (e) => { e.stopPropagation(); fn(); };
      li.append(b);
    };
    if (f.kind === "umsn") act("이름 바꾸기", "✎", () => renameFile(f.name));
    act("내려받기", "⬇", () => downloadFile(f.name));
    act("지우기", "✕", () => deleteFile(f.name));
    li.onclick = () => {
      if (f.kind === "umsn") openTab(f.name);
      else if (isImage(f.name)) showImage(f.name, f.bytes);
      else downloadFile(f.name);
      $("#sidebar").classList.remove("open");
    };
    li.ondblclick = () => { if (f.kind === "umsn") renameFile(f.name); };
    list.append(li);
  }
}

function fileText(name) {
  const f = state.files.get(name);
  return f.editor ? f.editor.getValue() : f.text;
}

function download(name, blob) {
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadFile(name) {
  const f = state.files.get(name);
  if (!f) return;
  const blob = f.kind === "umsn"
    ? new Blob([fileText(name)], { type: "text/plain;charset=utf-8" })
    : new Blob([f.bytes]);
  download(name, blob);
}

const isImage = (name) => (name.split(".").pop().toLowerCase() in IMAGE_TYPES);

async function openFiles(fileList) {
  for (const file of fileList) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const lower = file.name.toLowerCase();
    if (lower.endsWith(".umsn") || lower.endsWith(".py")) {
      let text;
      try {
        text = new TextDecoder("utf-8", { fatal: true }).decode(bytes).replace(/^\uFEFF/, "");
      } catch (err) {
        consoleLine(`엄슨 오류! ${file.name}: UTF-8 이 아닌 파일은 쓸 수 없슨! 파일을 UTF-8 로 저장하세요.\n`, "err");
        continue;
      }
      if (lower.endsWith(".py")) {
        const res = await lang.call("to_umsn", { src: text, name: file.name });
        if (!res.ok) { consoleLine(res.error + "\n", "err"); continue; }
        const name = uniqueName(file.name.replace(/\.py$/i, ""));
        addFile(name, { kind: "umsn", text: res.code });
        openTab(name);
        consoleLine(`${file.name} (파이썬) → ${name} (엄슨) 으로 바꿨슨.\n`, "info");
      } else {
        const existing = state.files.get(file.name);
        if (existing && fileText(file.name) !== text && !confirm(`'${file.name}' 이(가) 이미 있슨. 덮어쓸까요?`)) continue;
        if (existing && existing.editor) existing.editor.setValue(text);
        else addFile(file.name, { kind: "umsn", text });
        openTab(file.name);
      }
    } else {
      addFile(file.name, { kind: "data", bytes });
      consoleLine(`자료 파일 '${file.name}' 을(를) 작업 폴더에 넣었슨 (${bytes.length.toLocaleString()} 바이트).\n`, "info");
    }
  }
  saveStore();
}

async function openExample(name) {
  const fname = name + ".umsn";
  if (state.files.has(fname)) { openTab(fname); return; }
  try {
    const res = await fetch(`${state.root}examples/${encodeURIComponent(fname)}`);
    if (!res.ok) throw new Error(res.status);
    addFile(fname, { kind: "umsn", text: await res.text() });
    openTab(fname);
  } catch (err) {
    status(`예제를 불러오지 못했슨: ${fname} (${err.message})`, true);
  }
}

// ---------------------------------------------------------------------------
// 콘솔
// ---------------------------------------------------------------------------
const out = () => $("#console-out");
let stderrRest = "";
const MAX_CONSOLE = 400000;

function atBottom() {
  const o = out();
  return o.scrollHeight - o.scrollTop - o.clientHeight < 40;
}

function trimConsole() {
  const o = out();
  let size = o.textContent.length;
  while (size > MAX_CONSOLE && o.firstChild) {
    size -= o.firstChild.textContent.length;
    o.firstChild.remove();
  }
}

function consoleAppend(node) {
  const stick = atBottom();
  out().append(node);
  if (stick) out().scrollTop = out().scrollHeight;
}

function consoleText(text, cls = "") {
  if (!text) return;
  const o = out();
  const stick = atBottom();
  const last = o.lastChild;
  if (last && last.nodeType === 1 && last.tagName === "SPAN" && last.className === cls && !last.dataset.file) {
    last.firstChild.appendData(text);
  } else {
    o.append(el("span", { className: cls, textContent: text }));
  }
  if (o.childNodes.length > 2000 || text.length > 10000) trimConsole();
  if (stick) o.scrollTop = o.scrollHeight;
}

function consoleLine(text, cls) { flushStderr(); consoleText(text, cls); }

const LOCATION_PATTERNS = [
  /File "([^"]+)", line (\d+)/,
  /\(([^()]+?\.umsn) (\d+)줄(?: (\d+)칸)?\)/,
  /^([^\s:]+\.umsn) (\d+)줄 (\d+)칸/,
];

function stderrLine(line) {
  for (const re of LOCATION_PATTERNS) {
    const m = line.match(re);
    if (m && state.files.has(m[1])) {
      const span = el("span", { className: "err link", textContent: line, title: `${m[1]} ${m[2]}줄로 가기` });
      span.dataset.file = m[1];
      span.dataset.line = m[2];
      span.dataset.col = m[3] || "1";
      consoleAppend(span);
      return;
    }
  }
  consoleText(line, "err");
}

function consoleStderr(text) {
  text = stderrRest + text.split(WORK_PREFIX).join("");
  const parts = text.split("\n");
  stderrRest = parts.pop();
  for (const p of parts) stderrLine(p + "\n");
  if (/tkinter|_tkinter|turtle/.test(text) && /ModuleNotFoundError|No module named|엄모듈/.test(text)) {
    consoleText("※ 티킨터(tkinter)·거북(turtle) 창은 브라우저에서 열 수 없슨. 데스크톱 UMSN-IDE (pyumsn -e) 를 쓰세요.\n", "info");
  }
}

function flushStderr() {
  if (stderrRest) { const rest = stderrRest; stderrRest = ""; stderrLine(rest); }
}

function showImage(title, bytes, type) {
  const ext = title.split(".").pop().toLowerCase();
  const blob = new Blob([bytes], { type: type || IMAGE_TYPES[ext] || "image/png" });
  const url = URL.createObjectURL(blob);
  const img = el("img", { src: url, alt: title });
  const link = el("a", { href: url, download: title.includes(".") ? title : title + ".png", textContent: "내려받기" });
  consoleAppend(el("figure", {}, img, el("figcaption", {}, `${title} · `, link)));
  img.onload = () => { if (atBottom()) out().scrollTop = out().scrollHeight; };
}

function b64ToBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

// ---------------------------------------------------------------------------
// 실행
// ---------------------------------------------------------------------------
function updateRunButtons() {
  const f = activeFile();
  $("#btn-run").disabled = state.running || !state.runReady || !f;
  $("#btn-stop").disabled = !state.running;
  $("#console-state").textContent = state.running
    ? (state.waitingInput ? "입력 기다리는 중…" : "실행 중…")
    : state.runReady ? "" : "실행기 준비 중…";
  $("#console-in").classList.toggle("waiting", state.waitingInput);
}

function parseArgs(text) {
  const args = [];
  const re = /"((?:\\.|[^"\\])*)"|'([^']*)'|(\S+)/g;
  let m;
  while ((m = re.exec(text))) args.push(m[1] !== undefined ? m[1].replace(/\\(.)/g, "$1") : m[2] !== undefined ? m[2] : m[3]);
  return args;
}

let runStarted = 0;
let runToken = 0;

async function runActive() {
  const file = activeFile();
  if (!file || state.running) return;
  if (!state.runReady) { status("실행기를 준비하는 중이슨… 잠시 뒤 다시 누르세요."); return; }
  closeComplete();
  out().replaceChildren();
  stderrRest = "";
  const files = [];
  for (const f of state.files.values()) {
    if (f.kind === "umsn") files.push({ name: f.name, text: fileText(f.name) });
    else files.push({ name: f.name, bytes: f.bytes.slice().buffer });
  }
  consoleText(`▶ ${file.name}\n`, "info");
  state.running = true;
  state.waitingInput = false;
  runStarted = performance.now();
  const token = ++runToken;
  if (interruptBuffer) new Uint8Array(interruptBuffer)[0] = 0;
  const stdinLines = state.interactive ? [] : state.typeahead.splice(0);
  runner.post({ type: "run", files, main: file.name, args: parseArgs($("#run-args").value), stdinLines },
    files.filter((f) => f.bytes).map((f) => f.bytes));
  updateRunButtons();
  setTimeout(() => { if (state.running && token === runToken) out().focus({ preventScroll: true }); }, 0);
}

function onRunEvent(msg) {
  switch (msg.type) {
    case "stdout": flushStderr(); consoleText(msg.text.split(WORK_PREFIX).join("")); break;
    case "stderr": consoleStderr(msg.text); break;
    case "status": consoleLine(msg.text + "\n", "info"); break;
    case "echo": flushStderr(); consoleText(msg.text, "echo"); break;
    case "image": flushStderr(); showImage(msg.title, b64ToBytes(msg.b64), "image/png"); break;
    case "input":
      flushStderr();
      state.waitingInput = true;
      updateRunButtons();
      if (state.typeahead.length) answerInput(state.typeahead.shift());
      else $("#stdin").focus({ preventScroll: true });
      break;
    case "stdin-eof":
      consoleLine("\n(입력이 없슨: 이 환경에서는 실행 전에 아래 입력 칸에 줄을 적어 두세요)\n", "info");
      break;
    case "done": {
      flushStderr();
      state.running = false;
      state.waitingInput = false;
      if (msg.error) consoleLine(`엄슨 오류! ${msg.error}\n`, "err");
      for (const f of msg.files || []) {
        const bytes = new Uint8Array(f.bytes);
        const existing = state.files.get(f.name);
        if (existing && existing.kind === "umsn") continue;
        if (f.name.endsWith(".umsn") && !f.name.includes("/")) {
          addFile(f.name, { kind: "umsn", text: new TextDecoder().decode(bytes) });
          consoleLine(`엄슨 파일을 만들었슨: ${f.name}\n`, "info");
          saveStore();
          continue;
        }
        addFile(f.name, { kind: "data", bytes });
        if (isImage(f.name)) showImage(f.name, bytes);
        else consoleLine(`파일을 만들었슨: ${f.name} (왼쪽 파일 목록에서 내려받기)\n`, "info");
      }
      const secs = ((msg.ms ?? performance.now() - runStarted) / 1000).toFixed(2);
      consoleLine(`\n■ 끝 (종료 코드 ${msg.code}, ${secs}초)\n`, msg.code === 0 ? "info" : "err");
      updateRunButtons();
      break;
    }
    case "fatal":
      state.running = false;
      consoleLine(`실행기 오류: ${msg.error}\n`, "err");
      updateRunButtons();
      break;
    default: break;
  }
}

function answerInput(line) {
  consoleText(line + "\n", "echo");
  if (!stdinBuffer) return;
  const view = new Int32Array(stdinBuffer);
  const bytes = new TextEncoder().encode(line).slice(0, stdinBuffer.byteLength - 8);
  new Uint8Array(stdinBuffer, 8).set(bytes);
  Atomics.store(view, 1, bytes.length);
  Atomics.store(view, 0, 1);
  Atomics.notify(view, 0);
  state.waitingInput = false;
  updateRunButtons();
}

function sendEof() {
  if (!state.waitingInput || !stdinBuffer) return;
  const view = new Int32Array(stdinBuffer);
  consoleText("^D\n", "echo");
  Atomics.store(view, 0, 2);
  Atomics.notify(view, 0);
  state.waitingInput = false;
  updateRunButtons();
}

function submitStdin(e) {
  e.preventDefault();
  const input = $("#stdin");
  const line = input.value;
  input.value = "";
  if (state.running && state.waitingInput) answerInput(line);
  else {
    state.typeahead.push(line);
    consoleText(`(미리 입력) ${line}\n`, "echo");
  }
}

function stopRun() {
  if (!state.running) return;
  const token = runToken;
  const hard = () => {
    if (!state.running || token !== runToken) return;
    runner.terminate();
    state.running = false;
    state.waitingInput = false;
    flushStderr();
    consoleLine("\n엄슨 중단! (실행기를 새로 준비하슨)\n", "err");
    startRunner();
  };
  if (interruptBuffer) {
    new Uint8Array(interruptBuffer)[0] = 2; // SIGINT → KeyboardInterrupt
    if (state.waitingInput) sendEof();
    setTimeout(hard, 1500);
  } else {
    hard();
  }
}

// ---------------------------------------------------------------------------
// 검사, 파이썬 보기, 단어장, 음역
// ---------------------------------------------------------------------------
function showProblemCount(problems) {
  const node = $("#st-problems");
  node.textContent = problems.length ? `문제 ${problems.length}개` : "문제 없슨";
  node.classList.toggle("bad", problems.length > 0);
}

async function checkActive() {
  const file = activeFile();
  if (!file || !state.langReady) return;
  const text = fileText(file.name);
  const result = await lang.call("analyze", { src: text });
  file.editor.applyAnalysis(text, result);
  flushStderr();
  if (!result.problems.length) { consoleLine(`문제 없슨! ${file.name}\n`, "info"); return; }
  for (const [line, col, , msg, sugg] of result.problems) {
    stderrLine(`${file.name} ${line}줄 ${(col || 0) + 1}칸: ${msg}${sugg ? ` → '${sugg}'` : ""}\n`);
  }
}

function showPanel(which) {
  const panel = $("#panel");
  if (!which || (!panel.hidden && panel.dataset.current === which)) { panel.hidden = true; panel.dataset.current = ""; return; }
  panel.hidden = false;
  panel.dataset.current = which;
  for (const b of panel.querySelectorAll("[data-panel]")) b.classList.toggle("active", b.dataset.panel === which);
  for (const b of panel.querySelectorAll("[data-body]")) b.hidden = b.dataset.body !== which;
  if (which === "words") $("#words-search").focus();
  if (which === "python") schedulePythonView(true);
  if (which === "translit") $("#tr-en").focus();
}

let pyTimer = null;
function schedulePythonView(now = false) {
  if ($("#panel").hidden || $("#panel").dataset.current !== "python") return;
  clearTimeout(pyTimer);
  pyTimer = setTimeout(refreshPythonView, now ? 0 : 400);
}

async function refreshPythonView() {
  const file = activeFile();
  const view = $("#python-view");
  if (!file) { view.textContent = ""; return; }
  if (!state.langReady) { view.textContent = "파이썬 준비 중…"; return; }
  const res = await lang.call("to_py", { src: fileText(file.name), name: file.name });
  view.textContent = res.ok ? res.code : res.error;
  view.classList.toggle("t-error", !res.ok);
}

function renderWords() {
  const q = $("#words-search").value.trim().toLowerCase();
  const list = $("#words-list");
  list.replaceChildren();
  let lastCat = null;
  let count = 0;
  for (const [cat, um, py] of state.words) {
    if (q && !um.toLowerCase().includes(q) && !py.toLowerCase().includes(q) && !cat.toLowerCase().includes(q)) continue;
    if (++count > 600) break;
    if (cat !== lastCat) { list.append(el("div", { className: "cat", textContent: cat })); lastCat = cat; }
    const row = el("div", { className: "w", tabIndex: 0, title: `${um} = ${py}` },
      el("span", { className: "um", textContent: um }), el("span", { className: "py", textContent: py }));
    const put = () => { const ed = activeEditor(); if (ed) { ed.insert(um); } };
    row.onclick = put;
    row.onkeydown = (e) => { if (e.key === "Enter") put(); };
    list.append(row);
  }
  if (!state.words.length) list.textContent = "단어장을 불러오는 중…";
  else if (!count) list.textContent = "찾는 단어가 없슨.";
}

async function translitField(input, output, op, key) {
  const value = input.value.trim();
  if (!value) { output.replaceChildren(); return; }
  if (!state.langReady) { output.textContent = "준비 중…"; return; }
  const res = await lang.call(op, { [key]: value });
  if (input.value.trim() !== value) return;
  output.replaceChildren();
  if (res.ok) output.append(el("span", { textContent: res.result }), el("span", { className: "note", textContent: res.note }));
  else output.append(el("span", { className: "t-error", textContent: res.error }));
}

// ---------------------------------------------------------------------------
// 문제 풍선말·오른쪽 클릭 메뉴
// ---------------------------------------------------------------------------
function showProblemTooltip(problem, e) {
  const tip = $("#tooltip");
  if (!problem) { tip.hidden = true; return; }
  tip.replaceChildren(el("span", { textContent: problem.msg }));
  if (problem.suggestion) tip.append(el("span", { className: "sugg", textContent: `오른쪽 클릭 → '${problem.suggestion}' 로 바꾸기` }));
  tip.hidden = false;
  const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
  const y = e.clientY + 18 + tip.offsetHeight > window.innerHeight ? e.clientY - tip.offsetHeight - 10 : e.clientY + 18;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${y}px`;
}

function showMenu(menu, x, y) {
  menu.hidden = false;
  menu.style.left = `${Math.max(4, Math.min(x, window.innerWidth - menu.offsetWidth - 8))}px`;
  menu.style.top = `${Math.max(4, Math.min(y, window.innerHeight - menu.offsetHeight - 8))}px`;
  const first = menu.querySelector("button");
  if (first) first.focus();
}

function showProblemMenu(editor, problem, e) {
  $("#tooltip").hidden = true;
  const menu = $("#ctx-menu");
  const word = editor.getValue().slice(problem.start, problem.end);
  const one = el("button", { textContent: `'${word}' → '${problem.suggestion}' 로 바꾸기` });
  one.onclick = () => { menu.hidden = true; editor.replaceRange(problem.start, problem.end, problem.suggestion); };
  const all = el("button", { textContent: `이 파일의 '${word}' 모두 바꾸기` });
  all.onclick = () => {
    menu.hidden = true;
    const text = editor.getValue();
    const same = editor.problems.filter((p) => text.slice(p.start, p.end) === word).sort((a, b) => b.start - a.start);
    for (const p of same) editor.replaceRange(p.start, p.end, problem.suggestion);
  };
  menu.replaceChildren(one, all);
  showMenu(menu, e.clientX, e.clientY);
}

// ---------------------------------------------------------------------------
// 자동 완성
// ---------------------------------------------------------------------------
let completeItems = [];
let completeSel = 0;
let completeFor = null;
let completeAuto = false;
const completeOpen = () => !$("#complete").hidden;
function closeComplete() { $("#complete").hidden = true; completeFor = null; }

function updateComplete(editor, auto = false) {
  const { word, start, end } = editor.wordBeforeCaret();
  if (auto && !word) { closeComplete(); return; }
  const seen = new Set();
  const items = [];
  const push = (um, py) => {
    if (seen.has(um) || um === word || !um.startsWith(word)) return;
    seen.add(um);
    items.push([um, py]);
  };
  for (const [, um, py] of state.words) push(um, py);
  for (const m of editor.getValue().matchAll(/[\w가-힣$]{2,}/gu)) push(m[0], "");
  items.sort((a, b) => a[0].length - b[0].length || a[0].localeCompare(b[0], "ko"));
  completeItems = items.slice(0, 60);
  completeSel = 0;
  if (!completeItems.length) { closeComplete(); return; }
  completeFor = { editor, start, end };
  completeAuto = auto && (completeAuto || !completeOpen());
  const box = $("#complete");
  box.replaceChildren();
  completeItems.forEach(([um, py], i) => {
    const item = el("div", { className: "item" + (i === 0 ? " sel" : ""), role: "option" },
      el("span", { textContent: um }), el("span", { className: "py", textContent: py }));
    item.onmousedown = (e) => { e.preventDefault(); completeSel = i; acceptComplete(); };
    box.append(item);
  });
  const rect = editor.ta.getBoundingClientRect();
  const { x, y, lh } = editor.caretPixel();
  box.hidden = false;
  const left = Math.min(rect.left + x, window.innerWidth - box.offsetWidth - 8);
  let top = rect.top + y + lh + 2;
  if (top + box.offsetHeight > window.innerHeight) top = rect.top + y - box.offsetHeight - 2;
  box.style.left = `${Math.max(4, left)}px`;
  box.style.top = `${Math.max(4, top)}px`;
}

function moveComplete(delta) {
  const items = $("#complete").children;
  items[completeSel].classList.remove("sel");
  completeSel = (completeSel + delta + items.length) % items.length;
  items[completeSel].classList.add("sel");
  items[completeSel].scrollIntoView({ block: "nearest" });
}

function acceptComplete() {
  if (!completeFor) return;
  const { editor } = completeFor;
  const { start, end } = editor.wordBeforeCaret();
  const [um] = completeItems[completeSel];
  closeComplete();
  editor.replaceRange(start, end, um);
}

function onEditorKey(editor, e) {
  const mod = e.ctrlKey || e.metaKey;
  if (completeOpen()) {
    if (e.key === "ArrowDown") { moveComplete(1); return true; }
    if (e.key === "ArrowUp") { moveComplete(-1); return true; }
    // 저절로 뜬 목록은 Tab 으로만 고른다 (Enter 는 줄바꿈 그대로)
    if (e.key === "Tab" || (e.key === "Enter" && !completeAuto)) { acceptComplete(); return true; }
    if (e.key === "Enter") closeComplete();
    if (e.key === "Escape") { closeComplete(); return true; }
    if (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "Home" || e.key === "End") closeComplete();
  }
  if (mod && (e.key === " " || e.code === "Space")) { updateComplete(editor); return true; }
  return false;
}

// ---------------------------------------------------------------------------
// 찾기·바꾸기·줄로 이동
// ---------------------------------------------------------------------------
let findMatches = [];
let findIndex = -1;

function openFind(replace = false) {
  const bar = $("#findbar");
  bar.hidden = false;
  const ed = activeEditor();
  if (ed) {
    const sel = ed.getValue().slice(ed.ta.selectionStart, ed.ta.selectionEnd);
    if (sel && !sel.includes("\n")) $("#find-text").value = sel;
  }
  (replace ? $("#replace-text") : $("#find-text")).focus();
  $("#find-text").select();
  updateFind(true);
}

function closeFind() {
  $("#findbar").hidden = true;
  for (const f of state.files.values()) if (f.editor) f.editor.setMarks([]);
  const ed = activeEditor();
  if (ed) ed.focus();
}

function updateFind(jump) {
  const ed = activeEditor();
  const q = $("#find-text").value;
  findMatches = [];
  if (ed && q) {
    const text = ed.getValue();
    for (let i = text.indexOf(q); i >= 0 && findMatches.length < 5000; i = text.indexOf(q, i + q.length)) findMatches.push([i, i + q.length]);
  }
  if (!findMatches.length) findIndex = -1;
  else if (jump || findIndex < 0 || findIndex >= findMatches.length) {
    const caret = ed.ta.selectionStart;
    findIndex = Math.max(0, findMatches.findIndex(([a]) => a >= caret));
  }
  if (ed) ed.setMarks(findMatches, findIndex);
  $("#find-count").textContent = q ? (findMatches.length ? `${findIndex + 1} / ${findMatches.length}` : "없슨") : "";
  if (jump && findIndex >= 0) ed.select(findMatches[findIndex][0], findMatches[findIndex][1], false);
}

function findStep(delta) {
  if (!findMatches.length) return;
  findIndex = (findIndex + delta + findMatches.length) % findMatches.length;
  const ed = activeEditor();
  ed.setMarks(findMatches, findIndex);
  ed.select(findMatches[findIndex][0], findMatches[findIndex][1], false);
  $("#find-count").textContent = `${findIndex + 1} / ${findMatches.length}`;
}

function replaceOne() {
  const ed = activeEditor();
  if (!ed || findIndex < 0) return;
  const [a, b] = findMatches[findIndex];
  ed.replaceRange(a, b, $("#replace-text").value);
  updateFind(false);
  $("#replace-text").focus();
}

function replaceAll() {
  const ed = activeEditor();
  const q = $("#find-text").value;
  if (!ed || !q || !findMatches.length) return;
  const n = findMatches.length;
  const text = ed.getValue().split(q).join($("#replace-text").value);
  ed.replaceRange(0, ed.getValue().length, text);
  updateFind(false);
  status(`${n}곳을 바꿨슨.`);
}

function gotoLine() {
  const ed = activeEditor();
  if (!ed) return;
  const value = prompt("몇째 줄로 갈까요?", String(ed.lineCol().line));
  const line = parseInt(value, 10);
  if (line > 0) ed.goto(line);
}

// ---------------------------------------------------------------------------
// 공유 링크
// ---------------------------------------------------------------------------
async function pack(obj) {
  const bytes = new TextEncoder().encode(JSON.stringify(obj));
  let data = bytes;
  let tag = "j";
  if (typeof CompressionStream !== "undefined") {
    data = new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(new CompressionStream("deflate-raw"))).arrayBuffer());
    tag = "z";
  }
  let bin = "";
  for (const b of data) bin += String.fromCharCode(b);
  return tag + btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function unpack(text) {
  const tag = text[0];
  const b64 = text.slice(1).replace(/-/g, "+").replace(/_/g, "/");
  let bytes = b64ToBytes(b64 + "===".slice((b64.length + 3) % 4));
  if (tag === "z") bytes = new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"))).arrayBuffer());
  return JSON.parse(new TextDecoder().decode(bytes));
}

async function share() {
  const file = activeFile();
  if (!file) return;
  const url = `${location.origin}${location.pathname}#c=${await pack({ n: file.name, t: fileText(file.name) })}`;
  try {
    await navigator.clipboard.writeText(url);
    status("링크를 복사했슨! 받은 사람이 열면 이 코드가 새 탭으로 열리슨.");
  } catch (err) {
    prompt("이 링크를 복사하세요", url);
  }
}

async function openSharedFromHash() {
  const m = location.hash.match(/^#c=([\w-]+)/);
  if (!m) return false;
  try {
    const { n, t } = await unpack(m[1]);
    const base = String(n || "공유.umsn").replace(/\.umsn$/, "");
    let name = base + ".umsn";
    if (state.files.has(name) && fileText(name) !== t) name = uniqueName(base + "_공유");
    if (!state.files.has(name)) addFile(name, { kind: "umsn", text: t });
    openTab(name);
    status(`공유된 코드를 '${name}' 으로 열었슨.`);
  } catch (err) {
    status("공유 링크를 읽지 못했슨.", true);
  }
  history.replaceState(null, "", location.pathname + location.search);
  return true;
}

// ---------------------------------------------------------------------------
// 테마·글자 크기·배치
// ---------------------------------------------------------------------------
function applyTheme(theme) {
  state.theme = theme;
  document.documentElement.dataset.theme = theme;
  saveStore();
}

function applyFontSize(size) {
  state.fontSize = Math.min(28, Math.max(10, size));
  document.documentElement.style.setProperty("--font-size", `${state.fontSize}px`);
  for (const f of state.files.values()) if (f.editor) f.editor._onCursor();
  saveStore();
}

function setupSplitter() {
  const splitter = $("#splitter");
  const pane = $("#console-pane");
  const center = $(".center");
  let startY = 0;
  let startH = 0;
  const move = (e) => {
    const h = Math.min(center.clientHeight - 120, Math.max(90, startH - (e.clientY - startY)));
    pane.style.height = `${h}px`;
  };
  splitter.addEventListener("pointerdown", (e) => {
    startY = e.clientY;
    startH = pane.offsetHeight;
    splitter.classList.add("drag");
    splitter.setPointerCapture(e.pointerId);
    splitter.addEventListener("pointermove", move);
  });
  splitter.addEventListener("pointerup", (e) => {
    splitter.classList.remove("drag");
    splitter.releasePointerCapture(e.pointerId);
    splitter.removeEventListener("pointermove", move);
  });
  splitter.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    e.preventDefault();
    pane.style.height = `${Math.max(90, pane.offsetHeight + (e.key === "ArrowUp" ? 30 : -30))}px`;
  });
}

// ---------------------------------------------------------------------------
// 연결
// ---------------------------------------------------------------------------
function bindUi() {
  $("#btn-new").onclick = newFile;
  $("#btn-open").onclick = () => $("#file-input").click();
  $("#file-input").onchange = (e) => { openFiles([...e.target.files]); e.target.value = ""; };
  $("#btn-save").onclick = () => state.active && downloadFile(state.active);
  $("#btn-run").onclick = runActive;
  $("#btn-stop").onclick = stopRun;
  $("#btn-python").onclick = () => showPanel("python");
  $("#btn-words").onclick = () => showPanel("words");
  $("#btn-translit").onclick = () => showPanel("translit");
  $("#btn-check").onclick = checkActive;
  $("#btn-share").onclick = share;
  $("#btn-theme").onclick = () => applyTheme(state.theme === "light" ? "dark" : "light");
  $("#btn-font-up").onclick = () => applyFontSize(state.fontSize + 1);
  $("#btn-font-down").onclick = () => applyFontSize(state.fontSize - 1);
  $("#btn-help").onclick = () => $("#dlg-help").showModal();
  $("#btn-clear").onclick = () => { out().replaceChildren(); stderrRest = ""; };
  $("#btn-files").onclick = () => $("#sidebar").classList.toggle("open");
  $("#btn-eof").onclick = sendEof;
  $("#console-in").onsubmit = submitStdin;
  $("#stdin").onkeydown = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "d") { e.preventDefault(); sendEof(); } };
  $("#run-args").oninput = saveStore;
  $("#panel-close").onclick = () => showPanel(null);
  for (const b of document.querySelectorAll("[data-panel]")) b.onclick = () => showPanel(b.dataset.panel);
  $("#words-search").oninput = renderWords;
  $("#tr-en").oninput = () => translitField($("#tr-en"), $("#tr-en-out"), "translit", "name");
  $("#tr-um").oninput = () => translitField($("#tr-um"), $("#tr-um-out"), "untranslit", "word");
  $("#py-refresh").onclick = refreshPythonView;
  $("#py-copy").onclick = () => navigator.clipboard.writeText($("#python-view").textContent).then(() => status("파이썬 코드를 복사했슨."));
  $("#py-download").onclick = async () => {
    const file = activeFile();
    if (!file) return;
    const res = await lang.call("to_py", { src: fileText(file.name), name: file.name });
    if (!res.ok) { consoleLine(res.error + "\n", "err"); return; }
    download(file.name.replace(/\.umsn$/, ".py"), new Blob([res.code], { type: "text/x-python;charset=utf-8" }));
  };

  $("#find-text").oninput = () => updateFind(true);
  $("#find-text").onkeydown = (e) => {
    if (e.key === "Enter") { e.preventDefault(); findStep(e.shiftKey ? -1 : 1); }
    if (e.key === "Escape") closeFind();
  };
  $("#replace-text").onkeydown = (e) => {
    if (e.key === "Enter") { e.preventDefault(); replaceOne(); }
    if (e.key === "Escape") closeFind();
  };
  $("#find-next").onclick = () => findStep(1);
  $("#find-prev").onclick = () => findStep(-1);
  $("#replace-one").onclick = replaceOne;
  $("#replace-all").onclick = replaceAll;
  $("#find-close").onclick = closeFind;

  const exMenu = $("#menu-examples");
  for (const [name, desc] of EXAMPLES) {
    const b = el("button", { role: "menuitem" }, name, el("span", { className: "sub", textContent: desc }));
    b.onclick = () => { exMenu.hidden = true; $("#btn-examples").setAttribute("aria-expanded", "false"); openExample(name); };
    exMenu.append(b);
  }
  $("#btn-examples").onclick = (e) => {
    e.stopPropagation();
    exMenu.hidden = !exMenu.hidden;
    $("#btn-examples").setAttribute("aria-expanded", String(!exMenu.hidden));
    if (!exMenu.hidden) exMenu.querySelector("button").focus();
  };

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#menu-examples")) { exMenu.hidden = true; $("#btn-examples").setAttribute("aria-expanded", "false"); }
    if (!e.target.closest("#ctx-menu")) $("#ctx-menu").hidden = true;
    if (!e.target.closest("#complete")) closeComplete();
    const link = e.target.closest(".console-out .link");
    if (link) { openTab(link.dataset.file); activeEditor().goto(+link.dataset.line, +link.dataset.col); }
  });
  for (const menu of [exMenu, $("#ctx-menu")]) {
    menu.addEventListener("keydown", (e) => {
      const items = [...menu.querySelectorAll("button")];
      const i = items.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
      if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
      if (e.key === "Escape") { menu.hidden = true; const ed = activeEditor(); if (ed) ed.focus(); }
    });
  }

  document.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;
    const key = e.key;
    const handled = () => { e.preventDefault(); e.stopPropagation(); };
    if (key === "F5" && e.shiftKey) { handled(); stopRun(); }
    else if (key === "F5" || (mod && key === "Enter")) { handled(); runActive(); }
    else if (key === "F6") { handled(); showPanel("python"); }
    else if (key === "F7") { handled(); checkActive(); }
    else if (key === "F1") { handled(); showPanel("words"); }
    else if (key === "F9") { handled(); applyTheme(state.theme === "light" ? "dark" : "light"); }
    else if (mod && key.toLowerCase() === "s") { handled(); if (state.active) downloadFile(state.active); }
    else if (mod && key.toLowerCase() === "o") { handled(); $("#file-input").click(); }
    else if (mod && key.toLowerCase() === "f" && !e.shiftKey) { handled(); openFind(false); }
    else if (mod && key.toLowerCase() === "h") { handled(); openFind(true); }
    else if (mod && key.toLowerCase() === "g") { handled(); gotoLine(); }
    else if (key === "Escape" && !$("#findbar").hidden && e.target.closest && e.target.closest(".editor")) closeFind();
  });

  window.addEventListener("resize", closeComplete);
  document.addEventListener("scroll", () => { $("#tooltip").hidden = true; closeComplete(); }, true);
  const editors = $("#editors");
  editors.addEventListener("dragover", (e) => { e.preventDefault(); });
  editors.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer.files.length) openFiles([...e.dataTransfer.files]);
  });
  setupSplitter();
}

async function main() {
  bindUi();
  const saved = loadStore();
  const prefersLight = window.matchMedia && matchMedia("(prefers-color-scheme: light)").matches;
  applyTheme((saved && saved.theme) || (prefersLight ? "light" : "dark"));
  applyFontSize((saved && saved.fontSize) || 15);
  if (saved && saved.args) $("#run-args").value = saved.args;
  if (window.innerWidth <= 760) $("#sidebar").classList.remove("open");

  if (saved && saved.files && Object.keys(saved.files).length) {
    for (const [name, text] of Object.entries(saved.files)) addFile(name, { kind: "umsn", text });
    for (const name of saved.tabs || []) if (state.files.has(name)) openTab(name);
    if (saved.active && state.files.has(saved.active)) activate(saved.active);
  } else {
    addFile("환영.umsn", { kind: "umsn", text: WELCOME });
    openTab("환영.umsn");
  }
  if (!state.tabs.length && state.files.size) openTab([...state.files.keys()][0]);

  try {
    state.root = await detectRoot();
  } catch (err) {
    status(err.message, true);
    $("#st-engine").textContent = "pyumsn 없음";
    return;
  }
  await openSharedFromHash();
  window.addEventListener("hashchange", openSharedFromHash);
  startLang();
  startRunner();
  if (document.fonts) document.fonts.ready.then(() => { for (const f of state.files.values()) if (f.editor) f.editor._onCursor(); });
}

main();
