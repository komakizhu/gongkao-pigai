import { expect, test } from "@playwright/test";
import type { BrowserContext } from "@playwright/test";

test.use({ serviceWorkers: "block" });

test("records and restores an answer when a viewer denies IndexedDB", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "indexedDB", { get() { throw new DOMException("Denied by viewer", "SecurityError"); } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "新建练习" }).click();
  await page.getByLabel("练习名称").fill("受限查看器");
  await page.getByLabel("题目数量").fill("100");
  await page.getByRole("button", { name: "开始记录" }).click();
  await expect(page.getByText("0/100 已答")).toBeVisible();
  await page.locator(".question-row").last().getByRole("button", { name: "选择 D" }).click();
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.locator(".save-status")).toHaveText("已保存");
  await page.reload();
  await page.getByRole("button", { name: "继续答题" }).click();
  await expect(page.locator(".question-row").last().getByRole("button", { name: "选择 D" })).toHaveAttribute("aria-pressed", "true");
});

test("exports and pastes all 100 answers when both browser storage APIs are denied", async ({ browser }) => {
  const denyStorage = async (context: BrowserContext) => context.addInitScript(() => {
    Object.defineProperty(navigator, "canShare", { value: () => false });
    for (const name of ["indexedDB", "localStorage"]) Object.defineProperty(window, name, { get() { throw new DOMException("Denied by viewer", "SecurityError"); } });
  });
  const first = await browser.newContext({ serviceWorkers: "block" });
  await denyStorage(first);
  const page = await first.newPage();
  await page.goto(test.info().project.use.baseURL!);
  await page.getByRole("button", { name: "新建练习" }).click();
  await page.getByLabel("练习名称").fill("复制恢复100题");
  await page.getByLabel("题目数量").fill("100");
  await page.getByRole("button", { name: "开始记录" }).click();
  await page.locator(".question-row").last().getByRole("button", { name: "选择 D" }).click();
  await expect(page.getByText("未保存", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.locator(".save-status")).toContainText("此查看器未能保存当前作答");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "导出.json" }).click();
  const json = await page.locator("#transfer-text").inputValue();
  expect(JSON.parse(json).exercise.questions).toHaveLength(100);
  await first.close();
  const second = await browser.newContext({ serviceWorkers: "block" });
  await denyStorage(second);
  const restored = await second.newPage();
  await restored.goto(test.info().project.use.baseURL!);
  await restored.getByRole("button", { name: "粘贴恢复" }).click();
  await restored.getByLabel("完整作答 JSON").fill(json);
  await restored.getByRole("button", { name: "恢复作答" }).click();
  await expect(restored.locator(".question-row")).toHaveCount(100);
  await expect(restored.locator(".question-row").last().getByRole("button", { name: "选择 D" })).toHaveAttribute("aria-pressed", "true");
  await second.close();
});
