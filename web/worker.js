// UMSN-IDE Web — Pyodide 워커.
//
// 한 파일로 두 가지 역할을 한다.
//   role "lang": 구문 강조·검사·변환·단어장 (편집하는 동안 계속 불림)
//   role "run" : 엄슨 프로그램 실행 (stdout/stderr 흘려보내기, input(), 멈추기)
// 실행 중에도 편집기가 멈추지 않도록 둘은 서로 다른 워커에서 돈다.

const PYODIDE_VERSION = "314.0.7";
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const FONT_URL = "https://cdn.jsdelivr.net/npm/d2coding@1.3.2/fonts/d2coding-full.ttf";

// pyumsn 패키지 중 브라우저에서 쓰는 모듈 (cli, runner, repl 은 하위 프로세스를 쓰므로 뺌)
const PY_MODULES = ["__init__", "errors", "importer", "launcher", "lexer", "sourceio",
  "translator", "vocab"];
const LIB = "/home/pyodide/lib";
const WORK = "/home/pyodide/work";
const FONT_PATH = "/home/pyodide/fonts/D2Coding.ttf";

let pyodide = null;
let web = null;          // umsn_web 모듈 (PyProxy)
let role = null;
let stdinView = null;    // 대화형 입력용 SharedArrayBuffer (Int32 [상태, 길이] + 바이트)
let stdinQueue = [];     // SharedArrayBuffer 가 없을 때 미리 적어 둔 입력
let fontReady = false;
let mplReady = false;

const post = (msg, transfer) => self.postMessage(msg, transfer || []);

async function fetchText(url) {
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${url} 을(를) 불러오지 못했슨 (${res.status})`);
  return res.text();
}

async function init(msg) {
  role = msg.role;
  const { loadPyodide } = await import(PYODIDE_URL + "pyodide.mjs");
  pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
  const FS = pyodide.FS;
  FS.mkdirTree(LIB + "/pyumsn");
  FS.mkdirTree(WORK);
  const sources = await Promise.all([
    ...PY_MODULES.map((m) => fetchText(`${msg.root}pyumsn/${m}.py`)),
    fetchText(msg.webRoot + "umsn_web.py"),
  ]);
  PY_MODULES.forEach((m, i) => FS.writeFile(`${LIB}/pyumsn/${m}.py`, sources[i]));
  FS.writeFile(`${LIB}/umsn_web.py`, sources[sources.length - 1]);

  if (role === "run") setupStdio(msg);
  pyodide.registerJsModule("umsn_host", {
    postImage: (title, b64) => post({ type: "image", title, b64 }),
  });
  pyodide.runPython(`import sys\nsys.path.insert(0, ${JSON.stringify(LIB)})`);
  web = pyodide.pyimport("umsn_web");
  const host = pyodide.pyimport("umsn_host");
  const info = JSON.parse(web.init(WORK, host));
  post({ type: "ready", ...info, pyodide: PYODIDE_VERSION, interactive: !!stdinView });
}

function setupStdio(msg) {
  const decoders = { stdout: new TextDecoder(), stderr: new TextDecoder() };
  for (const stream of ["stdout", "stderr"]) {
    const setter = stream === "stdout" ? "setStdout" : "setStderr";
    pyodide[setter]({
      isatty: true, // 줄 단위로 바로바로 보이게
      write: (buf) => {
        const text = decoders[stream].decode(buf, { stream: true });
        if (text) post({ type: stream, text });
        return buf.length;
      },
    });
  }
  if (msg.stdinBuffer) stdinView = new Int32Array(msg.stdinBuffer);
  if (msg.interruptBuffer) pyodide.setInterruptBuffer(new Uint8Array(msg.interruptBuffer));
  pyodide.setStdin({ stdin: readLine, isatty: false });
}

// input() 이 한 줄을 달라고 할 때. 대화형이면 메인 스레드가 답할 때까지 기다린다.
function readLine() {
  if (!stdinView) {
    if (stdinQueue.length) {
      const line = stdinQueue.shift();
      post({ type: "echo", text: line + "\n" });
      return line + "\n";
    }
    post({ type: "stdin-eof" });
    return null;
  }
  Atomics.store(stdinView, 0, 0);
  post({ type: "input" });
  Atomics.wait(stdinView, 0, 0);
  const state = Atomics.load(stdinView, 0);
  if (state === 2) return null; // EOF (Ctrl+D)
  const len = Atomics.load(stdinView, 1);
  const bytes = new Uint8Array(stdinView.buffer, 8, len).slice();
  return new TextDecoder().decode(bytes) + "\n";
}

async function ensureFont() {
  if (fontReady) return;
  try {
    const res = await fetch(FONT_URL);
    if (!res.ok) throw new Error(res.status);
    pyodide.FS.mkdirTree(FONT_PATH.slice(0, FONT_PATH.lastIndexOf("/")));
    pyodide.FS.writeFile(FONT_PATH, new Uint8Array(await res.arrayBuffer()));
    fontReady = true;
  } catch (err) {
    post({ type: "status", text: `D2Coding 글꼴을 받지 못해 그림의 한글이 깨질 수 있슨 (${err})` });
  }
}

function writeWorkspace(files) {
  const FS = pyodide.FS;
  for (const f of files) {
    const path = `${WORK}/${f.name}`;
    const dir = path.slice(0, path.lastIndexOf("/"));
    FS.mkdirTree(dir);
    FS.writeFile(path, f.text !== undefined ? f.text : new Uint8Array(f.bytes));
  }
}

async function run(msg) {
  const started = performance.now();
  stdinQueue = (msg.stdinLines || []).slice();
  web.clear_workspace();
  writeWorkspace(msg.files);
  try {
    const py = web.python_for_imports();
    await pyodide.loadPackagesFromImports(py, {
      messageCallback: (text) => { if (!/already loaded/.test(text)) post({ type: "status", text }); },
      errorCallback: (text) => post({ type: "status", text }),
    });
    if (pyodide.loadedPackages.matplotlib && !mplReady) {
      post({ type: "status", text: "matplotlib 준비 중 (한글 글꼴 D2Coding)…" });
      await ensureFont();
      web.setup_matplotlib(fontReady ? FONT_PATH : null);
      mplReady = true;
    }
  } catch (err) {
    post({ type: "status", text: `패키지를 불러오지 못했슨: ${err.message || err}` });
  }
  const before = web.snapshot();
  let code;
  try {
    code = web.run_program(msg.main, JSON.stringify(msg.args || []));
  } catch (err) {
    post({ type: "stderr", text: `엄슨 오류! ${err.message || err}\n` });
    code = 1;
  }
  const changed = JSON.parse(web.changed_files(before));
  const outFiles = [];
  const transfer = [];
  for (const name of changed) {
    if (name.endsWith(".umsn") && msg.files.some((f) => f.name === name && f.text !== undefined)) continue;
    const bytes = pyodide.FS.readFile(`${WORK}/${name}`);
    outFiles.push({ name, bytes: bytes.buffer });
    transfer.push(bytes.buffer);
  }
  post({ type: "done", code, ms: Math.round(performance.now() - started), files: outFiles }, transfer);
}

function call(op, args) {
  switch (op) {
    case "analyze": return JSON.parse(web.analyze(args.src));
    case "to_py": return JSON.parse(web.to_py(args.src, args.name || "<엄슨>"));
    case "to_umsn": return JSON.parse(web.to_umsn(args.src, !!args.keepSymbols, args.name || "<파이썬>"));
    case "words": return JSON.parse(web.words());
    case "translit": return JSON.parse(web.translit(args.name));
    case "untranslit": return JSON.parse(web.untranslit(args.word));
    default: throw new Error(`모르는 요청: ${op}`);
  }
}

self.onmessage = async (event) => {
  const msg = event.data;
  try {
    if (msg.type === "init") await init(msg);
    else if (msg.type === "run") await run(msg);
    else if (msg.type === "call") post({ type: "reply", id: msg.id, ok: true, result: call(msg.op, msg.args || {}) });
  } catch (err) {
    const text = String(err && err.message ? err.message : err);
    if (msg.type === "call") post({ type: "reply", id: msg.id, ok: false, error: text });
    else if (msg.type === "run") post({ type: "done", code: 1, files: [], error: text });
    else post({ type: "fatal", error: text });
  }
};
