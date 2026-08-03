import { createHmac } from "node:crypto";
import type { TraditionalCultureProfile, TraditionalCultureSnapshot, TrustedTime } from "./api";
import { TRADITIONAL_REFERENCE_BOOKS, TRADITIONAL_RULE_PROFILES } from "./traditional-culture";

const PROFILE_KEYS = new Set([
  "calendar_type",
  "birth_date",
  "birth_time",
  "time_precision",
  "gender",
  "birth_place",
  "timezone",
  "true_solar_time_applied",
  "focus_topics",
  "interpretation_framework",
  "reference_book_ids",
]);
const FOCUS_TOPICS = new Set(["temperament", "career", "relationships", "timing"]);
const FRAMEWORKS = new Set(TRADITIONAL_RULE_PROFILES.map((item) => item.id));
const REFERENCES = new Set(TRADITIONAL_REFERENCE_BOOKS.map((item) => item.id));
const HIDDEN_CHARACTERS = /[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringArray(value: unknown, allowed: Set<string>, maxLength: number, label: string) {
  if (!Array.isArray(value) || value.length > maxLength || value.some((item) => typeof item !== "string" || !allowed.has(item))) {
    throw new Error(`${label}无效`);
  }
  if (new Set(value).size !== value.length) throw new Error(`${label}不能重复`);
  return value as string[];
}

export function parseTraditionalProfile(value: unknown): TraditionalCultureProfile {
  if (!isRecord(value) || Object.keys(value).some((key) => !PROFILE_KEYS.has(key))) {
    throw new Error("排盘资料包含未知字段");
  }
  const birthDate = typeof value.birth_date === "string" ? value.birth_date : "";
  const birthTime = typeof value.birth_time === "string" ? value.birth_time : "";
  const birthPlace = typeof value.birth_place === "string" ? value.birth_place : "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(birthDate)) throw new Error("出生日期格式无效");
  const parsedDate = new Date(`${birthDate}T00:00:00+08:00`);
  const earliest = new Date("1900-01-01T00:00:00+08:00");
  if (Number.isNaN(parsedDate.getTime()) || parsedDate < earliest || parsedDate > new Date()) {
    throw new Error("出生日期超出支持范围");
  }
  if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(birthTime)) throw new Error("出生时间格式无效");
  if (birthPlace.length > 120 || HIDDEN_CHARACTERS.test(birthPlace)) throw new Error("出生地格式无效");
  if (value.calendar_type !== "solar" || value.timezone !== "Asia/Shanghai") throw new Error("当前只支持公历和 Asia/Shanghai");
  if (!(["exact", "approximate"] as unknown[]).includes(value.time_precision)) throw new Error("时间精度无效");
  if (!(["male", "female"] as unknown[]).includes(value.gender)) throw new Error("排盘性别参数无效");
  if (typeof value.true_solar_time_applied !== "boolean") throw new Error("真太阳时开关无效");
  const focusTopics = stringArray(value.focus_topics, FOCUS_TOPICS, 4, "研究主题");
  const framework = value.interpretation_framework ?? "comparative_research";
  if (typeof framework !== "string" || !FRAMEWORKS.has(framework as never)) throw new Error("解释体系无效");
  const referenceBookIds = stringArray(value.reference_book_ids ?? [], REFERENCES, 15, "参考典籍");
  return {
    calendar_type: "solar",
    birth_date: birthDate,
    birth_time: birthTime,
    time_precision: value.time_precision as "exact" | "approximate",
    gender: value.gender as "male" | "female",
    birth_place: birthPlace,
    timezone: "Asia/Shanghai",
    true_solar_time_applied: value.true_solar_time_applied,
    focus_topics: focusTopics as TraditionalCultureProfile["focus_topics"],
    interpretation_framework: framework as TraditionalCultureProfile["interpretation_framework"],
    reference_book_ids: referenceBookIds as TraditionalCultureProfile["reference_book_ids"],
  };
}

export function parseTrustedTime(value: unknown): TrustedTime {
  if (!isRecord(value)) throw new Error("联网校时响应无效");
  const source = value.source;
  const provider = value.provider;
  const synced = value.synced;
  const validNetwork = source === "network" && provider === "https_consensus" && synced === true;
  const validFallback = source === "local_fallback" && provider === "system_clock" && synced === false;
  if (!validNetwork && !validFallback) throw new Error("联网校时来源无效");
  for (const key of ["utc_datetime", "local_datetime", "timezone", "source_url"] as const) {
    if (typeof value[key] !== "string") throw new Error("联网校时字段无效");
  }
  if (value.timezone !== "Asia/Shanghai" || Number.isNaN(new Date(value.utc_datetime as string).getTime())) {
    throw new Error("联网校时时刻无效");
  }
  if (validNetwork && (typeof value.time_proof !== "string" || !/^v1\.[a-f0-9]{64}$/.test(value.time_proof))) {
    throw new Error("联网校时证明缺失");
  }
  if (validFallback && value.time_proof !== undefined) throw new Error("本机时间回退不能携带联网证明");
  return value as unknown as TrustedTime;
}

export function snapshotProofFor(snapshot: TraditionalCultureSnapshot, secret: string) {
  if (secret.length < 32) throw new Error("Council 内部认证尚未就绪");
  const timeProof = snapshot.timing_facts?.time_proof || "";
  const digest = createHmac("sha256", secret)
    .update(`${snapshot.snapshot_sha256}\n${timeProof}`, "utf8")
    .digest("hex");
  return `v1.${digest}`;
}

export function localBackendUrl(value = process.env.COUNCIL_BACKEND_URL || "http://127.0.0.1:8001") {
  const parsed = new URL(value);
  const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (!(["127.0.0.1", "localhost", "::1"] as string[]).includes(hostname) || !(["http:", "https:"] as string[]).includes(parsed.protocol)) {
    throw new Error("排盘服务只允许连接本机后端");
  }
  return parsed.origin;
}
