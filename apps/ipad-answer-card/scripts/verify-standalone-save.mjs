#!/usr/bin/env node

import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import assert from "node:assert/strict";
import { chromium, webkit } from "playwright";

if (!process.argv[2]) throw new Error("用法：node scripts/verify-standalone-save.mjs <单文件.html>");
const htmlPath = resolve(process.cwd(), process.argv[2]);
const originalHtml = await readFile(htmlPath, "utf8");
const temporaryDirectory = await mkdtemp(join(tmpdir(), "answer-recorder-"));
const answers = Array.from({ length: 100 }, (_, i) => ["B", "D", "A", "C"][i % 4]);
const labels = ["标记本题重要", "整题不确定", "标记本题不会做", "标记 A 为不确定"];
const note = "100题恢复测试 </script> & 备注";
const normalViewer = (context) => context.addInitScript(() => Object.defineProperty(navigator, "canShare", { value: () => false }));
async function open(page, path) {
  await page.goto(pathToFileURL(path).href);
  await page.getByRole("button", { name: "继续答题" }).click();
  await page.locator(".question-row").first().waitFor();
}
async function exportFile(page, kind) {
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: `导出.${kind}` }).click();
  const result = await download;
  const text = await readFile(await result.path(), "utf8");
  assert.ok(result.suggestedFilename().endsWith(`.${kind}`));
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  return text;
}
// Legacy embedded snapshots remain readable, but the Save button must never generate one.
async function legacyFixture(path, json) {
  const safe = json.replaceAll("<", "\\u003c").replaceAll("\u2028", "\\u2028").replaceAll("\u2029", "\\u2029");
  await writeFile(path, originalHtml.replace(/<body([^>]*)>/i, `<body$1><script id="answer-recorder-state" type="application/json">${safe}</script>`));
}

for (const [engine, launcher] of Object.entries({ chromium, webkit })) {
  const profile = join(temporaryDirectory, `${engine}-profile`);
  let persistent = await launcher.launchPersistentContext(profile, { headless: true, acceptDownloads: true, viewport: { width: 375, height: 812 } });
  let browser;
  try {
    await normalViewer(persistent);
    const firstPage = await persistent.newPage();
    await open(firstPage, htmlPath);
    assert.equal(await firstPage.locator(".question-row").count(), 100);
    const disconnected = await firstPage.locator(".question-list").evaluate((list, choices) => {
      const buttons = [...list.children].map((row, i) => row.querySelector(`[data-action="answer"][data-answer="${choices[i]}"]`));
      buttons.forEach((button) => button.click());
      return buttons.filter((button) => !button.isConnected).length;
    }, answers);
    assert.equal(disconnected, 0);
    const first = firstPage.locator(".question-row").first();
    await first.getByRole("button", { name: /^不确定/ }).click();
    for (const label of labels) await first.getByRole("button", { name: label }).click();
    await first.locator("summary").click();
    await first.getByLabel("第 1 题备注").fill(note);
    await first.locator("summary").click();
    await firstPage.screenshot({ path: join(dirname(htmlPath), `紧凑布局-${engine}-375px.png`) });
    // Filtering must not limit what Save and export persist.
    await firstPage.getByRole("button", { name: "查看未答" }).click();
    let downloads = 0;
    firstPage.on("download", () => downloads++);
    await firstPage.getByRole("button", { name: "保存", exact: true }).click();
    await firstPage.waitForFunction(() => document.querySelector(".save-status")?.textContent === "已保存");
    assert.equal(downloads, 0);
    assert.equal(await firstPage.getByRole("dialog").count(), 0);
    const json = await exportFile(firstPage, "json");
    assert.deepEqual(JSON.parse(json).exercise.questions.map((q) => q.answer), answers);
    await persistent.close();

    // Close the whole browser process and reopen the SAME original HTML with the SAME profile.
    persistent = await launcher.launchPersistentContext(profile, { headless: true, acceptDownloads: true });
    const originalPage = await persistent.newPage();
    await open(originalPage, htmlPath);
    assert.deepEqual(await originalPage.locator('.answer-button[aria-pressed="true"]').allTextContents(), answers);
    const reopenedFirst = originalPage.locator(".question-row").first();
    await reopenedFirst.getByRole("button", { name: /^不确定/ }).click();
    await reopenedFirst.locator("summary").click();
    assert.equal(await reopenedFirst.getByLabel("第 1 题备注").inputValue(), note);
    await reopenedFirst.locator("summary").click();
    for (const label of labels) assert.equal(await reopenedFirst.getByRole("button", { name: label }).getAttribute("aria-pressed"), "true");
    await persistent.close();

    browser = await launcher.launch({ headless: true });
    const snapshotPath = join(temporaryDirectory, `${engine}-legacy.html`);
    await legacyFixture(snapshotPath, json);
    const context = await browser.newContext({ acceptDownloads: true });
    await normalViewer(context);
    const page = await context.newPage();
    await open(page, snapshotPath);
    assert.deepEqual(await page.locator('.answer-button[aria-pressed="true"]').allTextContents(), answers);
    const csv = await exportFile(page, "csv");
    assert.equal(csv.trim().split(/\r?\n/).length, 101);
    assert.ok(csv.includes(",1,single,B,true"));
    await page.locator(".question-row").first().getByRole("button", { name: "选择 D" }).click();
    // No manual Save: the synchronous journal must survive immediate close too.
    await page.close();
    const reopened = await context.newPage();
    await open(reopened, snapshotPath);
    assert.equal(await reopened.locator(".question-row").first().getByRole("button", { name: "选择 D" }).getAttribute("aria-pressed"), "true");
    const latest = await exportFile(reopened, "json");
    const latestPath = join(temporaryDirectory, `${engine}-legacy-latest.html`);
    await legacyFixture(latestPath, latest);
    await context.close();

    const restricted = await browser.newContext({ acceptDownloads: true });
    await restricted.addInitScript(() => {
      Object.defineProperty(navigator, "canShare", { value: () => false });
      for (const key of ["indexedDB", "localStorage"]) Object.defineProperty(window, key, { get() { throw new DOMException("Viewer denied storage", "SecurityError"); } });
    });
    const restrictedPage = await restricted.newPage();
    await open(restrictedPage, latestPath);
    assert.equal(await restrictedPage.locator('.answer-button[aria-pressed="true"]').count(), 100);
    await restrictedPage.getByRole("button", { name: "保存", exact: true }).click();
    await restrictedPage.waitForFunction(() => document.querySelector(".save-status")?.textContent?.includes("此查看器未能保存当前作答"));
    assert.equal(await restrictedPage.getByRole("dialog").count(), 0);
    const restrictedJson = JSON.parse(await exportFile(restrictedPage, "json"));
    assert.equal(restrictedJson.exercise.questions.length, 100);
    assert.equal(restrictedJson.exercise.questions[99].answer, "C");
    await restricted.close();
    console.log(JSON.stringify({ engine, answersRestored: 100, detachedButtons: 0, saveDoesNotDownload: true, originalFileSurvivesBrowserProcessRestart: true, annotationsRestored: true, newerEditsSurviveOldFileReopen: true, restrictedStorageReportsSaveFailure: true, csvRecords: 100 }));
  } finally {
    await persistent.close();
    await browser?.close();
  }
}
