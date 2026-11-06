import { test, expect } from "@playwright/test";
import fs from "node:fs";
const password = fs
  .readFileSync("../.env", "utf8")
  .match(/^ADMIN_PASSWORD=(.*)$/m)![1]
  .trim();
for (const width of [1440, 390]) {
  test(`Yönetim ekranları ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("http://127.0.0.1:8000");
    await page.getByLabel("Yönetici parolası").fill(password);
    await page.getByRole("button", { name: "Panele giriş" }).click();
    await expect(
      page.getByRole("heading", { name: "Görüşme", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Bir randevu ile başlayın.")).toBeVisible();
    for (const title of [
      "Randevular",
      "Araçlar ve fiyatlar",
      "Geçmiş",
      "Ses laboratuvarı",
      "Sistem",
      "M01–M11",
    ]) {
      await page.getByRole("button", { name: title, exact: true }).click();
      await expect(
        page.getByRole("heading", { name: title, exact: true }),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBeTruthy();
    }
    await page.getByRole("button", { name: "M01–M11", exact: true }).click();
    await page.getByRole("button", { name: "Sözleşmeyi incele" }).click();
    await expect(page.locator(".bubble")).toContainText(
      "bir milyon iki yüz elli bin",
    );
    await page.screenshot({
      path: `../data/milestones-ui-${width}.png`,
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Ses laboratuvarı", exact: true })
      .click();
    await page.getByRole("button", { name: "Normalizasyonu incele" }).click();
    await expect(page.locator(".bubble")).toContainText(
      "bir milyon iki yüz elli bin",
    );
    await page.screenshot({ path: `../data/ui-${width}.png`, fullPage: true });
  });
}
