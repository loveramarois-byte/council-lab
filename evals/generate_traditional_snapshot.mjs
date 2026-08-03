import { writeFile } from "node:fs/promises";
import { buildTraditionalCultureSnapshot } from "../frontend/lib/traditional-culture.ts";

const output = process.argv[2] ?? "evals/results/traditional-snapshot.json";
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
  interpretation_framework: "comparative_research",
  reference_book_ids: [],
});

await writeFile(output, `${JSON.stringify(snapshot, null, 2)}\n`, "utf8");
console.log(JSON.stringify({
  output,
  snapshot_sha256: snapshot.snapshot_sha256,
  engines: snapshot.engines.map((engine) => `${engine.id}@${engine.version}`),
  palaces: snapshot.ziwei_chart.palaces.length,
}, null, 2));
