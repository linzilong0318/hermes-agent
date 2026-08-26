#!/usr/bin/env node
/**
 * probe 模板:CLI 探索页面结构(方案 B,替代 MCP planner/generator 的浏览器探索)。
 *
 * 用法:
 *   export E2E_DIR=/opt/data/e2e/<sid>          # 工作区(需已物化:playwright.config.ts + auth.json)
 *   node probe-<页面>.mjs [--path /iotWeb/xxx]  # 相对路径(自动拼物化配置里的 baseURL)
 *   node probe-<页面>.mjs --url https://...     # 或直接给完整 URL
 *   node probe-<页面>.mjs --out /tmp/probe.json # JSON 落盘(默认 stdout)
 *
 * 复制为 probe-<页面>.mjs 后:
 *   1. 需要交互时在 interact(page) 里写点击/展开菜单/开下拉,再 dump(见下);
 *   2. 同页面此前测过时(有 references/*.md),只核对关键项,不必全量 dump。
 *
 * dump 内容:URL/title、input(id/placeholder/type)、button(innerText)、
 *   a 链接、可见 tab、.chint-pagination-total-text 分页文本、
 *   .chint-table-placeholder 空态、打开的下拉选项 title、表单错误文本。
 * 已知坑速记(写定位器前必读 references/pitfalls.md):
 *   - 下拉选项用 .chint-select-item-option[title="..."] 面板关联定位
 *   - 虚拟滚动表格行是 .chint-table-tbody-virtual .chint-table-row(不是 tr)
 *   - 分页按钮用 .chint-pagination-next/.chint-pagination-prev
 *   - 搜索 0 结果断言 .chint-table-placeholder,不要断言"总共 0 条"
 *   - CLI 加载 auth.json 是中文界面;MCP 时代遗留的英文定位器不适用
 */
import { chromium } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const E2E_DIR = process.env.E2E_DIR || process.cwd();
const AUTH_FILE = path.join(E2E_DIR, 'auth.json');
const CONFIG_FILE = path.join(E2E_DIR, 'playwright.config.ts');

function extractBaseUrl() {
  try {
    const src = fs.readFileSync(CONFIG_FILE, 'utf8');
    const m = src.match(/baseURL\s*:\s*(?:process\.env\.[A-Z_0-9]+\s*\|\|\s*)?['"]([^'"]+)['"]/);
    if (m) return m[1];
  } catch {}
  return null;
}

function parseArgs() {
  const a = process.argv.slice(2);
  const out = { path: null, url: null, out: null };
  for (let i = 0; i < a.length; i++) {
    if (a[i] === '--path') out.path = a[++i];
    else if (a[i] === '--url') out.url = a[++i];
    else if (a[i] === '--out') out.out = a[++i];
  }
  return out;
}

/** 复制本文件后在此写交互(展开菜单/开下拉/翻页),再 dump。默认不做交互。 */
async function interact(page) {
  // 示例:展开侧边菜单
  // await page.locator('.chint-menu-submenu-title', { hasText: '设备管理' }).click();
  // await page.locator('.chint-menu-item', { hasText: '新增设备' }).click();
  // 示例:打开某个下拉看选项
  // await page.locator('#control-hooks_xxx').click();
}

/** 结构 dump:返回 JSON 对象,并打印人读摘要。 */
async function dump(page) {
  const data = {
    url: page.url(),
    title: await page.title(),
    inputs: await page.locator('input').evaluateAll(els =>
      els.map(e => ({ id: e.id, placeholder: e.placeholder, type: e.type }))),
    buttons: await page.locator('button').evaluateAll(els =>
      [...new Set(els.map(e => (e.innerText || '').trim()).filter(Boolean))]),
    links: await page.locator('a').evaluateAll(els =>
      els.map(e => ({ text: (e.innerText || '').trim(), href: e.href })).filter(x => x.text)),
    tabs: await page.locator('[role="tab"], .chint-tabs-tab').evaluateAll(els =>
      [...new Set(els.map(e => (e.innerText || '').trim()).filter(Boolean))]),
    pagination: await page.locator('.chint-pagination-total-text').allInnerTexts(),
    emptyState: await page.locator('.chint-table-placeholder').allInnerTexts(),
    dropdownOptions: await page
      .locator('.chint-select-dropdown:not([style*="display: none"]) .chint-select-item-option')
      .evaluateAll(els => [...new Set(els.map(e => e.getAttribute('title') || (e.innerText || '').trim()).filter(Boolean))]),
    formErrors: await page.locator('.chint-form-item-explain-error').allInnerTexts(),
  };
  console.log('===== probe dump =====');
  console.log(JSON.stringify(data, null, 2));
  console.log('===== 摘要 =====');
  console.log(`URL: ${data.url}`);
  console.log(`inputs(${data.inputs.length}): ${data.inputs.map(i => `${i.id || i.placeholder}(${i.type})`).join(', ')}`);
  console.log(`buttons: ${data.buttons.join(' | ')}`);
  if (data.tabs.length) console.log(`tabs: ${data.tabs.join(' | ')}`);
  if (data.pagination.length) console.log(`pagination: ${data.pagination.join(' | ')}`);
  if (data.emptyState.length) console.log(`emptyState: ${data.emptyState.join(' | ')}`);
  if (data.dropdownOptions.length) console.log(`dropdownOptions: ${data.dropdownOptions.join(' | ')}`);
  if (data.formErrors.length) console.log(`formErrors: ${data.formErrors.join(' | ')}`);
  return data;
}

(async () => {
  const args = parseArgs();
  const baseUrl = extractBaseUrl();
  if (!args.url && !args.path) {
    console.error('用法: node probe-<页面>.mjs --path <相对路径> | --url <完整URL> [--out <json>]');
    process.exit(2);
  }
  if (!args.url && !baseUrl) {
    console.error(`无法从 ${CONFIG_FILE} 提取 baseURL —— 先物化(阶段 1)或改用 --url`);
    process.exit(2);
  }
  const target = args.url || baseUrl + args.path;
  const storageState = fs.existsSync(AUTH_FILE) ? AUTH_FILE : undefined;
  if (!storageState) console.warn('[probe] auth.json 不存在 —— 未登录态浏览(先 DISPLAY=:<n> node login.mjs)');

  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = storageState
    ? await browser.newContext({ storageState })
    : await browser.newContext();
  const page = await context.newPage();
  console.log(`[probe] goto ${target}`);
  await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(1500); // 等首屏渲染

  await interact(page);
  await page.waitForTimeout(800);
  const data = await dump(page);
  if (args.out) fs.writeFileSync(args.out, JSON.stringify(data, null, 2));
  await browser.close();
})().catch(e => {
  console.error('[probe] 失败:', e.message);
  process.exit(1);
});