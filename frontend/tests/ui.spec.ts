import { test, expect } from "@playwright/test";
import fs from "node:fs";

// V3 sidebar uses menuitems and user-facing labels, not internal tab IDs.
// Keep expected labels explicit so a removed navigation item fails the test.
const TAB_LABELS: Record<string, string> = {
  "Görüşme": "Görüşme Kokpiti",
  "Randevular": "Randevu Takvimi",
  "Araçlar ve fiyatlar": "Araç Kataloğu & Fiyatlar",
  "Geçmiş": "Görüşme Geçmişi",
  "Ses laboratuvarı": "Ses Laboratuvarı",
  "Sistem": "Sistem & Donanım Sağlığı",
  "M01–M11": "M01–M11 Kalite Kapıları",
  "Operatör (6002)": "Operatör Kokpiti (6002)",
  "Giden Çağrılar": "Giden Çağrılar (Outbound)",
  "A/B Test & İnce Ayar": "A/B Test & ASR Ayarı",
  "Sözlük": "Sözlük & Fonetik",
  "Supervisor Kalite": "Supervisor & FQICI",
  "Bildirimler": "Bildirimler & WhatsApp",
};

function navItem(page: import("@playwright/test").Page, title: string) {
  return page.getByRole("menuitem", { name: TAB_LABELS[title] ?? title, exact: true });
}

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
      await navItem(page, title).click();
      await expect(
        page.getByRole("heading", { name: title, exact: true }),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBeTruthy();
    }
    await navItem(page, "M01–M11").click();
    await expect(page.getByText("Toplam gecikme: — (ölçüm yok)", { exact: true })).toBeVisible();
    await expect(page.getByText(/SİMÜLASYON.*sunucu politikasını değiştirmez/)).toBeVisible();
    await page.getByRole("textbox", { name: "Sözleşme metni", exact: true }).scrollIntoViewIfNeeded();
    await page.getByRole("textbox", { name: "Sözleşme metni", exact: true }).fill("Volkswagen Passat için tahmini değer 1.250.000 TL.");
    await page.getByRole("button", { name: "Sözleşmeyi İncele", exact: true }).click({ timeout: 5000 });
    await expect(page.getByTestId("contract-normalized-text")).toContainText(
      "bir milyon iki yüz elli bin",
    );
    await page.screenshot({
      path: `../data/milestones-ui-${width}.png`,
      fullPage: true,
    });
    await navItem(page, "Ses laboratuvarı").click();
    await page.getByRole("textbox", { name: "Sentez metni", exact: true }).scrollIntoViewIfNeeded();
    await page.getByRole("textbox", { name: "Sentez metni", exact: true }).fill("Volkswagen Passat için tahmini değer 1.250.000 TL.");
    await page.getByRole("button", { name: "Normalizasyonu İncele", exact: true }).scrollIntoViewIfNeeded({ timeout: 5000 });
    await page.getByRole("button", { name: "Normalizasyonu İncele", exact: true }).click({ timeout: 5000 });
    await expect(page.getByTestId("lab-normalized-text")).toContainText(
      "bir milyon iki yüz elli bin",
    );
    await page.screenshot({ path: `../data/ui-${width}.png`, fullPage: true });
  });
}

const ALL_TABS = [
  "Görüşme",
  "Randevular",
  "Sıra & Lift Durumu",
  "Ekspertiz Raporları",
  "Araçlar ve fiyatlar",
  "Teknisyen Dikte",
  "Araç Teşhis & OBD-II",
  "Bildirimler",
  "Geçmiş",
  "Operatör (6002)",
  "Giden Çağrılar",
  "Araç İçi DSP & Gürültü",
  "A/B Test & İnce Ayar",
  "Sözlük",
  "Otomotiv Ontolojisi",
  "Ses laboratuvarı",
  "Supervisor Kalite",
  "Analitik & KPI",
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
      await navItem(page, title).click();
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

test("İlk randevu rehberi panelden ilk randevuyu yönlendirir ve takvime bağlar", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("http://127.0.0.1:8000");
  await page.getByLabel("Yönetici parolası").fill(password);
  await page.getByRole("button", { name: "Panele giriş" }).click();

  // 1. İlk Randevu Kurulum Rehberinin 'Bir randevu ile başlayın' metniyle açıldığını doğrula
  await expect(page.getByText("Bir randevu ile başlayın.")).toBeVisible();
  await expect(page.getByText("İlk Randevu Kurulum Rehberi")).toBeVisible();

  // 2. Beş aşamalı rehber adımları görünür
  await expect(page.getByText("1. MODELLERİ HAZIRLA")).toBeVisible();
  await expect(page.getByText("2. ARAÇ & FİYAT TANIMLA")).toBeVisible();
  await expect(page.getByText("3. MÜSAİT SAAT EKLE")).toBeVisible();
  await expect(page.getByText("4. GÖRÜŞMEYİ BAŞLAT")).toBeVisible();
  await expect(page.getByText("5. RANDEVUYU AÇ")).toBeVisible();

  // 3. Rehber üzerinden Randevular sekmesine geçiş
  await navItem(page, "Randevular").click();
  await expect(page.getByRole("heading", { name: "Randevular", exact: true })).toBeVisible();
  await expect(page.getByText("Randevu Takvimi & Planlama")).toBeVisible();
});
