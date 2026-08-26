#!/usr/bin/env node
// Materialize template/ -> workspace root with container patches (idempotent).
// Behavior documented in the playwright-e2e-workflow skill:
//   - CONFIG_DIR + absolute storageState (__dirname), CJS-transpile safe
//   - headless: true + --no-sandbox (container has no DISPLAY / sandbox limits)
//   - json reporter guaranteed (阶段5 报告依赖)
//   - global-setup: AUTH_FILE injection + no-DISPLAY login guidance
//
// Robustness notes (v6.2):
//   - All patch anchors are quote/whitespace tolerant (single/double quotes,
//     optional spaces) and existence-aware — safe to run against arbitrary
//     but syntactically valid Playwright configs shipped by the backend.
//   - Never duplicate an injected block (idempotent even if the template
//     already contains the container patches).
//   - Ends with a patch-verification summary so silent skips are visible.
import { cpSync, existsSync, mkdirSync, readFileSync, symlinkSync, writeFileSync } from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const TPL = path.join(ROOT, 'template');

// Engineer files may use CR-only or CRLF line endings — normalize to LF.
const read = (p) => readFileSync(p, 'utf8').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
const write = (p, c) => writeFileSync(p, c, 'utf8');
const patched = [];
const check = {};

// ---------- tiny structural helpers ----------

// Insert a block right after the first import line (quotes/format agnostic).
// TS hoists imports, so the block may safely reference 'path' anywhere top-level.
function insertAfterFirstImport(src, block) {
  const m = src.match(/^import[^\n]*\n/m);
  return m ? src.replace(m[0], m[0] + block) : block + '\n' + src;
}

// Append an entry into the FIRST "name: [ ... ]" array found (quote tolerant),
// e.g. append a flag into args. No-op if already present.
function appendToFirstArray(src, anchor, entry) {
  const re = new RegExp('(' + anchor + '\\s*:\\s*\\[)([^\\]]*)(\\])');
  const m = src.match(re);
  if (!m) return src;
  const tail = m[2].trim();
  return src.replace(m[0], `${m[1]}${tail ? tail + ', ' : ''}${entry}${m[3]}`);
}

// ---------- playwright.config.ts ----------
let cfg = read(path.join(TPL, 'playwright.config.ts'));

// 1) CONFIG_DIR banner (path import + dir constant). Skip if already present.
if (!cfg.includes('CONFIG_DIR')) {
  const block =
    "import * as path from 'path';\n\n" +
    '// container patch: absolute paths must not depend on process cwd\n' +
    'const CONFIG_DIR = __dirname;\n';
  cfg = insertAfterFirstImport(cfg, block);
}

// 2) testDir/outputDir: only inject the pair when missing entirely.
if (!/testDir\s*:/.test(cfg)) {
  cfg = cfg.replace(
    /export\s+default\s+defineConfig\s*\(\s*{/,
    "export default defineConfig({\n  testDir: '.',\n  outputDir: 'test-results',"
  );
} else if (!/outputDir\s*:/.test(cfg)) {
  // testDir present but outputDir missing — add it next to testDir.
  cfg = cfg.replace(/(testDir\s*:\s*[^,\n]+),?/, "$1,\n  outputDir: 'test-results'");
}

// 3) storageState: convert the relative literal 'auth.json' to an absolute
//    path.join(CONFIG_DIR, ...). Leave already-absolute variants untouched.
cfg = cfg.replace(
  /storageState\s*:\s*['"]auth\.json['"]/,
  "storageState: path.join(CONFIG_DIR, 'auth.json')"
);

// 4) headless: force true (container has no display).
cfg = cfg.replace(/headless(\s*:\s*)false\b/g, 'headless$1true');

// 5) --no-sandbox in launchOptions.args (inject launchOptions/args as needed).
//    Target the TOP-LEVEL use block (indent ≤ 2 spaces) so every project
//    inherits it; fall back to the first use block if none matches.
if (!cfg.includes('launchOptions')) {
  const topUse = cfg.match(/^ {0,2}use\s*:\s*{/m);
  if (topUse) {
    cfg = cfg.replace(topUse[0], topUse[0] + "\n    launchOptions: { args: ['--no-sandbox'] },");
  } else if (/use\s*:\s*{/.test(cfg)) {
    cfg = cfg.replace(/use\s*:\s*{/, "use: {\n    launchOptions: { args: ['--no-sandbox'] },");
  } else {
    cfg = cfg.replace(/\n\}\);?\s*$/, "\n  use: { launchOptions: { args: ['--no-sandbox'] } },\n});");
  }
} else if (!/args\s*:/.test(cfg)) {
  cfg = cfg.replace(/launchOptions\s*:\s*{/, "launchOptions: { args: ['--no-sandbox'],");
} else if (!cfg.includes('--no-sandbox')) {
  cfg = appendToFirstArray(cfg, 'args', "'--no-sandbox'");
}

// 6) config may pin msedge/other browsers not installed here — drop any
//    non-chromium browserName and any channel, use bundled chromium.
//    Inline forms (`use: { browserName: "msedge", channel: "msedge" }`)
//    included: trailing comma is consumed so no dangling commas remain.
cfg = cfg.replace(/\s*browserName\s*:\s*['"](?!chromium)[^'"]*['"]\s*,?/g, '');
cfg = cfg.replace(/\s*channel\s*:\s*['"][^'"]*['"]\s*,?/g, '');

// 7) json reporter guarantee (阶段5 报告依赖). Skip if any outputFile exists.
const REPORT_JSON = "path.join(CONFIG_DIR, 'report/test-results.json')";
if (!cfg.includes('outputFile')) {
  const jsonEntry = `['json', { outputFile: ${REPORT_JSON} }]`;
  if (!/reporter\s*:/.test(cfg)) {
    // No reporter at all — inject a full block (prefer after globalSetup).
    if (/globalSetup\s*:/.test(cfg)) {
      cfg = cfg.replace(
        /(globalSetup\s*:\s*[^,\n]+),?\n/,
        `$1,\n  reporter: [\n    ['list'],\n    ${jsonEntry},\n  ],\n`
      );
    } else {
      cfg = cfg.replace(
        /export\s+default\s+defineConfig\s*\(\s*{/,
        `export default defineConfig({\n  reporter: [\n    ['list'],\n    ${jsonEntry},\n  ],`
      );
    }
  } else if (/reporter\s*:\s*\[/.test(cfg)) {
    // Array form — splice the json entry in as the first reporter.
    cfg = cfg.replace(/(reporter\s*:\s*\[)/, `$1\n    ${jsonEntry},`);
  } else {
    // Scalar form, e.g. reporter: 'html' — wrap into an array with json.
    cfg = cfg.replace(
      /reporter\s*:\s*['"]([^'"]+)['"]/,
      `reporter: [\n    ['$1'],\n    ${jsonEntry},\n  ]`
    );
  }
}

// 8) clean-up pass: strip any browserName/channel the reporter/other patches
//    may have left inline (also covers per-project configs).
cfg = cfg.replace(/\s*browserName\s*:\s*['"](?!chromium)[^'"]*['"]\s*,?/g, '');
cfg = cfg.replace(/\s*channel\s*:\s*['"][^'"]*['"]\s*,?/g, '');

write(path.join(ROOT, 'playwright.config.ts'), cfg);
patched.push('playwright.config.ts');

// Patch-verification runs against the files as written to disk, not the
// in-memory strings — catches mistakes like a broken write().
const diskCfg = read(path.join(ROOT, 'playwright.config.ts'));
check.cfg = {
  configDir: diskCfg.includes('CONFIG_DIR'),
  storageStateAbs: diskCfg.includes("path.join(CONFIG_DIR, 'auth.json')"),
  headlessTrue: /headless\s*:\s*true\b/.test(diskCfg),
  noSandbox: diskCfg.includes('--no-sandbox'),
  jsonReporter: /outputFile\s*:/.test(diskCfg),
  noMsEdge: !/channel\s*:/.test(diskCfg) && !/browserName\s*:\s*['"](?!chromium)/.test(diskCfg),
};

// ---------- global-setup.ts ----------
let gs = read(path.join(TPL, 'global-setup.ts'));

// 1) AUTH_FILE banner: path import (only if missing) + AUTH_FILE const.
if (!gs.includes('const AUTH_FILE')) {
  const pathImport = /from\s+['"]path['"]/.test(gs)
    ? ''
    : "import * as path from 'path';\n";
  const block =
    pathImport +
    '\n' +
    '// container patch: absolute auth path (env-overridable), never cwd-relative\n' +
    "const AUTH_FILE = process.env.AUTH_FILE || path.join(__dirname, 'auth.json');\n";
  gs = insertAfterFirstImport(gs, block);
}

// 2) auth.json literals -> AUTH_FILE (colon form only; the login-time
//    storageState({ path: 'auth.json' }) save stays relative on purpose).
gs = gs.replace(/(existsSync|unlinkSync)\s*\(\s*['"]auth\.json['"]\s*\)/g, '$1(AUTH_FILE)');
gs = gs.replace(/(storageState\s*:\s*)['"]auth\.json['"]/g, '$1AUTH_FILE');

// 3) no msedge/other browsers here — drop channel from launch calls.
gs = gs.replace(/\s*channel\s*:\s*['"][^'"]*['"]\s*,?/g, '');

// 4) no-DISPLAY guard at the LOGIN-BRANCH entry: right before the
//    `try { unlinkSync(AUTH_FILE); }` line (auth came back invalid).
//    - auth VALID  -> serverAuthValid returns true -> early return -> guard
//      never reached, so headless runs work even without DISPLAY.
//    - auth INVALID -> about to start the inline login; without DISPLAY we
//      can't run the headed path, so point to login.mjs instead.
//    NOT anchored on chromium.launch: the first braced launch in the template
//    is the auth-probe inside serverAuthValid (also launches with options),
//    so a launch anchor wrongly blocks every headless run (2026-08-18 bug).*/
if (!gs.includes('no DISPLAY')) {
  const unlinkRe = /try\s*\{\s*unlinkSync\s*\(\s*AUTH_FILE\s*\)\s*;\s*\}\s*catch\s*\{\s*\}/;
  const lines = gs.split('\n');
  const idx = lines.findIndex((l) => unlinkRe.test(l));
  if (idx >= 0) {
    const pad = lines[idx].match(/^\s*/)[0];
    lines.splice(
      idx,
      0,
      `${pad}// container patch: headed login needs X; otherwise point to login.mjs`,
      `${pad}if (!process.env.DISPLAY) {`,
      `${pad}  console.error('[global-setup] auth invalid and no DISPLAY — run: DISPLAY=:99 node login.mjs');`,
      `${pad}  process.exit(1);`,
      `${pad}}`
    );
    gs = lines.join('\n');
  }
}
// Append --no-sandbox to the FIRST braced chromium.launch's options:
//   - if that call already has an args array → append into it
//   - otherwise inject `args: ['--no-sandbox']` right after its `{`
// Scoped to the launch call (bracket depth), so a `use.args` elsewhere in
// the file is never touched.
function ensureLaunchNoSandbox(src) {
  if (!/chromium\.launch\(\s*\{/.test(src)) return src;
  const lines = src.split('\n');
  const idx = lines.findIndex((l) => /chromium\.launch\(\s*\{/.test(l));
  let depth = 0, started = false, end = idx;
  for (let i = idx; i < lines.length; i++) {
    for (const ch of lines[i]) {
      if (ch === '{') { depth++; started = true; }
      else if (ch === '}') depth--;
    }
    end = i;
    if (started && depth === 0) break;
  }
  const slice = lines.slice(idx, end + 1).join('\n');
  const replaced = /args\s*:/.test(slice)
    ? appendToFirstArray(slice, 'args', "'--no-sandbox'")
    : slice.replace(/(chromium\.launch\(\s*\{)/, "$1 args: ['--no-sandbox'], ");
  return lines.slice(0, idx).join('\n') + '\n' + replaced + '\n' + lines.slice(end + 1).join('\n');
}
if (!gs.includes('--no-sandbox')) {
  gs = ensureLaunchNoSandbox(gs);
}

write(path.join(ROOT, 'global-setup.ts'), gs);
patched.push('global-setup.ts');

const diskGs = read(path.join(ROOT, 'global-setup.ts'));
check.gs = {
  authFile: diskGs.includes('const AUTH_FILE'),
  guard: diskGs.includes('no DISPLAY'),
  noChannel: !/channel\s*:/.test(diskGs),
  noSandbox: diskGs.includes('--no-sandbox'),
};

// ---------- assets ----------
if (existsSync(path.join(TPL, 'assets'))) {
  mkdirSync(path.join(ROOT, 'assets'), { recursive: true });
  cpSync(path.join(TPL, 'assets'), path.join(ROOT, 'assets'), { recursive: true });
  patched.push('assets/');
}

// ---------- node_modules links ----------
// No local install: link the global playwright packages so the config loader
// (resolves from config dir upward) and test files can import them. Keeps the
// exact version the CLI uses — no browser-revision drift.
function linkNodeModules() {
  const nm = path.join(ROOT, 'node_modules');
  const links = [
    ['@playwright/test', '/usr/local/lib/node_modules/@playwright/test'],
    ['playwright', '/usr/local/lib/node_modules/playwright'],
    ['playwright-core', '/usr/local/lib/node_modules/playwright/node_modules/playwright-core'],
  ];
  for (const [name, target] of links) {
    if (!existsSync(target)) continue;
    const p = path.join(nm, name);
    if (!existsSync(p)) {
      mkdirSync(path.dirname(p), { recursive: true });
      symlinkSync(target, p, 'dir');
      console.log('linked node_modules/' + name);
    }
  }
}
linkNodeModules();

// ---------- patch-verification summary ----------
console.log('materialized:', patched.join(', '));
for (const [file, checks] of Object.entries(check)) {
  for (const [name, ok] of Object.entries(checks)) {
    console.log(`  [${ok ? 'ok' : 'WARN'}] ${file}::${name}`);
    if (!ok) console.log(`        (silent skip — template may legitimately differ)`);
  }
}