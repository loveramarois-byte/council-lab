import { describe, expect, it } from "vitest";
import {
  localBackendUrl,
  parseTraditionalProfile,
  parseTrustedTime,
  snapshotProofFor,
} from "./traditional-snapshot-server";
import type { TraditionalCultureSnapshot } from "./api";

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

describe("traditional snapshot server boundary", () => {
  it("accepts raw profile fields and rejects client-supplied derived coordinates", () => {
    expect(parseTraditionalProfile(profile).birth_place).toBe("山东青岛");
    expect(() => parseTraditionalProfile({ ...profile, birth_longitude: 0 })).toThrow("未知字段");
  });

  it("accepts only consensus network time or an explicit local fallback", () => {
    expect(parseTrustedTime({
      utc_datetime: "2026-08-03T00:00:00Z",
      local_datetime: "2026-08-03T08:00:00+08:00",
      timezone: "Asia/Shanghai",
      source: "network",
      provider: "https_consensus",
      source_url: "https://www.cloudflare.com/,https://www.google.com/generate_204",
      time_proof: `v1.${"a".repeat(64)}`,
      synced: true,
    }).synced).toBe(true);
    expect(() => parseTrustedTime({ ...profile, source: "network", provider: "timeapi.io", synced: true })).toThrow("来源无效");
  });

  it("binds the server proof to the snapshot hash and rejects remote backend URLs", () => {
    const snapshot = { snapshot_sha256: "a".repeat(64), timing_facts: { time_proof: `v1.${"b".repeat(64)}` } } as TraditionalCultureSnapshot;
    const secret = "server-internal-token-with-at-least-32-characters";
    expect(snapshotProofFor(snapshot, secret)).not.toBe(snapshotProofFor({ ...snapshot, snapshot_sha256: "c".repeat(64) }, secret));
    expect(localBackendUrl("http://127.0.0.1:8001/path")).toBe("http://127.0.0.1:8001");
    expect(() => localBackendUrl("https://example.com")).toThrow("只允许连接本机后端");
  });
});
