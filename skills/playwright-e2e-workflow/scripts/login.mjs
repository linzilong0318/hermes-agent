#!/usr/bin/env node
// Standalone login for the e2e workspace: saves storageState to ./auth.json
// (relative to this script's dir). Does NOT touch /opt/data/auth.json, which is
// Hermes' own credential store — overwriting it destroys Hermes credentials.
//
// v6.3 (2026-08-18): 账号与项目空间不再在此硬编码/自动选择 —— 一律从后端
//       下发的 global-setup.ts(物化到工作区根)读取,作为唯一事实来源。
//       下拉只选 global-setup.ts 指定的确切空间;目标空间不在下拉列表里时
//       直接报错退出,绝不回退到第一个"项目/"选项(防止误操作其他空间)。
//
// Usage:
//   cd /opt/data/e2e && DISPLAY=:99 PLAYWRIGHT_BROWSERS_PATH=/opt/hermes/.playwright node login.mjs
import { createRequire } from 'module';
const require = createRequire(import.meta.url);

// Resolve 'playwright' from local node_modules first, fall back to the global
// install (this container keeps playwright global, no local node_modules).
let playwright;
try {
  playwright = require('playwright');
} catch {
  playwright = require('/usr/local/lib/node_modules/playwright');
}
const { chromium } = playwright;

import { existsSync, unlinkSync, readFileSync } from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const AUTH_FILE = path.join(__dirname, 'auth.json');
const GLOBAL_SETUP = path.join(__dirname, 'global-setup.ts');
const BASE = process.env.BASE_URL || 'https://test-workbench.chintx.com/';

/**
 * 从后端下发的 global-setup.ts 提取账号与项目空间(唯一事实来源)。
 * 解析不到完整账号/空间时抛错中止,绝不猜测、绝不回退。
 */
function readCredentialFromGlobalSetup() {
  if (!existsSync(GLOBAL_SETUP)) {
    throw new Error(`未找到 ${GLOBAL_SETUP} —— 请先物化(prepare.mjs / fetch_config)再登录`);
  }
  const src = readFileSync(GLOBAL_SETUP, 'utf8');
  // 注意:fill 前是 `"]').fill(`,中间有 `]`、`)`、`'`,所以通配必须能跨这三者
  // (不能用 [^)] 或 [^'] 排除——实测会把 `]` 后紧跟的 `)` 拦掉导致解析失败)。
  const mUser = src.match(/placeholder="请输入用户名"[\s\S]*?\.fill\('([^']+)'\)/);
  const mPass = src.match(/placeholder="请输入密码"[\s\S]*?\.fill\('([^']+)'\)/);
  const mSpace = src.match(/locator\('text=(项目\/[^']+)'\)\s*\.click/);
  const missing = [
    !mUser && '账号(username)',
    !mPass && '密码(password)',
    !mSpace && '项目空间(text=项目/...)',
  ].filter(Boolean);
  if (missing.length) {
    throw new Error(
      `无法从 ${GLOBAL_SETUP} 解析出完整账号/空间,缺: ${missing.join(', ')}\n` +
      `请核对后端下发的 global-setup.ts 是否包含「请输入用户名」fill、「请输入密码」fill、` +
      `以及 text=项目/... 的空间点击。`
    );
  }
  return { username: mUser[1], password: mPass[1], space: mSpace[1] };
}

const browser = await chromium.launch({
  headless: false,
  args: ['--no-sandbox', '--start-maximized'],
});

try {
  // Auth already valid? quick check
  if (existsSync(AUTH_FILE)) {
    const ctx = await browser.newContext({ storageState: AUTH_FILE, baseURL: BASE });
    const p = await ctx.newPage();
    await p.goto('/iotWeb/deviceManage', { waitUntil: 'domcontentloaded', timeout: 20000 });
    await p.waitForTimeout(1500);
    const valid = !p.url().includes('/login');
    await ctx.close();
    if (valid) {
      console.log('auth.json already valid');
      process.exit(0);
    }
    console.log('auth.json stale, re-login');
  }

  // 先解析事实来源;失败即中止,避免无谓地先把旧 auth 删了
  const { username, password, space } = readCredentialFromGlobalSetup();
  console.log(`→ 从 global-setup.ts 读取: 账号=${username}, 目标空间=${space}`);

  try { unlinkSync(AUTH_FILE); } catch {}

  const context = await browser.newContext({ baseURL: BASE, viewport: { width: 1920, height: 1080 } });
  const page = await context.newPage();

  console.log('→ opening login page');
  await page.goto('/infraWeb/login?redirectPath=/workbenchWeb', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(1500);

  // switch to Chinese if on English UI
  const langEl = page.locator('text=English');
  if (await langEl.isVisible({ timeout: 3000 }).catch(() => false)) {
    await langEl.click();
    await page.locator('text=简体中文').click();
    await page.waitForTimeout(500);
  }

  await page.locator('input[placeholder="请输入用户名"]').fill(username);
  await page.locator('input[placeholder="请输入密码"]').fill(password);
  await page.waitForTimeout(300);

  // slider captcha
  const slider = page.locator('.rc-slider-captcha-button');
  const box = await slider.boundingBox();
  if (!box) {
    await page.screenshot({ path: path.join(__dirname, 'login-fail.png') });
    throw new Error('滑块未找到');
  }
  const startX = box.x + box.width / 2;
  const startY = box.y + box.height / 2;
  await page.mouse.move(startX, startY);
  await page.waitForTimeout(100);
  await page.mouse.down();
  for (let i = 1; i <= 25; i++) {
    await page.mouse.move(startX + 490 * (i / 25), startY);
    await page.waitForTimeout(15 + Math.random() * 15);
  }
  await page.mouse.up();
  await page.waitForTimeout(500);

  await page.locator('button').filter({ hasText: '登 录' }).click();
  await page.waitForTimeout(3000);

  // select space: 只选 global-setup.ts 指定的确切空间;不在下拉则报错退出(绝不回退)
  const combo = page.locator('[role="combobox"]').first();
  if (await combo.isVisible({ timeout: 3000 }).catch(() => false)) {
    await combo.click();
    await page.waitForTimeout(800);
    const opts = await page.locator('.chint-select-item-option, [role="option"], .ant-select-item-option').allInnerTexts();
    const clean = opts.map((s) => s.trim()).filter(Boolean);
    console.log('→ space options:', JSON.stringify(clean));
    if (!clean.includes(space)) {
      throw new Error(
        `目标项目空间「${space}」不在当前账号的可选列表中,可用选项: ${JSON.stringify(clean)}\n` +
        `请核对 global-setup.ts 里的空间与当前登录账号归属是否匹配;不要自动改选其他空间。`
      );
    }
    await page.locator(`text=${space}`).first().click();
    console.log('→ picked space:', space);
    await page.waitForTimeout(1000);
  }

  // verify logged in
  const ok = await page.locator('text=个人信息').first().isVisible({ timeout: 10000 }).catch(() => false);
  if (!ok) {
    await page.screenshot({ path: path.join(__dirname, 'login-fail.png') });
    throw new Error('登录失败, URL=' + page.url());
  }

  await context.storageState({ path: AUTH_FILE });
  console.log('→ login OK, saved', AUTH_FILE);
  await context.close();
} finally {
  await browser.close();
}