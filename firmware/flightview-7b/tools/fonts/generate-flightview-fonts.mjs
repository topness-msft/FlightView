import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const firmwareRoot = path.resolve(__dirname, "..", "..");
const fontsDir = path.join(firmwareRoot, "components", "flightview_views", "fonts");
const sourceDir = path.join(fontsDir, "source_ttf");
const generatedHeader = path.join(fontsDir, "flightview_fonts.h");
const converterScript = path.join(__dirname, "node_modules", "lv_font_conv", "lv_font_conv.js");
const checkMode = process.argv.includes("--check");
const flashBudgetBytes = 750 * 1024;

const sources = [
  {
    file: "Outfit-ExtraBold.ttf",
    family: "Outfit",
    repo: "https://github.com/Outfitio/Outfit-Fonts",
    commit: "902773808eb372f70fb34e8946dd1ffe604efc79",
    sourcePath: "fonts/ttf/Outfit-ExtraBold.ttf",
    sha256: "0f028cbdc61a588bc44fef911e8d2bcfc0bc05b241a9b797686024d269d964b6",
  },
  {
    file: "Outfit-Bold.ttf",
    family: "Outfit",
    repo: "https://github.com/Outfitio/Outfit-Fonts",
    commit: "902773808eb372f70fb34e8946dd1ffe604efc79",
    sourcePath: "fonts/ttf/Outfit-Bold.ttf",
    sha256: "f620b69582e06d7e1b3bbde74ed8c5876eadabb038390780db2a3414a1490197",
  },
  {
    file: "JetBrainsMono-Bold.ttf",
    family: "JetBrains Mono",
    repo: "https://github.com/JetBrains/JetBrainsMono",
    commit: "19371302b95d218af43299bce79ddbddd0bc364d",
    sourcePath: "fonts/ttf/JetBrainsMono-Bold.ttf",
    sha256: "d22c4f3821d725eb01210d278d95dfcfcaadc34699a06658d47c8a5cc5830ada",
  },
];

const fontConfigs = [
  {
    name: "fv_outfit_88",
    source: "Outfit-ExtraBold.ttf",
    size: 88,
    ranges: ["0x20-0x7E,0xA0-0xFF"],
    use: "carrier primary",
    requiredText: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ,.-/&+ÉéÑñÅåÄäÖöÜüÇçÆæØøß",
  },
  {
    name: "fv_outfit_64",
    source: "Outfit-Bold.ttf",
    size: 64,
    ranges: ["0x20-0x7E,0xA0-0xFF"],
    use: "carrier fallback",
    requiredText: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ,.-/&+ÉéÑñÅåÄäÖöÜüÇçÆæØøß",
  },
  {
    name: "fv_mono_80",
    source: "JetBrainsMono-Bold.ttf",
    size: 80,
    ranges: ["0x20-0x7E,0xB0"],
    use: "airframe/type code",
    requiredText: "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ,./+-°",
  },
  {
    name: "fv_mono_96",
    source: "JetBrainsMono-Bold.ttf",
    size: 96,
    ranges: ["0x20-0x7E,0xB0"],
    use: "origin/destination IATA",
    requiredText: "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ,./+-°",
  },
  {
    name: "fv_mono_40",
    source: "JetBrainsMono-Bold.ttf",
    size: 40,
    ranges: ["0x20-0x7E,0xB0"],
    use: "stats and flight badge",
    requiredText: "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ,./+-°",
  },
  {
    name: "fv_outfit_28",
    source: "Outfit-Bold.ttf",
    size: 28,
    ranges: ["0x20-0x7E,0xA0-0xFF"],
    use: "cities, full airframe names, and secondary header text",
    requiredText: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ,.-/&+ÉéÑñÅåÄäÖöÜüÇçÆæØøßãSão Paulo München",
  },
];

function fail(message) {
  throw new Error(message);
}

function sha256(filePath) {
  return createHash("sha256").update(readFileSync(filePath)).digest("hex");
}

function ensureSources() {
  for (const source of sources) {
    const filePath = path.join(sourceDir, source.file);
    if (!existsSync(filePath)) {
      fail(`Missing source TTF ${filePath}. Restore it from ${source.repo}/blob/${source.commit}/${source.sourcePath}`);
    }
    const actual = sha256(filePath);
    if (actual !== source.sha256) {
      fail(`${source.file} sha256 mismatch: expected ${source.sha256}, got ${actual}`);
    }
  }
}

function readU16(buffer, offset) {
  return buffer.readUInt16BE(offset);
}

function readI16(buffer, offset) {
  return buffer.readInt16BE(offset);
}

function readU32(buffer, offset) {
  return buffer.readUInt32BE(offset);
}

function tableMap(buffer) {
  const count = readU16(buffer, 4);
  const tables = new Map();
  for (let i = 0; i < count; i += 1) {
    const offset = 12 + i * 16;
    const tag = buffer.toString("ascii", offset, offset + 4);
    tables.set(tag, {
      offset: readU32(buffer, offset + 8),
      length: readU32(buffer, offset + 12),
    });
  }
  return tables;
}

function parseCmap(buffer, cmap) {
  const subtables = [];
  const count = readU16(buffer, cmap.offset + 2);
  for (let i = 0; i < count; i += 1) {
    const record = cmap.offset + 4 + i * 8;
    const platform = readU16(buffer, record);
    const encoding = readU16(buffer, record + 2);
    const offset = cmap.offset + readU32(buffer, record + 4);
    const format = readU16(buffer, offset);
    subtables.push({ platform, encoding, offset, format });
  }
  const chosen =
    subtables.find((s) => s.format === 12 && s.platform === 3 && s.encoding === 10) ||
    subtables.find((s) => s.format === 4 && s.platform === 3 && (s.encoding === 1 || s.encoding === 0)) ||
    subtables.find((s) => s.format === 12) ||
    subtables.find((s) => s.format === 4);
  if (!chosen) fail("No supported cmap format 4/12 subtable found");
  return (codePoint) => {
    if (chosen.format === 12) return glyphFromFormat12(buffer, chosen.offset, codePoint);
    return glyphFromFormat4(buffer, chosen.offset, codePoint);
  };
}

function glyphFromFormat12(buffer, offset, codePoint) {
  const groupCount = readU32(buffer, offset + 12);
  let lo = 0;
  let hi = groupCount - 1;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    const group = offset + 16 + mid * 12;
    const start = readU32(buffer, group);
    const end = readU32(buffer, group + 4);
    if (codePoint < start) hi = mid - 1;
    else if (codePoint > end) lo = mid + 1;
    else return readU32(buffer, group + 8) + codePoint - start;
  }
  return 0;
}

function glyphFromFormat4(buffer, offset, codePoint) {
  if (codePoint > 0xffff) return 0;
  const segCount = readU16(buffer, offset + 6) / 2;
  const endCodes = offset + 14;
  const startCodes = endCodes + segCount * 2 + 2;
  const idDeltas = startCodes + segCount * 2;
  const idRangeOffsets = idDeltas + segCount * 2;
  for (let i = 0; i < segCount; i += 1) {
    const end = readU16(buffer, endCodes + i * 2);
    if (codePoint > end) continue;
    const start = readU16(buffer, startCodes + i * 2);
    if (codePoint < start) return 0;
    const delta = readI16(buffer, idDeltas + i * 2);
    const rangeOffset = readU16(buffer, idRangeOffsets + i * 2);
    if (rangeOffset === 0) return (codePoint + delta) & 0xffff;
    const glyphOffset = idRangeOffsets + i * 2 + rangeOffset + (codePoint - start) * 2;
    const glyph = readU16(buffer, glyphOffset);
    return glyph === 0 ? 0 : (glyph + delta) & 0xffff;
  }
  return 0;
}

function parseTtf(filePath) {
  const buffer = readFileSync(filePath);
  const tables = tableMap(buffer);
  for (const tag of ["head", "hhea", "hmtx", "maxp", "cmap", "OS/2"]) {
    if (!tables.has(tag)) fail(`${path.basename(filePath)} missing ${tag} table`);
  }
  const head = tables.get("head");
  const hhea = tables.get("hhea");
  const maxp = tables.get("maxp");
  const hmtx = tables.get("hmtx");
  const os2 = tables.get("OS/2");
  const unitsPerEm = readU16(buffer, head.offset + 18);
  const glyphCount = readU16(buffer, maxp.offset + 4);
  const hMetricCount = readU16(buffer, hhea.offset + 34);
  const advances = [];
  let lastAdvance = 0;
  for (let i = 0; i < glyphCount; i += 1) {
    if (i < hMetricCount) {
      lastAdvance = readU16(buffer, hmtx.offset + i * 4);
      advances.push(lastAdvance);
    } else {
      advances.push(lastAdvance);
    }
  }
  const os2Version = readU16(buffer, os2.offset);
  const weightClass = readU16(buffer, os2.offset + 4);
  const xHeight = os2Version >= 2 && os2.length >= 88 ? readI16(buffer, os2.offset + 86) : null;
  const capHeight = os2Version >= 2 && os2.length >= 90 ? readI16(buffer, os2.offset + 88) : null;
  const glyphIndex = parseCmap(buffer, tables.get("cmap"));
  return {
    unitsPerEm,
    weightClass,
    xHeight,
    capHeight,
    glyphIndex,
    advanceFor(codePoint) {
      const glyph = glyphIndex(codePoint);
      if (glyph === 0) return null;
      return advances[glyph] ?? advances[advances.length - 1];
    },
  };
}

function parseRangeToken(token) {
  const parts = token.split("-");
  const parsePart = (part) => Number.parseInt(part.trim().replace(/^0x/i, ""), part.trim().toLowerCase().startsWith("0x") ? 16 : 10);
  const start = parsePart(parts[0]);
  const end = parts.length > 1 ? parsePart(parts[1]) : start;
  return { start, end };
}

function configIncludes(config, codePoint) {
  return config.ranges.some((range) =>
    range.split(",").some((token) => {
      const { start, end } = parseRangeToken(token);
      return codePoint >= start && codePoint <= end;
    })
  );
}

function codePoints(text) {
  return Array.from(text, (ch) => ch.codePointAt(0));
}

function assertRequiredGlyphs(config, metrics) {
  for (const codePoint of codePoints(config.requiredText)) {
    if (!configIncludes(config, codePoint)) {
      fail(`${config.name} range omits required U+${codePoint.toString(16).toUpperCase().padStart(4, "0")}`);
    }
    if (metrics.advanceFor(codePoint) == null) {
      fail(`${config.name} source font lacks U+${codePoint.toString(16).toUpperCase().padStart(4, "0")}`);
    }
  }
}

function textWidth(metrics, size, text) {
  let units = 0;
  for (const codePoint of codePoints(text)) {
    const advance = metrics.advanceFor(codePoint);
    if (advance == null) fail(`Missing glyph U+${codePoint.toString(16).toUpperCase()} for "${text}"`);
    units += advance;
  }
  return Math.round((units * size) / metrics.unitsPerEm);
}

function runConverter(config) {
  const sourcePath = path.relative(__dirname, path.join(sourceDir, config.source));
  const outputPath = path.relative(__dirname, path.join(fontsDir, `${config.name}.c`));
  const args = [
    "--font",
    sourcePath,
    "--range",
    config.ranges.join(","),
    "--size",
    String(config.size),
    "--format",
    "lvgl",
    "--bpp",
    "4",
    "--lv-font-name",
    config.name,
    "--lv-include",
    "lvgl.h",
    "--no-kerning",
    "-o",
    outputPath,
  ];
  execFileSync(process.execPath, [converterScript, ...args], { cwd: __dirname, stdio: "pipe" });
}

function writeHeader() {
  const names = fontConfigs.map((config) => config.name);
  const header = `#pragma once

#include "lvgl.h"

${names.map((name) => `LV_FONT_DECLARE(${name});`).join("\n")}
`;
  const current = existsSync(generatedHeader) ? readFileSync(generatedHeader, "utf8") : null;
  if (current !== header) writeFileSync(generatedHeader, header);
}

function extractGeneratedStats(config) {
  const filePath = path.join(fontsDir, `${config.name}.c`);
  const text = readFileSync(filePath, "utf8");
  const bytes = statSync(filePath).size;
  const lineHeight = Number(text.match(/\.line_height\s*=\s*(\d+)/)?.[1] ?? 0);
  const baseLine = Number(text.match(/\.base_line\s*=\s*(\d+)/)?.[1] ?? 0);
  const bitmapFormat = Number(text.match(/\.bitmap_format\s*=\s*(\d+)/)?.[1] ?? -1);
  const bitmapBlock = text.match(/static LV_ATTRIBUTE_LARGE_CONST const uint8_t glyph_bitmap\[\] = \{([\s\S]*?)\n\};/)?.[1] ?? "";
  const bitmapBytes = (bitmapBlock.match(/0x[0-9a-f]{2}/gi) ?? []).length;
  const glyphDescriptors = Array.from(
    text.matchAll(/\.adv_w = (\d+), \.box_w = (\d+), \.box_h = (\d+), \.ofs_x = (-?\d+), \.ofs_y = (-?\d+)/g),
    (match) => ({
      advW: Number(match[1]),
      boxW: Number(match[2]),
      boxH: Number(match[3]),
      ofsX: Number(match[4]),
      ofsY: Number(match[5]),
    })
  );
  const maxBoxW = Math.max(...glyphDescriptors.map((g) => g.boxW));
  const maxBoxH = Math.max(...glyphDescriptors.map((g) => g.boxH));
  const maxAdvW = Math.max(...glyphDescriptors.map((g) => g.advW));
  const cmapCount = (text.match(/\.range_start\s*=/g) ?? []).length;
  const estimatedArrayBytes = bitmapBytes + glyphDescriptors.length * 8 + cmapCount * 24 + 160;
  return { bytes, bitmapBytes, estimatedArrayBytes, lineHeight, baseLine, bitmapFormat, maxBoxW, maxBoxH, maxAdvW };
}

function printReport(metricsByFile) {
  const generated = fontConfigs.map((config) => ({
    config,
    metrics: metricsByFile.get(config.source),
    generated: extractGeneratedStats(config),
  }));
  const totalBitmapBytes = generated.reduce((sum, item) => sum + item.generated.bitmapBytes, 0);
  const totalArrayBytes = generated.reduce((sum, item) => sum + item.generated.estimatedArrayBytes, 0);
  const totalSourceBytes = generated.reduce((sum, item) => sum + item.generated.bytes, 0);
  if (totalArrayBytes > flashBudgetBytes) {
    fail(`Estimated generated const data ${totalArrayBytes} exceeds ${flashBudgetBytes} byte budget`);
  }

  console.log("FlightView 7B font generation complete");
  console.log(`Generated fonts: ${fontConfigs.map((f) => `${f.name}.c`).join(", ")}`);
  console.log(`Estimated generated const data bytes: ${totalArrayBytes}`);
  console.log(`Estimated bitmap bytes inside const data: ${totalBitmapBytes}`);
  console.log(`Generated C source bytes: ${totalSourceBytes}`);
  console.log("");
  console.log("Source font metrics:");
  for (const source of sources) {
    const metrics = metricsByFile.get(source.file);
    const cap = metrics.capHeight == null ? "n/a" : `${Math.round((metrics.capHeight * 1000) / metrics.unitsPerEm) / 10}% em`;
    const xh = metrics.xHeight == null ? "n/a" : `${Math.round((metrics.xHeight * 1000) / metrics.unitsPerEm) / 10}% em`;
    console.log(`- ${source.file}: weight ${metrics.weightClass}, units/em ${metrics.unitsPerEm}, cap ${cap}, x-height ${xh}, sha256 ${source.sha256}`);
  }
  console.log("");
  console.log("Generated glyph dimensions:");
  for (const item of generated) {
    console.log(
      `- ${item.config.name}: ${item.config.use}, size ${item.config.size}, line ${item.generated.lineHeight}, baseline ${item.generated.baseLine}, max box ${item.generated.maxBoxW}x${item.generated.maxBoxH}, max adv ${item.generated.maxAdvW}, estimated array bytes ${item.generated.estimatedArrayBytes}, bitmap bytes ${item.generated.bitmapBytes}, bitmap_format ${item.generated.bitmapFormat}`
    );
  }
  console.log("");
  console.log("Layout measurements:");
  const widths = [
    ["United", "Outfit 88", "Outfit-ExtraBold.ttf", 88, 650],
    ["United", "Outfit 64", "Outfit-Bold.ttf", 64, 650],
    ["Unknown", "Outfit 88", "Outfit-ExtraBold.ttf", 88, 650],
    ["Unknown", "Outfit 64", "Outfit-Bold.ttf", 64, 650],
    ["All Nippon Airways", "Outfit 88", "Outfit-ExtraBold.ttf", 88, 650],
    ["All Nippon Airways", "Outfit 64", "Outfit-Bold.ttf", 64, 650],
    ["B39M", "JetBrains Mono 80", "JetBrainsMono-Bold.ttf", 80, 280],
    ["CL60", "JetBrains Mono 80", "JetBrainsMono-Bold.ttf", 80, 280],
    ["SEA", "JetBrains Mono 96", "JetBrainsMono-Bold.ttf", 96, 300],
    ["ORD", "JetBrains Mono 96", "JetBrainsMono-Bold.ttf", 96, 300],
    ["IAD", "JetBrains Mono 96", "JetBrainsMono-Bold.ttf", 96, 300],
    ["18,642", "JetBrains Mono 40", "JetBrainsMono-Bold.ttf", 40, 232],
    ["São Paulo", "Outfit 28", "Outfit-Bold.ttf", 28, 350],
    ["München", "Outfit 28", "Outfit-Bold.ttf", 28, 350],
  ];
  for (const [sample, label, source, size, lane] of widths) {
    const width = textWidth(metricsByFile.get(source), size, sample);
    const result = width <= lane ? "OK" : "OVER";
    console.log(`- ${sample} @ ${label}: ${width}px / ${lane}px ${result}`);
  }
  assertLayout(metricsByFile);
}

function assertLane(metricsByFile, sample, source, size, lane, label) {
  const width = textWidth(metricsByFile.get(source), size, sample);
  if (width > lane) fail(`${label} measures ${width}px, exceeding ${lane}px lane`);
}

function assertLayout(metricsByFile) {
  assertLane(metricsByFile, "United", "Outfit-ExtraBold.ttf", 88, 650, "United carrier at Outfit 88");
  assertLane(metricsByFile, "Unknown", "Outfit-ExtraBold.ttf", 88, 650, "Unknown carrier at Outfit 88");
  assertLane(metricsByFile, "All Nippon Airways", "Outfit-Bold.ttf", 64, 650, "All Nippon Airways carrier fallback at Outfit 64");
  for (const sample of ["B39M", "CL60"]) {
    assertLane(metricsByFile, sample, "JetBrainsMono-Bold.ttf", 80, 280, `${sample} airframe at JetBrains Mono 80`);
  }
  for (const sample of ["SEA", "ORD", "IAD"]) {
    assertLane(metricsByFile, sample, "JetBrainsMono-Bold.ttf", 96, 300, `${sample} route IATA at JetBrains Mono 96`);
  }
  assertLane(metricsByFile, "18,642", "JetBrainsMono-Bold.ttf", 40, 232, "18,642 stat at JetBrains Mono 40");
  assertLane(metricsByFile, "São Paulo", "Outfit-Bold.ttf", 28, 350, "São Paulo city at Outfit 28");
  assertLane(metricsByFile, "München", "Outfit-Bold.ttf", 28, 350, "München city at Outfit 28");
}

function main() {
  if (!existsSync(converterScript)) fail(`Missing local lv_font_conv at ${converterScript}. Run npm install in ${__dirname}.`);
  mkdirSync(fontsDir, { recursive: true });
  ensureSources();

  const metricsByFile = new Map();
  for (const source of sources) {
    metricsByFile.set(source.file, parseTtf(path.join(sourceDir, source.file)));
  }
  for (const config of fontConfigs) {
    assertRequiredGlyphs(config, metricsByFile.get(config.source));
    runConverter(config);
  }
  writeHeader();
  printReport(metricsByFile);
  if (checkMode) console.log("Font source hash, glyph coverage, generation, and layout checks passed.");
}

main();
