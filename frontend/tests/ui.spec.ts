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

const ALL_TABS = [
  "Görüşme",
  "Operatör (6002)",
  "Araç İçi DSP & Gürültü",
  "Randevular",
  "Sıra & Lift Durumu",
  "A/B Test & İnce Ayar",
  "Analitik & KPI",
  "Ekspertiz Raporları",
  "Teknisyen Dikte",
  "Araç Teşhis & OBD-II",
  "Araçlar ve fiyatlar",
  "Sözlük",
  "Bildirimler",
  "Giden Çağrılar",
  "Geçmiş",
  "Ses laboratuvarı",
  "Sistem",
  "M01–M11",
];
for (const width of [1440, 390]) {
  test(`Tüm sekmeler yatay taşma yapmaz ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("http://127.0.0.1:8000");
    await page.getByLabel("Yönetici parolası").fill(password);
    await page.getByRole("button", { name: "Panele giriş" }).click();
    await expect(page.locator("header h1")).toHaveText("Görüşme");
    for (const title of ALL_TABS) {
      await page.getByRole("button", { name: title, exact: true }).click();
      await expect(page.locator("header h1")).toHaveText(title);
      // Tembel yüklenen panelin yerleşmesi için kısa bekleme.
      await page.waitForLoadState("networkidle");
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        `${title} sekmesi ${width}px genişlikte yatay taşıyor`,
      ).toBeTruthy();
    }
  });
}

test("Yanlış parola Türkçe hata gösterir", async ({ page }) => {
  await page.goto("http://127.0.0.1:8000");
  await page.getByLabel("Yönetici parolası").fill(password + "-yanlis");
  await page.getByRole("button", { name: "Panele giriş" }).click();
  await expect(page.getByRole("alert")).toContainText("Parola hatalı");
  await expect(page.getByLabel("Yönetici parolası")).toBeVisible();
});

test("Çıkış giriş ekranına döner ve parolayı temizler", async ({ page }) => {
  await page.goto("http://127.0.0.1:8000");
  await page.getByLabel("Yönetici parolası").fill(password);
  await page.getByRole("button", { name: "Panele giriş" }).click();
  await expect(page.locator("header h1")).toHaveText("Görüşme");
  await page.getByRole("button", { name: "Çıkış", exact: true }).click();
  await expect(page.getByLabel("Yönetici parolası")).toBeVisible();
  await expect(page.getByLabel("Yönetici parolası")).toHaveValue("");
});
