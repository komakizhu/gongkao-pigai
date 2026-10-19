import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  // Exercise the ordinary download path; native share is verified in its own suite.
  await page.addInitScript(() => Object.defineProperty(navigator, "canShare", { value: () => false }));
});

test("creates a narrow exercise, records a choice, filters and exports", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 760 });
  await page.goto("/");
  await page.getByRole("button", { name: "新建练习" }).click();
  await page.getByLabel("练习名称").fill("窄屏演示");
  await page.getByLabel("起始题号").fill("41");
  await page.getByLabel("题目数量").fill("3");
  await page.getByRole("button", { name: "开始记录" }).click();
  await expect(page.getByText("0/3 已答")).toBeVisible();
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", 320);
  await page.getByRole("button", { name: "查看未答" }).click();
  await expect(page.getByRole("button", { name: "查看全部" })).toBeVisible();
  await expect(page.locator(".question-row")).toHaveCount(3);
  const q43 = page.locator('[data-question-id]').filter({ has: page.getByText("43", { exact: true }) }).first();
  await q43.getByRole("button", { name: "选择 B" }).click();
  await q43.getByRole("button", { name: "选择 D" }).click();
  await expect(page.getByText("1/3 已答")).toBeVisible();
  await expect(q43.getByRole("button", { name: "选择 D" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("43", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "查看全部" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出.json" }).click();
  expect((await download).suggestedFilename()).toMatch(/\.json$/);
});

test("keeps unanswered questions and saves without a completion step", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "新建练习" }).click();
  await page.getByLabel("练习名称").fill("直接保存演示");
  await page.getByLabel("起始题号").fill("1");
  await page.getByLabel("题目数量").fill("2");
  await page.getByRole("button", { name: "开始记录" }).click();
  await expect(page.getByText("0/2 已答")).toBeVisible();
  await expect(page.getByRole("button", { name: "完成练习" })).toHaveCount(0);
  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.locator(".save-status")).toHaveText("已保存");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("restores a saved choice after reload at supported widths", async ({ page }) => {
  for (const width of [320, 375, 430, 768]) {
    await page.setViewportSize({ width, height: 760 });
    await page.goto("/");
    await page.getByRole("button", { name: "新建练习" }).click();
    await page.getByLabel("练习名称").fill(`恢复 ${width}`);
    await page.getByLabel("起始题号").fill("41");
    await page.getByLabel("题目数量").fill("2");
    await page.getByRole("button", { name: "开始记录" }).click();
    await page.locator('[data-question-id]').first().getByRole("button", { name: "选择 D" }).click();
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await expect(page.locator(".save-status")).toHaveText("已保存");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.reload();
    await expect(page.getByText(`恢复 ${width}`)).toBeVisible();
    await page.getByRole("button", { name: "继续答题" }).first().click();
    await expect(page.locator('[data-question-id]').first().getByRole("button", { name: "选择 D" })).toHaveAttribute("aria-pressed", "true");
    await page.goto("/");
  }
});

test("marks independent uncertain options, keeps the panel open, and restores collapsed state", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 760 });
  await page.goto("/");
  await page.getByRole("button", { name: "新建练习" }).click();
  await page.getByLabel("练习名称").fill("不确定选项演示");
  await page.getByLabel("起始题号").fill("1");
  await page.getByLabel("题目数量").fill("2");
  await page.getByRole("button", { name: "开始记录" }).click();

  const question = page.locator(".question-row").first();
  const toggle = question.getByRole("button", { name: /^不确定/ });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(question.locator(".question-markers")).toBeVisible();
  await question.getByRole("button", { name: "整题不确定" }).click();
  await expect(question.getByRole("button", { name: "整题不确定" })).toHaveAttribute("aria-pressed", "true");
  for (const option of ["A", "B", "C", "D"]) {
    await expect(question.getByRole("button", { name: `标记 ${option} 为不确定` })).toHaveAttribute("aria-pressed", "false");
  }
  await question.getByRole("button", { name: "标记 A 为不确定" }).click();
  await question.getByRole("button", { name: "标记 C 为不确定" }).click();
  await expect(toggle).toHaveText("不确定 ⌃");
  await expect(question.getByRole("button", { name: "标记 A 为不确定" })).toHaveAttribute("aria-pressed", "true");
  await expect(question.getByRole("button", { name: "标记 C 为不确定" })).toHaveAttribute("aria-pressed", "true");

  await question.getByRole("button", { name: "选择 D" }).click();
  await expect(page.getByText("1/2 已答")).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(question.getByRole("button", { name: "选择 D" })).toHaveAttribute("aria-pressed", "true");

  await question.locator("summary").click();
  await question.getByRole("button", { name: "清空答案" }).click();
  await expect(page.getByText("0/2 已答")).toBeVisible();
  await expect(question.getByRole("button", { name: "选择 D" })).toHaveAttribute("aria-pressed", "false");
  await expect(toggle).toHaveText("不确定 ⌃");

  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.locator(".save-status")).toHaveText("已保存");
  await page.reload();
  await page.getByRole("button", { name: "继续答题" }).click();
  const reopened = page.locator(".question-row").first();
  const reopenedToggle = reopened.getByRole("button", { name: /^不确定/ });
  await expect(reopenedToggle).toHaveAttribute("aria-expanded", "false");
  await expect(reopenedToggle).toHaveText("不确定 ⌄");
  await reopenedToggle.click();
  await expect(reopened.getByRole("button", { name: "标记 A 为不确定" })).toHaveAttribute("aria-pressed", "true");
});

test("keeps uncertain controls usable without horizontal overflow", async ({ page }) => {
  for (const width of [320, 375, 430, 768]) {
    await page.setViewportSize({ width, height: 760 });
    await page.goto("/");
    await page.getByRole("button", { name: "新建练习" }).click();
    await page.getByLabel("练习名称").fill(`不确定布局 ${width}`);
    await page.getByLabel("起始题号").fill("1");
    await page.getByLabel("题目数量").fill("1");
    await page.getByRole("button", { name: "开始记录" }).click();
    const question = page.locator(".question-row").first();
    await question.getByRole("button", { name: /^不确定/ }).click();
    await expect(question.getByRole("button", { name: "标记 B 为不确定" })).toBeVisible();
    const answersBox = await question.locator(".answer-options").boundingBox();
    const toggleBox = await question.getByRole("button", { name: /^不确定/ }).boundingBox();
    expect(answersBox).not.toBeNull();
    expect(toggleBox).not.toBeNull();
    expect(answersBox!.width).toBeGreaterThanOrEqual(116);
    const answerButtonRights = await question.locator(".answer-button").evaluateAll((nodes) =>
      nodes.map((node) => node.getBoundingClientRect().right),
    );
    for (const right of answerButtonRights) {
      expect(right).toBeLessThanOrEqual(toggleBox!.x + 0.5);
    }
    expect(toggleBox!.x).toBeGreaterThan(answersBox!.x);
    expect(toggleBox!.y).toBeLessThan(answersBox!.y + answersBox!.height);
    await question.getByRole("button", { name: "选择 A" }).click();
    await expect(question.getByRole("button", { name: "选择 A" })).toHaveAttribute("aria-pressed", "true");
    await question.getByRole("button", { name: "标记 B 为不确定" }).click();
    await expect(question.getByRole("button", { name: "标记 B 为不确定" })).toHaveAttribute("aria-pressed", "true");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.goto("/");
  }
});

test("reopens the cached app while offline", async ({ page, context }) => {
  await page.goto("/");
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller), undefined, { timeout: 10_000 });
  await expect(page.getByText(/离线|自动保存/)).toHaveCount(0);
  await context.setOffline(true);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "答题记录" })).toBeVisible();
  await context.setOffline(false);
});


test("imports a public config and records multiple and boolean answers", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 760 });
  await page.goto("/");
  const config = {
    schemaVersion: 2,
    type: "answer-recorder-config",
    paperId: "e2e-three-types",
    paperVersion: "v1",
    name: "三类题型导入",
    questions: [
      { questionId: "e2e-three-types:q:1", number: 1, type: "single", options: ["A", "B", "C", "D"] },
      { questionId: "e2e-three-types:q:2", number: 2, type: "multiple", options: ["A", "B", "C", "D"] },
      { questionId: "e2e-three-types:q:3", number: 3, type: "boolean", options: ["对", "错"] },
    ],
  };
  await page.getByRole("button", { name: "导入答题卡" }).click();
  await page.locator("#import-config-file").setInputFiles({ name: "config.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(config)) });
  await expect(page.getByText("三类题型导入", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "继续答题" }).click();
  const q2 = page.locator('.question-row[data-question-id]').filter({ hasText: "2" }).first();
  await q2.getByRole("button", { name: "选择 A" }).click();
  await q2.getByRole("button", { name: "选择 C" }).click();
  await expect(q2.getByRole("button", { name: "选择 A" })).toHaveAttribute("aria-pressed", "true");
  await q2.getByRole("button", { name: /^不确定/ }).click();
  await q2.getByRole("button", { name: "标记 B 为不确定" }).click();
  await expect(q2.getByRole("button", { name: "标记 B 为不确定" })).toHaveAttribute("aria-pressed", "true");
  const q3 = page.locator('.question-row[data-question-id]').filter({ hasText: "3" }).first();
  await q3.getByRole("button", { name: "选择 错" }).click();
  await expect(q3.getByRole("button", { name: "选择 错" })).toHaveAttribute("aria-pressed", "true");
  await q3.getByRole("button", { name: /^不确定/ }).click();
  await q3.getByRole("button", { name: "标记 对 为不确定" }).click();
  await expect(q3.getByRole("button", { name: "标记 对 为不确定" })).toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});
