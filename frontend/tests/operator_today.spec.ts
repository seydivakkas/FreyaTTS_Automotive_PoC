import { expect, test } from "@playwright/test";

const id = "42842cf0-81ca-444b-aea0-859ec445e381";
const transferId = "70179a1b-cef8-4192-904e-49e0a588a120";
const since = "2026-11-10T12:00:00+00:00";

for (const width of [390, 1440]) {
  test(`Operatör Bugün, devreden iş ve kayıt bağlantıları ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const conversation = { id, channel: "web", status: "follow_up", created_at: since };
    const callback = { id, conversation_id: id, kind: "callback", since, since_source: "follow_up",
      period: "carryover", age_seconds: 90000 };
    const transfer = { id: transferId, conversation_id: null, kind: "transfer", since, since_source: "transfer",
      period: "today", age_seconds: 4 };
    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === "/api/operator/today") {
        const items = url.searchParams.get("period") === "carryover" ? [callback] : [transfer, callback];
        await route.fulfill({ json: { local_date: "2026-11-11", counts: { transfer: 1, callback: 1 },
          total: items.length, items } });
      } else if (url.pathname === `/api/transfers/${transferId}`) {
        await route.fulfill({ json: { id: transferId, status: "whispering", sip_headers: {},
          caller_channel: "test", customer_name: "", vehicle_plate: "", whisper_text: "" } });
      } else if (url.pathname === `/api/supervisor/conversations/${id}/detail`) {
        await route.fulfill({ json: {
          conversation, turns: [], traces: [], transfers: [], appointment: null,
          fqici: { store: "READY", scope: null, runs: [] },
        } });
      } else {
        await route.fulfill({ json: url.pathname === "/api/readiness" ? {} :
          url.pathname === "/api/conversations" ? [conversation] : [] });
      }
    });
    await page.goto(process.env.SUPERVISOR_UI_URL ?? "http://127.0.0.1:8000");
    await page.getByLabel("Yönetici parolası").fill("isolated-test");
    await page.getByRole("button", { name: "Panele giriş" }).click();
    await page.getByRole("button", { name: "Operatör (6002)", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Bugün", exact: true })).toBeVisible();
    await expect(page.getByText("Devreden · Bekleme 1 gün 1 sa", { exact: false })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.getByRole("button", { name: "Aktarımı aç", exact: true }).click();
    await expect(page.getByText(`Aktarım Detayları: ${transferId}`, { exact: false })).toBeVisible();
    await page.keyboard.press("Escape");
    await page.getByRole("combobox", { name: "Dönem", exact: true }).selectOption("carryover");
    await expect(page.getByRole("button", { name: "Aktarımı aç", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Görüşmeyi aç", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Görüşme detayı" })).toBeVisible();
    await expect(page.getByText(id, { exact: true })).toBeVisible();
  });
}
