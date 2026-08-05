import { expect, test } from "@playwright/test";


test("mobile navigation closes with Escape and restores menu focus", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const menuButton = page.getByRole("button", { name: "打开导航" });
  await menuButton.click();
  await expect(page.getByRole("button", { name: "关闭导航" }).last()).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(page.locator(".sidebar")).not.toHaveClass(/sidebar-open/);
  await expect(menuButton).toBeFocused();
});
