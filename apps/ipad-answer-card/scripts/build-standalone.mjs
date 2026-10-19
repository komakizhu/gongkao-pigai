#!/usr/bin/env node

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const [configArgument, outputArgument] = process.argv.slice(2);
if (!configArgument || !outputArgument) {
  console.error("用法：node scripts/build-standalone.mjs <公开配置.json> <输出.html>");
  process.exit(1);
}

const appRoot = fileURLToPath(new URL("..", import.meta.url));
const distRoot = resolve(appRoot, "dist");
const configPath = resolve(process.cwd(), configArgument);
const outputPath = resolve(process.cwd(), outputArgument);
const config = JSON.parse(await readFile(configPath, "utf8"));
let html = await readFile(resolve(distRoot, "index.html"), "utf8");

function assetPath(relativePath) {
  return resolve(distRoot, relativePath.replace(/^\.\//, ""));
}

function safeJson(value) {
  return JSON.stringify(value).replaceAll("<", "\\u003c").replaceAll("\u2028", "\\u2028").replaceAll("\u2029", "\\u2029");
}

for (const match of [...html.matchAll(/<script\b[^>]*\bsrc=["']([^"']+)["'][^>]*><\/script>/gi)]) {
  const tag = match[0];
  const source = await readFile(assetPath(match[1]), "utf8");
  // Bundled code may contain $& / $' / $`: replacement strings would corrupt the script.
  html = html.replace(tag, () => `<script type="module">${source}</script>`);
}

for (const match of [...html.matchAll(/<link\b[^>]*\brel=["']stylesheet["'][^>]*\bhref=["']([^"']+)["'][^>]*>/gi)]) {
  const tag = match[0];
  const source = await readFile(assetPath(match[1]), "utf8");
  html = html.replace(tag, () => `<style>${source}</style>`);
}

html = html.replace(/\s*<link\b[^>]*\brel=["']manifest["'][^>]*>/gi, "");
html = html.replace(/<title>[^<]*<\/title>/i, () => `<title>${String(config.name).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;") }答题卡</title>`);
html = html.replace(/<body([^>]*)>/i, (_match, attributes) => `<body${attributes}>\n    <script id="answer-recorder-config" type="application/json">${safeJson(config)}</script>`);

if (/(?:<script\b[^>]+\bsrc=|<link\b[^>]+\b(?:href|src)=)/i.test(html)) {
  throw new Error("单文件构建仍包含外部脚本或样式资源。");
}

await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, `<!doctype html>\n${html.slice(html.indexOf("<html"))}`, "utf8");
console.log(`已生成单文件答题卡：${outputPath}`);
