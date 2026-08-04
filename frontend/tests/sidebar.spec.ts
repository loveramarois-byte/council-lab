import { expect, test } from "@playwright/test";


test("desktop sidebar resizes, collapses without compression, and persists", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => window.localStorage.clear());
  await page.reload();

  const sidebar = page.locator(".sidebar");
  await expect(sidebar).toHaveCSS("width", "238px");
  await page.getByRole("button", { name: "收窄侧边栏" }).click();
  await expect(sidebar).toHaveCSS("width", "76px");
  await expect(page.locator(".brand-mark")).toHaveCSS("width", "28px");

  await page.getByRole("button", { name: "展开侧边栏" }).click();
  const resizeHandle = page.getByRole("separator", { name: "调整侧边栏宽度" });
  await resizeHandle.focus();
  await page.keyboard.press("Home");
  await expect(sidebar).toHaveCSS("width", "190px");
  await expect(resizeHandle).toHaveAttribute("aria-valuenow", "190");

  await page.reload();
  await expect(sidebar).toHaveCSS("width", "190px");
  await expect(page.getByRole("button", { name: "收窄侧边栏" })).toBeVisible();
  await expect(page.getByText("工作区", { exact: true })).toHaveCount(0);
});


test("mobile navigation ignores the desktop collapsed preference", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.evaluate(() => window.localStorage.setItem("council.sidebar.collapsed", "true"));
  await page.reload();

  await page.getByRole("button", { name: "打开导航" }).click();
  const sidebar = page.locator(".sidebar");
  await expect(sidebar).toHaveCSS("width", "286px");
  await expect(page.getByRole("link", { name: "新建审议" })).toBeVisible();
  await expect(page.getByRole("link", { name: "设置" })).toBeVisible();
  await expect(page.getByRole("button", { name: "收窄侧边栏" })).toBeHidden();
});
