import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { POST } from "../app/api/traditional/snapshot/route";

const profile = {
  calendar_type: "solar",
  birth_date: "2000-08-16",
  birth_time: "03:30",
  time_precision: "exact",
  gender: "male",
  birth_place: "山东青岛",
  timezone: "Asia/Shanghai",
  true_solar_time_applied: true,
  focus_topics: ["temperament"],
  interpretation_framework: "comparative_research",
  reference_book_ids: ["di_tian_sui"],
};

const trustedTime = {
  utc_datetime: "2026-08-03T00:00:00Z",
  local_datetime: "2026-08-03T08:00:00+08:00",
  timezone: "Asia/Shanghai",
  source: "network",
  provider: "https_consensus",
  source_url: "https://www.cloudflare.com/,https://www.google.com/generate_204",
  time_proof: `v1.${"a".repeat(64)}`,
  synced: true,
};

function request(body: unknown) {
  return new NextRequest("http://127.0.0.1:3000/api/traditional/snapshot", {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.COUNCIL_BACKEND_URL;
  delete process.env.COUNCIL_INTERNAL_API_TOKEN;
});

describe("traditional snapshot route", () => {
  it("rejects client-supplied derived fields before contacting the backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    process.env.COUNCIL_INTERNAL_API_TOKEN = "server-internal-token-with-at-least-32-characters";

    const response = await POST(request({ ...profile, day_pillar: "伪造日柱" }));

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({ error: { code: "TRADITIONAL_SNAPSHOT_INVALID" } });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns 503 when the local time service fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));
    process.env.COUNCIL_INTERNAL_API_TOKEN = "server-internal-token-with-at-least-32-characters";

    const response = await POST(request(profile));

    expect(response.status).toBe(503);
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("recomputes a schema-v2 snapshot and attaches a server proof", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json(trustedTime));
    vi.stubGlobal("fetch", fetchMock);
    process.env.COUNCIL_INTERNAL_API_TOKEN = "server-internal-token-with-at-least-32-characters";

    const response = await POST(request(profile));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(body).toMatchObject({
      schema_version: 2,
      calculation_source: "local_service",
      profile: { birth_place: "山东青岛", birth_place_normalized: "青岛" },
      timing_facts: { time_provider: "https_consensus", day_pillar: expect.any(String) },
      snapshot_sha256: expect.stringMatching(/^[a-f0-9]{64}$/),
      snapshot_proof: expect.stringMatching(/^v1\.[a-f0-9]{64}$/),
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8001/api/time",
      expect.objectContaining({ cache: "no-store", redirect: "error" }),
    );
  });

  it("refuses a non-loopback backend URL", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    process.env.COUNCIL_INTERNAL_API_TOKEN = "server-internal-token-with-at-least-32-characters";
    process.env.COUNCIL_BACKEND_URL = "https://example.com";

    const response = await POST(request(profile));

    expect(response.status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
