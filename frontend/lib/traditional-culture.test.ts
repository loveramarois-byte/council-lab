import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildTraditionalCultureSnapshot, TRADITIONAL_REFERENCE_BOOKS, TRADITIONAL_RULE_PROFILES } from "./traditional-culture";
import { resolveTraditionalLocation } from "./traditional-locations";


describe("traditional culture local calculation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-02T00:00:00.000Z"));
  });

  afterEach(() => vi.useRealTimers());

  it("freezes the reviewed sample and canonical digest", async () => {
    const snapshot = await buildTraditionalCultureSnapshot({
      calendar_type: "solar",
      birth_date: "2000-08-16",
      birth_time: "03:30",
      time_precision: "exact",
      gender: "male",
      birth_place: "",
      timezone: "Asia/Shanghai",
      true_solar_time_applied: false,
      focus_topics: ["temperament"],
    });

    expect(snapshot.calendar_facts.eight_char).toBe("庚辰 甲申 丙午 庚寅");
    expect(snapshot.ziwei_chart).toMatchObject({ five_elements_class: "木三局", soul_star: "破军", body_star: "文昌" });
    expect(snapshot.ziwei_chart.palaces).toHaveLength(12);
    expect(snapshot.profile.interpretation_framework).toBe("comparative_research");
    expect(snapshot.engines.map((engine) => `${engine.id}@${engine.version}`)).toEqual(["lunar-javascript@1.7.7", "iztro@2.5.8"]);
    expect(snapshot.snapshot_sha256).toBe("834a9b05215734c27c5bc5530ddd6eaf54be59c154854580356feaabca162b5a");
  });

  it("records selected reference-book metadata without bundling source text", async () => {
    const snapshot = await buildTraditionalCultureSnapshot({
      calendar_type: "solar",
      birth_date: "2000-08-16",
      birth_time: "03:30",
      time_precision: "exact",
      gender: "male",
      birth_place: "",
      timezone: "Asia/Shanghai",
      true_solar_time_applied: false,
      focus_topics: ["temperament"],
      interpretation_framework: "bazi_classical",
      reference_book_ids: ["di_tian_sui", "zhou_yi"],
    });

    expect(snapshot.profile.reference_book_ids).toEqual(["di_tian_sui", "zhou_yi"]);
    expect(snapshot.profile.interpretation_framework).toBe("bazi_classical");
    expect(TRADITIONAL_RULE_PROFILES.find((item) => item.id === "bazi_classical")).toMatchObject({ label: "八字规则优先" });
    expect(TRADITIONAL_REFERENCE_BOOKS.find((item) => item.id === "di_tian_sui")).toMatchObject({
      focus: "论五行旺衰",
      source: { level: "upstream_summary", label: "上游规则摘要", url: expect.stringContaining("bdd7f863d4450bf0e2fac84579ad6b45cfdfa25c") },
    });
    expect(TRADITIONAL_REFERENCE_BOOKS.find((item) => item.id === "zhou_yi")?.source).toMatchObject({ level: "index_only", label: "仅索引" });
    expect(TRADITIONAL_REFERENCE_BOOKS.find((item) => item.id === "ziwei_doushu_quan_shu")?.source).toMatchObject({ level: "upstream_excerpt", label: "上游精选片段" });
    expect(JSON.stringify(snapshot)).not.toContain("原文");
  });

  it("resolves Shandong Qingdao and freezes true-solar and current timing fields", async () => {
    const snapshot = await buildTraditionalCultureSnapshot({
      calendar_type: "solar",
      birth_date: "1995-04-27",
      birth_time: "11:45",
      time_precision: "exact",
      gender: "male",
      birth_place: "山东青岛",
      timezone: "Asia/Shanghai",
      true_solar_time_applied: true,
      focus_topics: ["timing"],
      interpretation_framework: "comparative_research",
      reference_book_ids: [],
    }, {
      utc_datetime: "2026-08-03T00:00:00Z",
      local_datetime: "2026-08-03T08:00:00+08:00",
      timezone: "Asia/Shanghai",
      source: "network",
      provider: "https_consensus",
      source_url: "https://www.cloudflare.com/,https://www.google.com/generate_204",
      synced: true,
    });

    expect(snapshot.schema_version).toBe(2);
    expect(snapshot.profile).toMatchObject({
      birth_place: "山东青岛",
      birth_place_normalized: "青岛",
      birth_latitude: 36.0671,
      birth_longitude: 120.3826,
      birth_place_source: "offline_city_catalog",
      true_solar_time_applied: true,
    });
    expect(snapshot.calendar_facts).toMatchObject({
      civil_solar_datetime: "1995-04-27 11:45:00",
      true_solar_datetime: "1995-04-27 11:49:00",
      true_solar_time_offset_minutes: 4,
    });
    expect(snapshot.calendar_facts.pillars[2]).toBeTruthy();
    expect(snapshot.calendar_facts.pillars[3]).toBeTruthy();
    expect(snapshot.timing_facts).toMatchObject({
      reference_civil_datetime: "2026-08-03 08:00:00",
      reference_true_solar_datetime: "2026-08-03 07:56:00",
      time_source: "network",
      time_provider: "https_consensus",
      year_pillar: "丙午",
      month_pillar: "乙未",
      day_pillar: "己酉",
      hour_pillar: "戊辰",
      previous_solar_term: { name: "大暑", datetime: "2026-07-23 03:13:05" },
      next_solar_term: { name: "立秋", datetime: "2026-08-07 19:42:43" },
    });
  });

  it("keeps the snapshot digest stable when only the server time proof changes", async () => {
    const profile = {
      calendar_type: "solar" as const,
      birth_date: "1995-04-27",
      birth_time: "11:45",
      time_precision: "exact" as const,
      gender: "male" as const,
      birth_place: "山东青岛",
      timezone: "Asia/Shanghai" as const,
      true_solar_time_applied: true,
      focus_topics: ["timing" as const],
    };
    const trustedTime = {
      utc_datetime: "2026-08-03T00:00:00Z",
      local_datetime: "2026-08-03T08:00:00+08:00",
      timezone: "Asia/Shanghai" as const,
      source: "network" as const,
      provider: "https_consensus" as const,
      source_url: "https://www.cloudflare.com/,https://www.google.com/generate_204",
      synced: true,
    };
    const first = await buildTraditionalCultureSnapshot(profile, { ...trustedTime, time_proof: `v1.${"a".repeat(64)}` });
    const second = await buildTraditionalCultureSnapshot(profile, { ...trustedTime, time_proof: `v1.${"b".repeat(64)}` });

    expect(first.timing_facts?.time_proof).not.toBe(second.timing_facts?.time_proof);
    expect(first.snapshot_sha256).toBe(second.snapshot_sha256);
  });

  it.each([
    ["青岛", "青岛"],
    ["青岛市", "青岛"],
    ["山东青岛", "青岛"],
    ["山东省青岛市", "青岛"],
  ])("resolves only structured city input %s", (input, expected) => {
    expect(resolveTraditionalLocation(input)?.name).toBe(expected);
  });

  it.each(["不在北京", "南京路", "我住在山东青岛附近", "广东青岛"])(
    "does not infer a city from ambiguous free-form input %s",
    (input) => {
      expect(resolveTraditionalLocation(input)).toBeNull();
    },
  );
});
