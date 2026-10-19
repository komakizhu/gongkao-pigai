import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

test.use({ serviceWorkers: "block" });

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.addInitScript(() => Object.defineProperty(navigator, "canShare", { value: () => false }));
  await page.goto("/");
  await page.getByRole("button", { name: "新建练习" }).click();
  await page.getByLabel("练习名称").fill("连续点选");
  await page.getByLabel("题目数量").fill("100");
  await page.getByRole("button", { name: "开始记录" }).click();
});

test("the document is the only answer-page scroller", async ({ page }) => {
  const list = page.locator(".question-list");
  expect(await list.evaluate((element) => getComputedStyle(element).overflowY)).toBe("visible");
  await page.getByRole("button", { name: "选择 A", exact: true }).first().hover();
  await page.mouse.wheel(0, 700);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(300);
  expect(await list.evaluate((element) => element.scrollTop)).toBe(0);
  await expect(page.locator('.answer-button[aria-pressed="true"]')).toHaveCount(0);
});

test("a touch drag is not recorded as an answer while the next quick tap still works", async ({ page }) => {
  const button = page.locator(".question-row").first().getByRole("button", { name: "选择 B" });
  await button.dispatchEvent("pointerdown", { pointerType: "touch", pointerId: 1, clientX: 80, clientY: 300 });
  await button.dispatchEvent("pointermove", { pointerType: "touch", pointerId: 1, clientX: 82, clientY: 260 });
  await button.dispatchEvent("pointerup", { pointerType: "touch", pointerId: 1, clientX: 82, clientY: 260 });
  await button.dispatchEvent("click", { detail: 1 });
  await expect(button).toHaveAttribute("aria-pressed", "false");
  await button.dispatchEvent("pointerdown", { pointerType: "touch", pointerId: 2, clientX: 80, clientY: 300 });
  await button.dispatchEvent("pointerup", { pointerType: "touch", pointerId: 2, clientX: 81, clientY: 301 });
  await button.dispatchEvent("click", { detail: 1 });
  await expect(button).toHaveAttribute("aria-pressed", "true");
});

test("rapid choices keep the rendered buttons alive and export all 100 answers", async ({ page }) => {
  const result = await page.locator(".question-list").evaluate((list) => {
    const rows = [...list.querySelectorAll(".question-row")];
    const answers = ["B", "D", "A", "C"];
    const buttons = rows.map((row, i) => row.querySelector<HTMLButtonElement>(`[data-action="answer"][data-answer="${answers[i % 4]}"]`)!);
    const started = performance.now();
    buttons.forEach((button) => button.click());
    return { elapsed: performance.now() - started, disconnected: buttons.filter((button) => !button.isConnected).length };
  });
  expect(result.disconnected).toBe(0);
  await expect(page.getByText("100/100 已答", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: "继续答题" }).click();
  await expect(page.locator('.answer-button[aria-pressed="true"]')).toHaveCount(100);
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出.json" }).click();
  const payload = JSON.parse(await readFile((await (await downloaded).path())!, "utf8"));
  expect(payload.exercise.questions.map((q: { answer: string }) => q.answer)).toEqual(Array.from({ length: 100 }, (_, i) => ["B", "D", "A", "C"][i % 4]));
  console.log(`100-choice burst: ${result.elapsed.toFixed(0)}ms; detached buttons: ${result.disconnected}`);
});

test("two compact rows align yellow and blue choices and use equal-size marker buttons", async ({ page }) => {
  for (const width of [320, 375, 430, 768]) {
    await page.setViewportSize({ width, height: 812 });
    const row = page.locator(".question-row").first();
    await row.getByRole("button", { name: /^不确定/ }).click();
    const number = await row.locator("summary").boundingBox();
    const markers = await row.locator(".question-markers").boundingBox();
    const type = await row.locator(".question-type").boundingBox();
    const toggle = await row.locator(".uncertain-toggle").boundingBox();
    expect(Math.abs(number!.y - markers!.y)).toBeLessThan(2);
    expect(Math.abs(type!.y + type!.height / 2 - (toggle!.y + toggle!.height / 2))).toBeLessThan(2);
    expect(markers!.x).toBeGreaterThanOrEqual(toggle!.x - 1);
    for (let i = 0; i < 4; i++) {
      const yellow = await row.locator(".uncertain-option").nth(i).boundingBox();
      const blue = await row.locator(".answer-button").nth(i).boundingBox();
      expect(Math.abs(yellow!.x - blue!.x)).toBeLessThan(1);
      expect(Math.abs(yellow!.width - blue!.width)).toBeLessThan(1);
      expect(Math.abs(yellow!.height - blue!.height)).toBeLessThan(1);
      expect(yellow!.y).toBeLessThan(blue!.y);
      if (i < 3) {
        const mark = await row.locator(".uncertain-marker").nth(i).boundingBox();
        expect(Math.abs(mark!.width - blue!.width)).toBeLessThan(1);
        expect(Math.abs(mark!.height - blue!.height)).toBeLessThan(1);
      }
    }
    await row.getByRole("button", { name: "整题不确定" }).click();
    const selectedCircle = await row.getByRole("button", { name: "整题不确定" }).evaluate((element) => getComputedStyle(element).backgroundColor);
    expect(selectedCircle).not.toBe("rgb(238, 241, 246)");
    await expect(row.getByRole("button", { name: /^不确定/ })).not.toContainText("整题");
    await row.getByRole("button", { name: "标记 A 为不确定" }).click();
    await expect(row.getByRole("button", { name: /^不确定/ })).not.toContainText("A");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await row.getByRole("button", { name: /^不确定/ }).click();
  }
});

test("Save writes the current page locally without downloading HTML", async ({ page }) => {
  let downloads = 0;
  page.on("download", () => downloads++);
  await page.locator(".question-row").last().getByRole("button", { name: "选择 C" }).click();
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.locator(".save-status")).toHaveText("已保存");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(downloads).toBe(0);
  await page.reload();
  await page.getByRole("button", { name: "继续答题" }).click();
  await expect(page.locator(".question-row").last().getByRole("button", { name: "选择 C" })).toHaveAttribute("aria-pressed", "true");
});

test("only an explicit Save marks the current revision saved, including after reopening", async ({ page }) => {
  const first = page.locator(".question-row").first();
  await expect(page.locator(".save-status")).toHaveText("未保存");
  await first.getByRole("button", { name: "选择 B" }).click();
  // Background recovery must not masquerade as the user pressing Save.
  await page.reload();
  await page.getByRole("button", { name: "继续答题" }).click();
  await expect(first.getByRole("button", { name: "选择 B" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".save-status")).toHaveText("未保存");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.locator(".save-status")).toHaveText("已保存");
  await page.reload();
  await page.getByRole("button", { name: "继续答题" }).click();
  await expect(page.locator(".save-status")).toHaveText("已保存");
  await first.getByRole("button", { name: "选择 D" }).click();
  await expect(page.locator(".save-status")).toHaveText("未保存");
});
