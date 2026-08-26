#!/usr/bin/env node
/**
 * 全模块文本扫描(方案 B):验证某文案/元素是否存在于模块任一页面。
 * 用途:用例与绑定页面疑似不匹配时,先拿"该 UI 不存在"的硬证据再决定落点(2026-08-13 实测:
 *   functionUid 绑定设备类型页但用例要求「指标/暂无历史数据」,扫完 11 页确认模块内不存在)。
 *
 * 用法:
 *   export E2E_DIR=/opt/data/e2e/<sid>    # 需已物化(playwright.config.ts + auth.json)
 *   node $SKILL_DIR/scripts/probe-sweep.mjs --terms 指标,历史,暂无历史数据 --base /iotWeb
 *   # --terms 逗号分隔目标文案(默认:指标,历史,暂无历史数据);--base 模块根路径(默认 /iotWeb)
 *   # generic 脚本,无需复制到会话目录,直接以技能目录路径运行即可(仅读 E2E_DIR 的 config/auth)
 *
 * 关键坑(写死了避免重踩):
 *   - 子菜单未展开时子项不渲染 data-menu-id → 先全部展开再提取路径
 *   - 不要逐个点菜单项导航(导航后菜单折叠,后续点击 "element is not visible")→ 提取路径后直接 goto
 */
import { chromium } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const E2E_DIR = process.env.E2E_DIR || process.cwd();
const AUTH_FILE = path.join(E2E_DIR, 'auth.json');
const CONFIG_FILE = path.join(E2E_DIR, 'playwright.config.ts');
const argv = process.argv.slice(2);
const terms = (argv.find(a => a.startsWith('--terms=')) || '--terms=指标,历史,暂无历史数据').split('=')[1].split(',');
const basePath = (argv.find(a => a.startsWith('--base=')) || '--base=/iotWeb').split('=')[1];

const src = fs.readFileSync(CONFIG_FILE, 'utf8');
const m = src.match(/baseURL\s*:\s*(?:process\.env\.[A-Z_0-9]+\s*\|\|\s*)?['"]([^'"]+)['"]/);
const baseUrl = m ? m[1] : null;
if (!baseUrl) { console.error(`无法从 ${CONFIG_FILE} 提取 baseURL(先物化)`); process.exit(2); }

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const context = await browser.newContext({ storageState: AUTH_FILE });
const page = await context.newPage();
await page.goto(baseUrl + basePath, { waitUntil: 'domcontentloaded', timeout: 30000 });
await page.waitForTimeout(1500);

// 1) 展开全部子菜单(子项 data-menu-id 才渲染)
const subs = await page.locator('.chint-menu-submenu-title').count();
for (let i = 0; i < subs; i++) {
  await page.locator('.chint-menu-submenu-title').nth(i).click();
  await page.waitForTimeout(400);
}
const paths = await page.evaluate(() =>
  [...new Set([...document.querySelectorAll('[data-menu-id]')]
    .map(el => el.getAttribute('data-menu-id').replace('rc-menu-uuid-', ''))
    .filter(p => p.startsWith('/')))]
);
console.log('扫描路径:', JSON.stringify(paths));

// 2) 逐个导航扫描 body 文本
for (const p of paths) {
  try {
    await page.goto(baseUrl + basePath + p, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(1200);
    const hits = await page.evaluate((ts) => {
      const text = document.body.innerText.replace(/\s+/g, ' ');
      return ts.filter(t => text.includes(t));
    }, terms);
    console.log(`${p.padEnd(42)} ${hits.length ? '命中: ' + hits.join(' | ') : '(无命中)'}`);
  } catch (e) {
    console.log(`${p.padEnd(42)} ERROR: ${e.message.split('\n')[0].slice(0, 60)}`);
  }
}
await browser.close();