import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

test.use({ serviceWorkers: "block" });

test("reopening a saved snapshot keeps answers changed since that snapshot", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, "canShare", { value: () => false }));
  await page.goto("/");
  await page.getByRole("button", { name: "新建练习" }).click();
  await page.getByLabel("练习名称").fill("旧快照恢复");
  await page.getByLabel("题目数量").fill("2");
  await page.getByRole("button", { name: "开始记录" }).click();
  await page.locator(".question-row").first().getByRole("button", { name: "选择 A" }).click();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出.json" }).click();
  const path = await (await downloaded).path();
  const snapshot = await readFile(path!, "utf8");
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  // Simulate reopening the same saved file while its original state is unchanged.
  await page.route(/\/$/, async (route) => {
    const response = await route.fetch();
    const html = (await response.text()).replace("</head>", `<script id="answer-recorder-state" type="application/json">${snapshot.replaceAll("<", "\\u003c")}</script></head>`);
    await route.fulfill({ response, body: html });
  });
  await page.locator(".question-row").first().getByRole("button", { name: "选择 B" }).click();
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.locator(".save-status")).toHaveText("已保存");
  await page.reload();
  await page.getByRole("button", { name: "继续答题" }).click();
  await expect(page.locator(".question-row").first().getByRole("button", { name: "选择 B" })).toHaveAttribute("aria-pressed", "true");
});
