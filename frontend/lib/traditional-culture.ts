import { sha256 as nobleSha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { astro } from "iztro";
import { Solar } from "lunar-javascript";
import type { TraditionalCultureProfile, TraditionalCultureReferenceId, TraditionalCultureSnapshot } from "./api";

const ENGINE_METADATA = [
  { id: "lunar-javascript" as const, version: "1.7.7", source_url: "https://github.com/6tail/lunar-javascript", license: "MIT" as const },
  { id: "iztro" as const, version: "2.5.8", source_url: "https://github.com/SylarLong/iztro", license: "MIT" as const },
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
  let normalizedProfile: TraditionalCultureProfile = { ...profile, birth_place: profile.birth_place.trim() };
  if (!normalizedProfile.reference_book_ids?.length) {
    const { reference_book_ids: _referenceBookIds, ...legacyProfile } = normalizedProfile;
    normalizedProfile = legacyProfile;
  }
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
