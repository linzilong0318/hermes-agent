#!/usr/bin/env node
// Clear the session workspace entirely: EVERY file/subdir inside the session
// dir is removed, leaving only the (empty) session dir itself.
//
// Rationale (v6.2, 2026-08-18): after a task finishes nothing in the session
// dir is reusable — auth.json gets recreated by login.mjs, template/ is
// re-fetched by fetch_config.py, scripts/login.mjs/seed.spec.ts are re-synced
// by preflight.py, node_modules is re-linked by prepare.mjs. So wipe it all.
//
// Safety: only runs against a directory that looks like a session workspace
// (path ends with <root>/e2e/<sessionId>). Anything else aborts — this script
// must NEVER be able to delete an arbitrary directory.
import { existsSync, rmSync, readdirSync } from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

// Accept legacy --all (was "also remove auth.json"); new behavior always wipes
// everything, so the flag is a no-op kept for backwards compatibility.
process.argv.includes('--all');

if (!/\/e2e\/[^/]+$/.test(ROOT) || !existsSync(ROOT)) {
  console.error(
    `[cleanup] 拒绝执行:当前目录不像会话工作区(${ROOT})。` +
      'cleanup.mjs 只应作为 session 目录(如 /opt/data/e2e/<sessionId>)下的运行副本执行。'
  );
  process.exit(2);
}

const entries = readdirSync(ROOT);
for (const f of entries) {
  const p = path.join(ROOT, f);
  rmSync(p, { recursive: true, force: true });
  console.log('removed', f);
}

console.log('cleanup done — session dir now empty');