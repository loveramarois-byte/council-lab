const pageUrl = process.argv[2];

if (!pageUrl) {
  console.error("Usage: node scripts/check_frontend_assets.mjs <page-url>");
  process.exit(2);
}

const pageResponse = await fetch(pageUrl, { redirect: "follow" });
if (!pageResponse.ok) {
  throw new Error(`Page returned HTTP ${pageResponse.status}: ${pageUrl}`);
}

const html = await pageResponse.text();
const assetPaths = new Set(
  [...html.matchAll(/(?:src|href)="([^"]*\/_next\/static\/[^"]+)"/g)].map((match) => match[1]),
);

if (assetPaths.size === 0) {
  throw new Error(`Page did not reference any Next.js static assets: ${pageUrl}`);
}

const failures = [];
for (const assetPath of assetPaths) {
  const assetUrl = new URL(assetPath, pageResponse.url);
  const assetResponse = await fetch(assetUrl);
  if (!assetResponse.ok) failures.push(`${assetResponse.status} ${assetUrl}`);
}

if (failures.length > 0) {
  throw new Error(`Frontend asset validation failed:\n${failures.join("\n")}`);
}

console.log(`Validated ${assetPaths.size} frontend assets from ${pageResponse.url}`);
