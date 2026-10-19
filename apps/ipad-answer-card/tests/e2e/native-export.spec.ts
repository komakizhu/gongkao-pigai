import { expect, test } from "@playwright/test";

test.use({ serviceWorkers: "block" });

test("compact export hides raw content and unavailable sharing while copying the whole attempt", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "canShare", { value: () => false });
    Object.defineProperty(navigator, "clipboard", { value: { writeText: async (text: string) => { (window as unknown as { copied: string }).copied = text; } } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "新建练习" }).click();
  await page.getByLabel("练习名称").fill("00国考行测");
  await page.getByLabel("题目数量").fill("100");
  await page.getByRole("button", { name: "开始记录" }).click();
  await page.locator(".question-row").last().getByRole("button", { name: "选择 D" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出.json" }).click();
  expect((await download).suggestedFilename()).toBe("00国考行测.json");
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator("#transfer-text")).not.toBeVisible();
  await expect(dialog.locator('[data-transfer="share"]')).not.toBeVisible();
  await expect(dialog.locator(".transfer-summary")).toHaveText("100 题 · 1 已答");
  await expect(dialog).not.toContainText("字节");
  await dialog.getByRole("button", { name: "复制", exact: true }).click();
  await expect(dialog.locator(".transfer-message")).toHaveText("已复制");
  const copied = JSON.parse(await page.evaluate(() => (window as unknown as { copied: string }).copied));
  expect(copied.exercise.questions).toHaveLength(100);
  expect(copied.exercise.questions[99].answer).toBe("D");
  await expect(dialog.locator("#transfer-text")).not.toBeVisible();
  await dialog.getByText("查看原文", { exact: true }).click();
  await expect(dialog.locator("#transfer-text")).toBeVisible();
  expect(JSON.parse(await dialog.locator("#transfer-text").inputValue()).exercise.questions).toHaveLength(100);
  await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".question-row").last().getByRole("button", { name: "选择 D" })).toHaveAttribute("aria-pressed", "true");
});

test("exports every question as a real JSON or CSV file through native sharing", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "canShare", { value: (data: ShareData) => Boolean(data.files?.length) });
    Object.defineProperty(navigator, "share", { value: (data: ShareData) => {
      const activated = navigator.userActivation.isActive;
      return Promise.all(data.files!.map(async (file) => ({ name: file.name, type: file.type, text: await file.text(), activated }))).then((files) => {
        (window as unknown as { shared: unknown }).shared = files[0];
      });
    } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "新建练习" }).click();
  await page.getByLabel("练习名称").fill("系统文件导出");
  await page.getByLabel("题目数量").fill("100");
  await page.getByRole("button", { name: "开始记录" }).click();
  await page.locator(".question-row").last().getByRole("button", { name: "选择 D" }).click();
  await page.getByRole("button", { name: "导出.json" }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { shared?: { name: string } }).shared?.name)).toBe("系统文件导出.json");
  const json = await page.evaluate(() => (window as unknown as { shared: { text: string; type: string; activated: boolean } }).shared);
  expect(json.type).toBe("application/json");
  expect(json.activated).toBe(true);
  expect(JSON.parse(json.text).exercise.questions).toHaveLength(100);
  expect(JSON.parse(json.text).exercise.questions[99].answer).toBe("D");
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("button", { name: "导出.csv" }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { shared?: { name: string } }).shared?.name)).toBe("系统文件导出.csv");
  const csv = await page.evaluate(() => (window as unknown as { shared: { text: string } }).shared.text);
  expect(csv.trim().split(/\r?\n/)).toHaveLength(101);
  expect(csv).toContain(",100,single,D,true");
});

for (const errorName of ["AbortError", "NotAllowedError"]) {
  test(`keeps the full record available when native sharing returns ${errorName}`, async ({ page }) => {
    await page.addInitScript((name) => {
      Object.defineProperty(navigator, "canShare", { value: () => true });
      Object.defineProperty(navigator, "share", { value: () => Promise.reject(new DOMException("Viewer", name)) });
    }, errorName);
    await page.goto("/");
    await page.getByRole("button", { name: "新建练习" }).click();
    await page.getByLabel("练习名称").fill("分享失败保护");
    await page.getByRole("button", { name: "开始记录" }).click();
    await page.locator(".question-row").first().getByRole("button", { name: "选择 C" }).click();
    await page.getByRole("button", { name: "导出.json" }).click();
    await expect(page.locator(".transfer-message")).toContainText(errorName === "AbortError" ? "已取消" : "未完成");
    const json = JSON.parse(await page.locator("#transfer-text").inputValue());
    expect(json.exercise.questions[0].answer).toBe("C");
    const downloaded = page.waitForEvent("download");
    await page.getByRole("link", { name: "下载", exact: true }).click();
    expect((await downloaded).suggestedFilename()).toBe("分享失败保护.json");
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    await expect(page.locator(".question-row").first().getByRole("button", { name: "选择 C" })).toHaveAttribute("aria-pressed", "true");
  });
}

test("blocked clipboard reveals selected full text for manual recovery", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "canShare", { value: () => false });
    Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.reject(new DOMException("Blocked", "NotAllowedError")) } });
    Object.defineProperty(document, "execCommand", { value: () => false });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "新建练习" }).click();
  await page.getByLabel("练习名称").fill("复制备用");
  await page.getByRole("button", { name: "开始记录" }).click();
  await page.locator(".question-row").first().getByRole("button", { name: "选择 C" }).click();
  await page.getByRole("button", { name: "导出.json" }).click();
  await page.getByRole("button", { name: "复制", exact: true }).click();
  await expect(page.locator(".transfer-message")).toHaveText("请长按已选文本复制。");
  await expect(page.locator("#transfer-text")).toBeVisible();
  const selection = await page.locator("#transfer-text").evaluate((element: HTMLTextAreaElement) => ({ start: element.selectionStart, end: element.selectionEnd, length: element.value.length, firstAnswer: JSON.parse(element.value).exercise.questions[0].answer }));
  expect(selection.start).toBe(0);
  expect(selection.end).toBe(selection.length);
  expect(selection.firstAnswer).toBe("C");
});
