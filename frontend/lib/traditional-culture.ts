import { sha256 as nobleSha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { astro } from "iztro";
import { Solar } from "lunar-javascript";
import type { TraditionalCultureProfile, TraditionalCultureSnapshot } from "./api";

const ENGINE_METADATA = [
  { id: "lunar-javascript" as const, version: "1.7.7", source_url: "https://github.com/6tail/lunar-javascript", license: "MIT" as const },
  { id: "iztro" as const, version: "2.5.8", source_url: "https://github.com/SylarLong/iztro", license: "MIT" as const },
];

const NOTICES = [
  "排盘由版本化本地开源引擎计算，不会调用第三方命理 API。",
  "传统文化解释不属于科学验证，不得作为医疗、法律、投资、合规或生产决策依据。",
  "当前按 Asia/Shanghai 民用时计算，未应用真太阳时校正；临界时刻可能因流派口径产生不同结果。",
  "ziwei-doushu 的开源实现依赖 iztro 与 lunar-javascript，共享底层结果不能视为独立交叉验证。",
];

function canonicalize(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalize(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function sha256(value: unknown) {
  const bytes = new TextEncoder().encode(canonicalize(value));
  return bytesToHex(nobleSha256(bytes));
}

function timeIndexFor(hour: number) {
  return hour === 23 ? 0 : Math.floor((hour + 1) / 2) % 12;
}

function starLabel(star: { name: string; brightness?: string; mutagen?: string }) {
  const suffix = [star.brightness, star.mutagen ? `化${star.mutagen}` : ""].filter(Boolean).join("·");
  return suffix ? `${star.name}（${suffix}）` : star.name;
}

export async function buildTraditionalCultureSnapshot(profile: TraditionalCultureProfile): Promise<TraditionalCultureSnapshot> {
  const [yearText, monthText, dayText] = profile.birth_date.split("-");
  const [hourText, minuteText] = profile.birth_time.split(":");
  const [year, month, day, hour, minute] = [yearText, monthText, dayText, hourText, minuteText].map(Number);
  const calendarDate = Solar.fromYmdHms(year, month, day, hour, minute, 0);
  const lunarDate = calendarDate.getLunar();
  const eightChar = lunarDate.getEightChar();
  const chart = astro.bySolar(`${year}-${month}-${day}`, timeIndexFor(hour), profile.gender === "male" ? "男" : "女", true, "zh-CN");
  const calculatedAt = new Date(Math.floor(Date.now() / 1000) * 1000).toISOString().replace(".000Z", "Z");
  const normalizedProfile = { ...profile, birth_place: profile.birth_place.trim() };
  const snapshotWithoutHash = {
    schema_version: 1 as const,
    calculation_source: "local_browser" as const,
    calculated_at: calculatedAt,
    profile: normalizedProfile,
    engines: ENGINE_METADATA,
    calendar_facts: {
      solar_datetime: calendarDate.toYmdHms(),
      lunar_date: lunarDate.toString(),
      zodiac: lunarDate.getYearShengXiao(),
      constellation: calendarDate.getXingZuo(),
      eight_char: eightChar.toString(),
      pillars: [eightChar.getYear(), eightChar.getMonth(), eightChar.getDay(), eightChar.getTime()],
      pillar_wuxing: [eightChar.getYearWuXing(), eightChar.getMonthWuXing(), eightChar.getDayWuXing(), eightChar.getTimeWuXing()],
      heavenly_stem_ten_gods: [eightChar.getYearShiShenGan(), eightChar.getMonthShiShenGan(), eightChar.getDayShiShenGan(), eightChar.getTimeShiShenGan()],
    },
    ziwei_chart: {
      solar_date: chart.solarDate,
      lunar_date: chart.lunarDate,
      chinese_date: chart.chineseDate,
      time_label: chart.time,
      time_range: chart.timeRange,
      five_elements_class: chart.fiveElementsClass,
      soul_star: chart.soul,
      body_star: chart.body,
      soul_palace_branch: chart.earthlyBranchOfSoulPalace,
      body_palace_branch: chart.earthlyBranchOfBodyPalace,
      palaces: chart.palaces.map((palace) => ({
        index: palace.index,
        name: palace.name,
        heavenly_stem: palace.heavenlyStem,
        earthly_branch: palace.earthlyBranch,
        is_body_palace: palace.isBodyPalace,
        is_original_palace: palace.isOriginalPalace,
        major_stars: palace.majorStars.map(starLabel),
        minor_stars: palace.minorStars.map(starLabel),
        changsheng12: palace.changsheng12,
        decadal_range: palace.decadal.range,
      })),
    },
    notices: NOTICES,
  };
  return { ...snapshotWithoutHash, snapshot_sha256: sha256(snapshotWithoutHash) };
}
