import coordinates from "./traditional-city-coordinates.json";

export const TRADITIONAL_LOCATION_SOURCE = {
  repository: "https://github.com/Ficere/tianji",
  commit: "d674635c810b167c616df5fd607418a38d290315",
  path: "references/city_coords.json",
  license: "MIT",
} as const;

export type TraditionalLocation = {
  name: string;
  latitude: number;
  longitude: number;
  source: "offline_city_catalog";
};

const CITY_ENTRIES = Object.entries(coordinates)
  .filter((entry): entry is [string, [number, number]] => Array.isArray(entry[1]) && entry[1].length === 2)
  .sort(([left], [right]) => right.length - left.length);

const PROVINCE_SECTIONS: [string, string[]][] = [
  ["北京", ["北京", "北京市"]], ["天津", ["天津", "天津市"]], ["石家庄", ["河北", "河北省"]],
  ["太原", ["山西", "山西省"]], ["呼和浩特", ["内蒙古", "内蒙古自治区"]], ["沈阳", ["辽宁", "辽宁省"]],
  ["长春", ["吉林", "吉林省"]], ["哈尔滨", ["黑龙江", "黑龙江省"]], ["上海", ["上海", "上海市"]],
  ["南京", ["江苏", "江苏省"]], ["杭州", ["浙江", "浙江省"]], ["合肥", ["安徽", "安徽省"]],
  ["福州", ["福建", "福建省"]], ["南昌", ["江西", "江西省"]], ["济南", ["山东", "山东省"]],
  ["郑州", ["河南", "河南省"]], ["武汉", ["湖北", "湖北省"]], ["长沙", ["湖南", "湖南省"]],
  ["广州", ["广东", "广东省"]], ["南宁", ["广西", "广西壮族自治区"]], ["海口", ["海南", "海南省"]],
  ["重庆", ["重庆", "重庆市"]], ["成都", ["四川", "四川省"]], ["昆明", ["云南", "云南省"]],
  ["贵阳", ["贵州", "贵州省"]], ["拉萨", ["西藏", "西藏自治区"]], ["西安", ["陕西", "陕西省"]],
  ["兰州", ["甘肃", "甘肃省"]], ["西宁", ["青海", "青海省"]], ["银川", ["宁夏", "宁夏回族自治区"]],
  ["乌鲁木齐", ["新疆", "新疆维吾尔自治区"]], ["香港", ["香港", "香港特别行政区"]],
  ["澳门", ["澳门", "澳门特别行政区"]], ["台北", ["台湾", "台湾省"]],
];

const PROVINCES_BY_CITY = (() => {
  const sectionStarts = new Map(PROVINCE_SECTIONS);
  const result = new Map<string, string[]>();
  let activeProvince: string[] = [];
  for (const [name] of Object.entries(coordinates)) {
    activeProvince = sectionStarts.get(name) || activeProvince;
    if (Array.isArray(coordinates[name as keyof typeof coordinates])) result.set(name, activeProvince);
  }
  return result;
})();

// The upstream catalog keeps these Yunnan aliases before its provincial
// capital. Pin them explicitly instead of inheriting the previous Sichuan
// section from source-file order.
const PROVINCE_OVERRIDES = new Map<string, string[]>([
  ["普洱", ["云南", "云南省"]],
  ["西双版纳", ["云南", "云南省"]],
  ["景洪", ["云南", "云南省"]],
]);

function normalizedPlace(value: string) {
  return value.normalize("NFKC").replace(/[\s,，·]+/g, "").replace(/(?:中国|中华人民共和国)/g, "");
}

export function resolveTraditionalLocation(value: string): TraditionalLocation | null {
  const normalized = normalizedPlace(value);
  if (!normalized) return null;
  const match = CITY_ENTRIES.find(([name]) => {
    const city = name.replace(/市$/, "");
    const cityForms = new Set([name, city, `${city}市`]);
    if (cityForms.has(normalized)) return true;
    return (PROVINCE_OVERRIDES.get(name) || PROVINCES_BY_CITY.get(name) || []).some((province) =>
      [...cityForms].some((cityForm) => normalized === `${province}${cityForm}`),
    );
  });
  if (!match) return null;
  const [name, [latitude, longitude]] = match;
  return { name: name.replace(/市$/, ""), latitude, longitude, source: "offline_city_catalog" };
}
