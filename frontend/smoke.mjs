/** 全画面のスモークテスト。
 *
 *   1. API を起動しておく（ビルド済みフロントを同じサーバから配信する）
 *        DMDEG_DATA_DIR=example_data DMDEG_BUILD_DIR=build_example \
 *          python -m uvicorn dmdeg.api.main:app --port 8000
 *   2. npm run smoke
 *
 * ブラウザは PLAYWRIGHT_CHROMIUM か、Playwright 同梱のものを使う。
 * 同梱版が無い場合は `npx playwright install chromium` が必要。
 */

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.DMDEG_BASE_URL ?? "http://127.0.0.1:8000";
const OUT = process.env.DMDEG_SMOKE_OUT ?? "smoke-output";
mkdirSync(OUT, { recursive: true });

const launchOptions = process.env.PLAYWRIGHT_CHROMIUM
  ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM }
  : {};

const browser = await chromium.launch(launchOptions);
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });

const errors = [];
page.on("console", (message) => {
  if (message.type() === "error") errors.push(message.text());
});
page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
page.on("response", (response) => {
  if (response.url().includes("/api/") && response.status() >= 400) {
    errors.push(`${response.status()} ${response.url()}`);
  }
});

async function visit(name, path, waitFor) {
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" });
  if (waitFor) {
    try {
      await page.waitForSelector(waitFor, { timeout: 15000 });
    } catch {
      errors.push(`[${name}] セレクタ待機失敗: ${waitFor}`);
    }
  }
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  const plots = await page.locator(".js-plotly-plot").count();
  const heading = (await page.locator("h1").first().textContent().catch(() => "")) ?? "";
  console.log(`${name.padEnd(14)} h1="${heading.trim()}" グラフ=${plots}`);
}

await visit("01-browse", "/", ".dataset");
await visit("02-dataset", "/datasets/GSE900001", ".js-plotly-plot");
await visit("03-gene", "/genes?gene=Lcn2", ".js-plotly-plot");
await visit(
  "04-compare",
  "/compare?case_dataset=GSE900001&case_group=dbdb_kidney_16w&case_organ=kidney",
  ".js-plotly-plot",
);
await visit("05-analysis", "/analysis?color_by=organ&top=500", ".js-plotly-plot");
await visit("06-docs", "/docs", ".card");

// 比較画面: WT 自動選択と、URL からの状態復元を確認する
const compareUrl = `${BASE}/compare?case_dataset=GSE900001&case_group=dbdb_kidney_16w&case_organ=kidney`;
await page.goto(compareUrl, { waitUntil: "networkidle" });
await page.waitForSelector(".summary-bar", { timeout: 15000 });

const summary = await page.locator(".summary-bar").innerText();
console.log(`\n--- 比較サマリ ---\n${summary}`);

const autoTag = await page.locator(".tag--control").first().textContent().catch(() => null);
if (autoTag?.includes("WT 自動選択") !== true) errors.push("WT 自動選択のタグが出ていない");

const topGenes = (await page.locator("table tbody tr td:first-child").allTextContents()).slice(0, 10);
console.log(`DEG 表 上位10: ${topGenes.join(", ")}`);

// 合成データに仕込んだ差分遺伝子が上位に出ているか
const spiked = new Set([
  "Havcr1", "Lcn2", "Timp1", "Col1a1", "Fn1", "Ccl2", "Spp1", "Vim", "Adgre1", "Tgfb1",
  "Slc34a1", "Lrp2", "Umod", "Kap", "Slc12a1", "Aqp2",
]);
const hits = topGenes.filter((gene) => spiked.has(gene)).length;
console.log(`上位10 のうち仕込み遺伝子: ${hits}/10`);
if (hits < 8) errors.push(`仕込んだ差分遺伝子が上位に出ていない (${hits}/10)`);

await page.reload({ waitUntil: "networkidle" });
await page.waitForSelector(".summary-bar", { timeout: 15000 });
const restored = await page.locator(".summary-bar").innerText();
if (restored !== summary) errors.push("URL から状態を復元できていない");
console.log(`URL 復元一致: ${restored === summary}`);

console.log(`\nJS / API エラー: ${errors.length ? "" : "なし"}`);
for (const error of errors) console.log(`  - ${error}`);

await browser.close();
process.exit(errors.length ? 1 : 0);
