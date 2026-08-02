import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildTraditionalCultureSnapshot, TRADITIONAL_REFERENCE_BOOKS, TRADITIONAL_RULE_PROFILES } from "./traditional-culture";


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
    expect(snapshot.snapshot_sha256).toBe("1a46c686e3d19434811ebe9c4b7927c81667d6c6268207f2773a9560430f6c59");
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
});
