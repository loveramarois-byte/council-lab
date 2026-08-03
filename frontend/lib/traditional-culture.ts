import { sha256 as nobleSha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { astro } from "iztro";
import { Solar } from "lunar-javascript";
import type { TraditionalCultureProfile, TraditionalCultureReferenceId, TraditionalCultureSnapshot, TraditionalInterpretationFramework, TrustedTime } from "./api";
import { resolveTraditionalLocation } from "./traditional-locations";

const ENGINE_METADATA = [
  { id: "lunar-javascript" as const, version: "1.7.7", source_url: "https://github.com/6tail/lunar-javascript", license: "MIT" as const },
  { id: "iztro" as const, version: "2.5.8", source_url: "https://github.com/SylarLong/iztro", license: "MIT" as const },
];

export const TRADITIONAL_RULE_PROFILES: {
  id: TraditionalInterpretationFramework;
  label: string;
  description: string;
}[] = [
  { id: "comparative_research", label: "比较研读（八字 + 紫微）", description: "两套体系并列解释并标出冲突" },
  { id: "bazi_classical", label: "八字规则优先", description: "四柱、五行和十神为主，紫微作对照" },
  { id: "ziwei_classical", label: "紫微规则优先", description: "命身宫和星曜为主，四柱作对照" },
];

export const TRADITIONAL_REFERENCE_BOOKS: {
  id: TraditionalCultureReferenceId;
  title: string;
  alias: string;
  focus: string;
  tradition: string;
  source: {
    level: "index_only" | "upstream_summary" | "upstream_excerpt";
    label: string;
    url?: string;
    note: string;
  };
}[] = [
  { id: "qiong_tong_bao_dian", title: "《穷通宝典》", alias: "常见作《穷通宝鉴》", focus: "论日主调候", tradition: "子平命理", source: { level: "upstream_summary", label: "上游规则摘要", url: "https://github.com/jinchenma94/bazi-skill/blob/bdd7f863d4450bf0e2fac84579ad6b45cfdfa25c/references/classical-texts.md", note: "上游是规则摘要和示例，不是经校勘的完整原文。" } },
  { id: "san_ming_tong_hui", title: "《三命通会》", alias: "", focus: "论格局神煞", tradition: "子平命理", source: { level: "upstream_summary", label: "上游规则摘要", url: "https://github.com/jinchenma94/bazi-skill/blob/bdd7f863d4450bf0e2fac84579ad6b45cfdfa25c/references/classical-texts.md", note: "上游是规则摘要和示例，不是经校勘的完整原文。" } },
  { id: "di_tian_sui", title: "《滴天髓》", alias: "", focus: "论五行旺衰", tradition: "子平命理", source: { level: "upstream_summary", label: "上游规则摘要", url: "https://github.com/jinchenma94/bazi-skill/blob/bdd7f863d4450bf0e2fac84579ad6b45cfdfa25c/references/classical-texts.md", note: "上游是规则摘要和示例，不是经校勘的完整原文。" } },
  { id: "yuan_hai_zi_ping", title: "《渊海子平》", alias: "", focus: "论十神六亲", tradition: "子平命理", source: { level: "upstream_summary", label: "上游规则摘要", url: "https://github.com/jinchenma94/bazi-skill/blob/bdd7f863d4450bf0e2fac84579ad6b45cfdfa25c/references/classical-texts.md", note: "上游是规则摘要和示例，不是经校勘的完整原文。" } },
  { id: "qian_li_ming_gao", title: "《千里命稿》", alias: "", focus: "论命例实证", tradition: "子平命理", source: { level: "upstream_summary", label: "上游规则摘要", url: "https://github.com/jinchenma94/bazi-skill/blob/bdd7f863d4450bf0e2fac84579ad6b45cfdfa25c/references/classical-texts.md", note: "上游是规则摘要和示例，不是经校勘的完整原文。" } },
  { id: "xie_ji_bian_fang_shu", title: "《协纪辨方书》", alias: "", focus: "论择日神煞", tradition: "历法择日", source: { level: "upstream_summary", label: "上游规则摘要", url: "https://github.com/jinchenma94/bazi-skill/blob/bdd7f863d4450bf0e2fac84579ad6b45cfdfa25c/references/classical-texts.md", note: "上游是规则摘要和示例，不是经校勘的完整原文。" } },
  { id: "guo_lao_xing_zong", title: "《果老星宗》", alias: "", focus: "论星命合参", tradition: "星命术", source: { level: "upstream_summary", label: "上游规则摘要", url: "https://github.com/jinchenma94/bazi-skill/blob/bdd7f863d4450bf0e2fac84579ad6b45cfdfa25c/references/classical-texts.md", note: "上游是规则摘要和示例，不是经校勘的完整原文。" } },
  { id: "zi_ping_zhen_quan", title: "《子平真诠》", alias: "", focus: "论用神格局", tradition: "子平命理", source: { level: "upstream_summary", label: "上游规则摘要", url: "https://github.com/jinchenma94/bazi-skill/blob/bdd7f863d4450bf0e2fac84579ad6b45cfdfa25c/references/classical-texts.md", note: "上游是规则摘要和示例，不是经校勘的完整原文。" } },
  { id: "shen_feng_tong_kao", title: "《神峰通考》", alias: "", focus: "论命理辨误", tradition: "子平命理", source: { level: "upstream_summary", label: "上游规则摘要", url: "https://github.com/jinchenma94/bazi-skill/blob/bdd7f863d4450bf0e2fac84579ad6b45cfdfa25c/references/classical-texts.md", note: "上游是规则摘要和示例，不是经校勘的完整原文。" } },
  { id: "zhou_yi", title: "《周易》", alias: "", focus: "论卦象与象数", tradition: "经学象数", source: { level: "index_only", label: "仅索引", note: "Council 只记录书名、主题和流派元数据，未载入原文。" } },
  { id: "ziwei_doushu_quan_shu", title: "《紫微斗数全书》", alias: "", focus: "论星曜与宫位", tradition: "紫微斗数", source: { level: "upstream_excerpt", label: "上游精选片段", url: "https://github.com/Renhuai123/ziwei-doushu/blob/88194a404242bfe5c6d5cc512e4117e3e245cdd5/lib/classics/data/quanshu.ts", note: "上游是结构化精选片段，不是完整古籍原文。" } },
  { id: "xing_ping_hui_hai", title: "《星平会海》", alias: "", focus: "论星命合参与格局", tradition: "星命术", source: { level: "index_only", label: "仅索引", note: "Council 只记录书名、主题和流派元数据，未载入原文。" } },
  { id: "ming_li_yue_yan", title: "《命理约言》", alias: "", focus: "论取用与格局", tradition: "子平命理", source: { level: "index_only", label: "仅索引", note: "Council 只记录书名、主题和流派元数据，未载入原文。" } },
  { id: "zao_hua_yuan_yuan", title: "《造化元钥》", alias: "", focus: "论调候与五行气势", tradition: "子平命理", source: { level: "index_only", label: "仅索引", note: "Council 只记录书名、主题和流派元数据，未载入原文。" } },
  { id: "bu_shi_zheng_zong", title: "《卜筮正宗》", alias: "", focus: "论六爻卦法", tradition: "卜筮", source: { level: "index_only", label: "仅索引", note: "Council 只记录书名、主题和流派元数据，未载入原文。" } },
];

type WallClock = { year: number; month: number; day: number; hour: number; minute: number; second: number };

const SHANGHAI_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

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

function wallClockFromDate(value: Date): WallClock {
  const parts = Object.fromEntries(SHANGHAI_FORMATTER.formatToParts(value).map((part) => [part.type, part.value]));
  return {
    year: Number(parts.year),
    month: Number(parts.month),
    day: Number(parts.day),
    hour: Number(parts.hour),
    minute: Number(parts.minute),
    second: Number(parts.second),
  };
}

function formatWallClock(value: WallClock) {
  const pad = (item: number) => String(item).padStart(2, "0");
  return `${value.year}-${pad(value.month)}-${pad(value.day)} ${pad(value.hour)}:${pad(value.minute)}:${pad(value.second)}`;
}

function shiftWallClock(value: WallClock, minutes: number): WallClock {
  const shifted = new Date(Date.UTC(value.year, value.month - 1, value.day, value.hour, value.minute + minutes, value.second));
  return {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
    hour: shifted.getUTCHours(),
    minute: shifted.getUTCMinutes(),
    second: shifted.getUTCSeconds(),
  };
}

function trueSolarOffsetMinutes(value: WallClock, longitude: number) {
  const start = Date.UTC(value.year, 0, 1);
  const current = Date.UTC(value.year, value.month - 1, value.day);
  const dayOfYear = Math.floor((current - start) / 86_400_000) + 1;
  const angle = (2 * Math.PI * (dayOfYear - 81)) / 364;
  const equationOfTime = 9.87 * Math.sin(2 * angle) - 7.53 * Math.cos(angle) - 1.5 * Math.sin(angle);
  return Math.round(4 * (longitude - 120) + equationOfTime);
}

function solarFromWallClock(value: WallClock) {
  return Solar.fromYmdHms(value.year, value.month, value.day, value.hour, value.minute, value.second);
}

function solarTermFact(term: { getName(): string; getSolar(): { toYmdHms(): string } }) {
  return { name: term.getName(), datetime: term.getSolar().toYmdHms() };
}

export function localFallbackTime(value = new Date()): TrustedTime {
  const rounded = new Date(Math.floor(value.getTime() / 1000) * 1000);
  const local = formatWallClock(wallClockFromDate(rounded)).replace(" ", "T");
  return {
    utc_datetime: rounded.toISOString().replace(".000Z", "Z"),
    local_datetime: `${local}+08:00`,
    timezone: "Asia/Shanghai",
    source: "local_fallback",
    provider: "system_clock",
    source_url: "",
    synced: false,
  };
}

function starLabel(star: { name: string; brightness?: string; mutagen?: string }) {
  const suffix = [star.brightness, star.mutagen ? `化${star.mutagen}` : ""].filter(Boolean).join("·");
  return suffix ? `${star.name}（${suffix}）` : star.name;
}

export async function buildTraditionalCultureSnapshot(profile: TraditionalCultureProfile, trustedTime = localFallbackTime()): Promise<TraditionalCultureSnapshot> {
  const [yearText, monthText, dayText] = profile.birth_date.split("-");
  const [hourText, minuteText] = profile.birth_time.split(":");
  const [year, month, day, hour, minute] = [yearText, monthText, dayText, hourText, minuteText].map(Number);
  const location = resolveTraditionalLocation(profile.birth_place);
  const trueSolarTimeApplied = Boolean(profile.true_solar_time_applied && location);
  const birthCivil: WallClock = { year, month, day, hour, minute, second: 0 };
  const birthOffset = trueSolarTimeApplied && location ? trueSolarOffsetMinutes(birthCivil, location.longitude) : 0;
  const birthCalculation = shiftWallClock(birthCivil, birthOffset);
  const calendarDate = solarFromWallClock(birthCalculation);
  const lunarDate = calendarDate.getLunar();
  const eightChar = lunarDate.getEightChar();
  const chart = astro.bySolar(`${birthCalculation.year}-${birthCalculation.month}-${birthCalculation.day}`, timeIndexFor(birthCalculation.hour), profile.gender === "male" ? "男" : "女", true, "zh-CN");
  const referenceInstant = new Date(trustedTime.utc_datetime);
  if (Number.isNaN(referenceInstant.getTime())) throw new Error("联网校时结果无效，请重试");
  const referenceCivil = wallClockFromDate(referenceInstant);
  const referenceOffset = trueSolarTimeApplied && location ? trueSolarOffsetMinutes(referenceCivil, location.longitude) : 0;
  const referenceCalculation = shiftWallClock(referenceCivil, referenceOffset);
  const referenceSolar = solarFromWallClock(referenceCalculation);
  const referenceLunar = referenceSolar.getLunar();
  const referenceEightChar = referenceLunar.getEightChar();
  let normalizedProfile: TraditionalCultureProfile = {
    ...profile,
    birth_place: profile.birth_place.trim(),
    birth_place_normalized: location?.name || null,
    birth_latitude: location?.latitude ?? null,
    birth_longitude: location?.longitude ?? null,
    birth_place_source: location?.source || "unresolved",
    true_solar_time_applied: trueSolarTimeApplied,
    interpretation_framework: profile.interpretation_framework || "comparative_research",
  };
  if (!normalizedProfile.reference_book_ids?.length) {
    const { reference_book_ids: _referenceBookIds, ...legacyProfile } = normalizedProfile;
    normalizedProfile = legacyProfile;
  }
  const snapshotWithoutHash = {
    schema_version: 2 as const,
    calculation_source: "local_browser" as const,
    calculated_at: trustedTime.utc_datetime,
    profile: normalizedProfile,
    engines: ENGINE_METADATA,
    calendar_facts: {
      solar_datetime: calendarDate.toYmdHms(),
      civil_solar_datetime: formatWallClock(birthCivil),
      true_solar_datetime: trueSolarTimeApplied ? formatWallClock(birthCalculation) : null,
      true_solar_time_offset_minutes: trueSolarTimeApplied ? birthOffset : null,
      lunar_date: lunarDate.toString(),
      zodiac: lunarDate.getYearShengXiao(),
      constellation: calendarDate.getXingZuo(),
      eight_char: eightChar.toString(),
      pillars: [eightChar.getYear(), eightChar.getMonth(), eightChar.getDay(), eightChar.getTime()],
      pillar_wuxing: [eightChar.getYearWuXing(), eightChar.getMonthWuXing(), eightChar.getDayWuXing(), eightChar.getTimeWuXing()],
      heavenly_stem_ten_gods: [eightChar.getYearShiShenGan(), eightChar.getMonthShiShenGan(), eightChar.getDayShiShenGan(), eightChar.getTimeShiShenGan()],
    },
    timing_facts: {
      reference_civil_datetime: formatWallClock(referenceCivil),
      reference_true_solar_datetime: formatWallClock(referenceCalculation),
      reference_true_solar_offset_minutes: referenceOffset,
      timezone: "Asia/Shanghai" as const,
      time_source: trustedTime.source,
      time_provider: trustedTime.provider,
      time_source_url: trustedTime.source_url,
      ...(trustedTime.time_proof ? { time_proof: trustedTime.time_proof } : {}),
      synced: trustedTime.synced,
      lunar_date: referenceLunar.toString(),
      year_pillar: referenceEightChar.getYear(),
      month_pillar: referenceEightChar.getMonth(),
      day_pillar: referenceEightChar.getDay(),
      hour_pillar: referenceEightChar.getTime(),
      current_solar_term: referenceLunar.getJieQi(),
      previous_solar_term: solarTermFact(referenceLunar.getPrevJieQi()),
      next_solar_term: solarTermFact(referenceLunar.getNextJieQi()),
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
    notices: [
      "排盘由版本化本地开源引擎计算，不会调用第三方命理 API。",
      "传统文化解释不属于科学验证，不得作为医疗、法律、投资、合规或生产决策依据。",
      trueSolarTimeApplied
        ? `已按${location?.name}城市级经度应用真太阳时校正；临界时刻仍可能因流派口径产生不同结果。`
        : "未应用真太阳时校正；临界时刻可能因出生地或流派口径产生不同结果。",
      trustedTime.synced ? "咨询时刻已通过至少两个一致的 HTTPS 时间源联网校时。" : "联网校时失败，本次明确使用本机时钟回退。",
      "ziwei-doushu 的开源实现依赖 iztro 与 lunar-javascript，共享底层结果不能视为独立交叉验证。",
    ],
  };
  const timingFactsForHash = { ...snapshotWithoutHash.timing_facts };
  delete timingFactsForHash.time_proof;
  const hashPayload = { ...snapshotWithoutHash, timing_facts: timingFactsForHash };
  return { ...snapshotWithoutHash, snapshot_sha256: sha256(hashPayload) };
}
