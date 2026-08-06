import { afterEach, describe, expect, it } from "vitest";

import { GET } from "../app/mobile-access/health/route";


const originalDesktopToken = process.env.COUNCIL_DESKTOP_TOKEN;

afterEach(() => {
  if (originalDesktopToken === undefined) delete process.env.COUNCIL_DESKTOP_TOKEN;
  else process.env.COUNCIL_DESKTOP_TOKEN = originalDesktopToken;
});


describe("desktop session health identity", () => {
  it("exposes only a one-way token identifier so launchers can reject stale frontends", async () => {
    process.env.COUNCIL_DESKTOP_TOKEN = "desktop-session-token-with-at-least-32-characters";

    const response = await GET();
    const identifier = response.headers.get("X-Council-Desktop-Token-ID");

    expect(identifier).toMatch(/^[a-f0-9]{16}$/);
    expect(identifier).not.toContain(process.env.COUNCIL_DESKTOP_TOKEN);
  });
});
