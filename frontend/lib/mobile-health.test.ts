import { afterEach, describe, expect, it } from "vitest";

import { GET } from "../app/mobile-access/health/route";


const originalRuntimeId = process.env.COUNCIL_RUNTIME_ID;
const originalWebBuildId = process.env.COUNCIL_WEB_BUILD_ID;
const originalInternalToken = process.env.COUNCIL_INTERNAL_API_TOKEN;

afterEach(() => {
  if (originalRuntimeId === undefined) delete process.env.COUNCIL_RUNTIME_ID;
  else process.env.COUNCIL_RUNTIME_ID = originalRuntimeId;
  if (originalWebBuildId === undefined) delete process.env.COUNCIL_WEB_BUILD_ID;
  else process.env.COUNCIL_WEB_BUILD_ID = originalWebBuildId;
  if (originalInternalToken === undefined) delete process.env.COUNCIL_INTERNAL_API_TOKEN;
  else process.env.COUNCIL_INTERNAL_API_TOKEN = originalInternalToken;
});


describe("mobile access health", () => {
  it("reports the current packaged runtime without allowing cached identity", async () => {
    process.env.COUNCIL_RUNTIME_ID = "macos:install-123";
    process.env.COUNCIL_WEB_BUILD_ID = "next-build-456";
    process.env.COUNCIL_INTERNAL_API_TOKEN = "server-internal-token-with-at-least-32-characters";
    const response = await GET();

    expect(await response.json()).toEqual({
      status: "ok",
      service: "council-mobile-access",
      runtime_id: "macos:install-123",
      web_build_id: "next-build-456",
      internal_api_id: "e90cee8a30ea5176",
    });
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });

  it("labels source mode as development when no runtime identity is set", async () => {
    delete process.env.COUNCIL_RUNTIME_ID;
    delete process.env.COUNCIL_WEB_BUILD_ID;
    delete process.env.COUNCIL_INTERNAL_API_TOKEN;
    const response = await GET();
    expect(await response.json()).toMatchObject({
      runtime_id: "development",
      web_build_id: "unknown",
      internal_api_id: "unconfigured",
    });
  });
});
