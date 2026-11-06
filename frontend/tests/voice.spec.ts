import { test, expect } from "@playwright/test";
import fs from "node:fs";
test.use({
  launchOptions: { args: ["--autoplay-policy=no-user-gesture-required"] },
});

test("Gerçek modellerle sanal mikrofon üzerinden randevu", async ({
  page,
  request,
}) => {
  test.skip(
    process.env.REAL_MODELS !== "1",
    "CUDA/STT/LLM ve ayrı kabul sunucusu gerektirir",
  );
  test.setTimeout(300000);
  page.on("pageerror", (e) => console.log("Browser error:", e.message));
  page.on("console", (m) => {
    if (m.type() === "error") console.log("Browser console:", m.text());
  });
  const base = process.env.VOICE_TEST_URL || "http://127.0.0.1:8011";
  const password = fs
    .readFileSync("../.env", "utf8")
    .match(/^ADMIN_PASSWORD=(.*)$/m)![1]
    .trim();
  const headers = {
    Authorization:
      "Basic " + Buffer.from("admin:" + password).toString("base64"),
  };
  const post = async (path: string, data: unknown) => {
    const r = await request.post(base + "/api/" + path, {
      headers,
      data,
      timeout: 180000,
    });
    expect(r.ok(), await r.text()).toBeTruthy();
    return r;
  };
  await post("models/load", {});
  await post("vehicles", {
    description: "Renault Megane",
    plate: "TEST-VOICE",
  });
  await post("slots", {
    starts_at: new Date(Date.now() + 86400000 * 3).toISOString(),
  });
  const wavs = [];
  for (const text of [
    "Benim adım Ali Yılmaz.",
    "Aracım Renault Megane.",
    "Birinci seçenek.",
    "Evet, onaylıyorum.",
  ]) {
    const r = await post("synthesize", { text });
    wavs.push((await r.body()).toString("base64"));
  }
  await page.addInitScript(() => {
    const w = window as any;
    navigator.mediaDevices.getUserMedia = async () => {
      const ac = new AudioContext();
      await ac.resume();
      const dest = ac.createMediaStreamDestination();
      w.injectVoice = async (base64: string) => {
        const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
        const buffer = await ac.decodeAudioData(bytes.buffer);
        const source = ac.createBufferSource();
        source.buffer = buffer;
        source.connect(dest);
        source.start();
        await new Promise<void>((resolve) => {
          source.onended = () => resolve();
        });
      };
      return dest.stream;
    };
  });
  await page.goto(base);
  await page.getByLabel("Yönetici parolası").fill(password);
  await page.getByRole("button", { name: "Panele giriş" }).click();
  await page.getByRole("button", { name: "Mikrofonla görüşme başlat" }).click();
  await page.waitForFunction(
    () =>
      document.querySelector('[role="alert"]') ||
      document.querySelector(".voice .pill")?.textContent === "Dinliyor",
    {},
    { timeout: 90000 },
  );
  expect(await page.getByRole("alert").allTextContents()).toEqual([]);
  await expect(page.locator(".voice .pill")).toHaveText("Dinliyor", {
    timeout: 90000,
  });
  for (let i = 0; i < wavs.length; i++) {
    const before = await page.locator(".bubble.user").count();
    await page.evaluate(async (wav) => {
      await (window as any).injectVoice(wav);
    }, wavs[i]);
    await expect(page.locator(".bubble.user")).toHaveCount(before + 1, {
      timeout: 90000,
    });
    if (i < wavs.length-1) {
      await expect(page.locator(".voice .pill")).toHaveText("Konuşuyor", {
        timeout: 90000,
      });
      await expect(page.locator(".voice .pill")).toHaveText("Dinliyor", {
        timeout: 90000,
      });
    }
  }
  await expect(
    page.getByText(/Randevunuz oluşturuldu\..*İyi günler dilerim\./),
  ).toBeVisible({ timeout: 90000 });
  const r = await request.get(base + "/api/appointments", { headers });
  const records = await r.json();
  expect(records.filter((x: any) => x.status === "confirmed")).toHaveLength(1);
  await page.screenshot({
    path: "../data/voice-acceptance.png",
    fullPage: true,
  });
});
