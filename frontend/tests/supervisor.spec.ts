import { expect, test } from "@playwright/test";

const traceId = "df601e89-4fa4-4031-a533-f8899d753c08";
const conversationId = "a17094ba-0fce-4589-a99e-5df903c394f0";

for (const width of [390, 1440]) {
  test(`Supervisor inceleme paneli ${width}px`, async ({ page }) => {
    let saved: unknown;
    await page.setViewportSize({ width, height: 950 });
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/supervisor/fqici-queue") {
        await route.fulfill({ json: {
          intake_enabled: false, worker_status: "NOT_CONNECTED", physical_sip_status: "HOLD", store: "READY",
          counts: {}, deferred_count: 0, oldest_wait_ms: null, runs: [], deferred: [],
        } });
      } else if (path === "/api/supervisor/quality") {
        await route.fulfill({ json: {
          catalogue_version: "intent-v1", mode: "shadow", trace_store: "READY",
          catalogue: [{ intent_id: "booking_status", domain: "service", description: "Randevu durumu", agent: "ServiceBooking" }],
          registry: { approval_configured: false, fallback_enabled: false },
          evaluation: { baseline: null, xgboost: null, comparable: false },
          software_regression: { status: "NOT RUN" }, physical_regression: "NOT RUN",
          traces: saved ? [] : [{
            trace_id: traceId, conversation_id: conversationId, created_at: "2026-11-10T12:00:00+00:00",
            review_status: "PENDING", review_labels: null, outcome: "legacy_delegated", qa_flags: ["needs_review"],
            decision: {
              route_state: "ROUTED", source: "rule",
              candidates: [{ intent_id: "booking_status", score: null, evidence: "rule.booking_status" }],
              reason_codes: [],
            },
            plan: { priority: "normal", requires_confirmation: false, model_version: "rules-v1",
              policy_version: "policy-v1", steps: [{
                step_id: "booking_status", agent: "ServiceBooking", action: "verify_identity_before_lookup", depends_on: [],
              }] },
          }],
        } });
      } else if (path === `/api/supervisor/review/${traceId}`) {
        saved = route.request().postDataJSON();
        await route.fulfill({ json: { review_status: "EDIT" } });
      } else {
        await route.fulfill({ json: path === "/api/readiness" ? {} : [] });
      }
    });
    await page.goto(process.env.SUPERVISOR_UI_URL ?? "http://127.0.0.1:8000");
    await page.getByLabel("Yönetici parolası").fill("isolated-test");
    await page.getByRole("button", { name: "Panele giriş" }).click();
    await page.getByRole("button", { name: "Supervisor Kalite", exact: true }).click();
    await expect(page.locator("#supervisor-title")).toBeVisible();
    await expect(page.getByText("XGBoost · NOT RUN")).toBeVisible();
    await page.getByText("ROUTED · normal · PENDING").click();
    await expect(page.getByText("ServiceBooking / verify_identity_before_lookup")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.getByRole("button", { name: "İncele", exact: true }).click();
    await page.getByRole("combobox", { name: "Karar", exact: true }).selectOption("EDIT");
    await page.getByRole("button", { name: "Kaydet", exact: true }).click();
    await expect(page.getByText("Bu görünümde karar kaydı yok.")).toBeVisible();
    expect(saved).toEqual({ verdict: "EDIT", labels: ["booking_status"] });
  });
}

for (const width of [390, 1440]) {
  test(`Analiz kuyruğu ile görüşme detayı bağlantısı ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 });
    const start = "2026-11-10T12:00:00+00:00";
    const conversation = { id: conversationId, channel: "asterisk", status: "completed", created_at: start };
    const run = { id: "run", state: "QUEUED", rule_version: "rules-v1", created_at_ms: Date.parse(start),
      attempts: 0, lease_expired: false };
    const source = { transport: "AUDIOSOCKET", origin: "SYNTHETIC" };
    const trace = {
      trace_id: traceId, conversation_id: conversationId, created_at: start,
      review_status: "OBSERVED", review_labels: null, outcome: "legacy_delegated", qa_flags: [],
      decision: { route_state: "ROUTED", source: "rule", candidates: [], reason_codes: [] },
      plan: { priority: "normal", requires_confirmation: false, model_version: "rules-v1",
        policy_version: "policy-v1", steps: [] },
    };
    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      const { pathname } = url;
      if (pathname === "/api/supervisor/fqici-queue") {
        await route.fulfill({ json: {
          intake_enabled: true, worker_status: "NOT_CONNECTED", physical_sip_status: "HOLD",
          store: "READY", counts: { QUEUED: 1 },
          deferred_count: 1, oldest_wait_ms: 91_000,
          runs: [{ ...run, ...source, conversation_id: conversationId }],
          deferred: [{ ...source, conversation_id: conversationId, ready_at_ms: Date.parse(start) }],
        } });
      } else if (pathname === "/api/supervisor/quality") {
        await route.fulfill({ json: {
          catalogue_version: "intent-v1", mode: "shadow", trace_store: "READY", catalogue: [],
          registry: { approval_configured: false, fallback_enabled: false },
          evaluation: { baseline: null, xgboost: null, comparable: false },
          software_regression: { status: "NOT RUN" }, physical_regression: "NOT RUN",
          traces: url.searchParams.get("conversation_id") === conversationId ? [trace] : [],
        } });
      } else if (pathname === `/api/supervisor/conversations/${conversationId}/detail`) {
        await route.fulfill({ json: {
          conversation,
          turns: [{ id: "turn", conversation_id: conversationId, role: "metric",
            text: "", metrics: '{"first_audio_ms":230}', created_at: start }],
          traces: [{ id: traceId, created_at: start, review_status: "OBSERVED", route_state: "ROUTED",
            outcome: "legacy_delegated", intents: ["booking_create"], reason_codes: ["intent.matched"] }],
          transfers: [{ id: "transfer", status: "accepted", created_at: start, completed_at: null }],
          appointment: { id: "appointment-linked", status: "confirmed", starts_at: start },
          fqici: { store: "READY", scope: { ...source, terminal_seen: true, ready_at_ms: null }, runs: [run] },
        } });
      } else {
        await route.fulfill({ json: pathname === "/api/readiness" ? {} :
          pathname === "/api/conversations" ? [conversation] : [] });
      }
    });
    await page.goto(process.env.SUPERVISOR_UI_URL ?? "http://127.0.0.1:8000");
    await page.getByLabel("Yönetici parolası").fill("isolated-test");
    await page.getByRole("button", { name: "Panele giriş" }).click();
    await page.getByRole("button", { name: "Supervisor Kalite", exact: true }).click();
    await expect(page.getByText("1 dk 31 sn")).toBeVisible();
    await expect(page.getByText("bağlı değil", { exact: true })).toBeVisible();
    await page.getByText("Analiz işlerini göster (2)").click();
    await expect(page.getByText("Ertelendi", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: `Görüşmeyi aç ${conversationId}` }).first().click();
    await expect(page.getByRole("heading", { name: "Görüşme detayı" })).toBeVisible();
    await expect(page.getByText("appointment-linked")).toBeVisible();
    await expect(page.getByText("accepted", { exact: false })).toBeVisible();
    await expect(page.getByText("İlk ses (sunucuda hazır)", { exact: false })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.getByRole("button", { name: "Supervisor kararlarını aç" }).click();
    await expect(page.getByRole("textbox", { name: "Görüşme kimliği" })).toHaveValue(conversationId);
    await expect(page.getByText("ROUTED · normal · OBSERVED")).toBeVisible();
  });
}
