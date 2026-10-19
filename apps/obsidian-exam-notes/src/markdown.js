/** Pure Markdown operations used by the Obsidian plugin and its tests. */

const QUESTION_HEADER = /^>\s*\[!exam-question\]\s*(?<title>.*)$/;
const CALLOUT_LINE = /^>\s?(.*)$/;
const BLOCK_ID = /^\^([A-Za-z0-9_-]+)\s*$/;
const PERSONAL_FOOTNOTE = /^exam-[A-Za-z0-9_-]+-note-(\d+)$/;

function linesWithOffsets(source) {
  const lines = [];
  let offset = 0;
  for (const line of source.split("\n")) {
    lines.push({ line, start: offset, end: offset + line.length });
    offset += line.length + 1;
  }
  return lines;
}
function stripQuote(line) {
  const match = line.match(CALLOUT_LINE);
  return match ? match[1] : line;
}

function parseQuestionAt(lines, index) {
  const header = lines[index].line.match(QUESTION_HEADER);
  if (!header) return null;
  let cursor = index + 1;
  const innerLines = [];
  while (cursor < lines.length && (lines[cursor].line === "" || lines[cursor].line.startsWith(">"))) {
    if (lines[cursor].line === "") break;
    innerLines.push(stripQuote(lines[cursor].line));
    cursor += 1;
  }
  let blockLine = cursor;
  while (blockLine < Math.min(lines.length, cursor + 4) && lines[blockLine].line.trim() === "") blockLine += 1;
  const blockMatch = blockLine < lines.length ? lines[blockLine].line.trim().match(BLOCK_ID) : null;
  const blockId = blockMatch ? blockMatch[1] : null;
  let scan = blockLine + (blockMatch ? 1 : 0);
  const materialIds = [];
  while (scan < Math.min(lines.length, blockLine + 8)) {
    const materialLine = lines[scan].line.match(/^材料：(.+)$/);
    if (materialLine) {
      for (const match of materialLine[1].matchAll(/#\^([A-Za-z0-9_-]+)/g)) materialIds.push(match[1]);
    }
    if (lines[scan].line.startsWith("> [!success]") || lines[scan].line.startsWith("> [!note]")) break;
    scan += 1;
  }
  const title = header.groups?.title ?? header[1] ?? "";
  const number = (title.match(/第\s*(\d+)\s*题/) || [])[1] || null;
  return {
    title: title.trim(),
    number,
    blockId,
    materialIds,
    innerLines,
    headerLine: index,
    endLine: cursor,
    startOffset: lines[index].start,
    endOffset: lines[Math.min(cursor, lines.length - 1)]?.start ?? lines[lines.length - 1]?.end ?? 0,
  };
}

export function findExamQuestions(source) {
  const lines = linesWithOffsets(source);
  const questions = [];
  for (let index = 0; index < lines.length; index += 1) {
    if (QUESTION_HEADER.test(lines[index].line)) {
      const question = parseQuestionAt(lines, index);
      if (question) questions.push(question);
    }
  }
  return questions;
}

export function parseExamQuestion(source, lineOrOffset = 0) {
  const questions = findExamQuestions(source);
  const line = typeof lineOrOffset === "number" && lineOrOffset >= 0
    ? (source.slice(0, lineOrOffset).split("\n").length - 1)
    : 0;
  return questions.find((question) => question.headerLine <= line && line <= question.endLine + 12) || questions[0] || null;
}

export function offsetToLine(source, offset) {
  return source.slice(0, Math.max(0, offset)).split("\n").length - 1;
}

export function findQuestionAtOffsets(source, start, end = start) {
  const questions = findExamQuestions(source);
  const leftLine = offsetToLine(source, start);
  const rightLine = offsetToLine(source, end);
  const question = questions.find((item) => item.headerLine <= leftLine && rightLine <= item.endLine);
  return question || null;
}

function calloutByBlockId(source, blockId) {
  const lines = linesWithOffsets(source);
  const target = lines.findIndex((item) => item.line.trim() === `^${blockId}`);
  if (target < 0) return null;
  let header = target - 1;
  while (header >= 0 && lines[header].line.trim() === "") header -= 1;
  while (header >= 0 && lines[header].line.startsWith(">")) header -= 1;
  header += 1;
  const headerMatch = lines[header]?.line.match(/^>\s*\[!([^\]]+)\]\s*(.*)$/);
  if (!headerMatch) return null;
  const innerLines = [];
  let cursor = header + 1;
  while (cursor < target && (lines[cursor].line === "" || lines[cursor].line.startsWith(">"))) {
    if (lines[cursor].line !== "") innerLines.push(stripQuote(lines[cursor].line));
    cursor += 1;
  }
  return { blockId, kind: headerMatch[1], title: headerMatch[2].trim(), innerLines, headerLine: header, blockLine: target };
}

export function extractBlockById(source, blockId) {
  return calloutByBlockId(source, String(blockId).replace(/^\^/, ""));
}

function stripPersonalFootnotesSafe(text) {
  const value = String(text);
  const ids = new Set();
  for (const match of value.matchAll(/\[\^([^\]]+)\]/g)) {
    if (PERSONAL_FOOTNOTE.test(match[1])) ids.add(match[1]);
  }
  const kept = value.split("\n").filter((line) => ![...ids].some((id) => line.startsWith(`[^${id}]:`)));
  let result = kept.join("\n");
  for (const id of ids) result = result.replaceAll(`[^${id}]`, "");
  return result.replace(/\n{3,}/g, "\n\n").trim();
}

export function stripPersonalFootnotes(text) {
  return stripPersonalFootnotesSafe(text);
}

function stripQuestionDecorations(question) {
  const body = question.innerLines.join("\n").trim();
  return stripPersonalFootnotes(body)
    .split("\n")
    .filter((line) => !/^材料：/.test(line) && !/^标签：/.test(line) && !/^关联：/.test(line))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function appendReferencedSourceFootnotes(copied, source) {
  const ids = [];
  for (const match of copied.matchAll(/\[\^([^\]]+)\]/g)) {
    if (!PERSONAL_FOOTNOTE.test(match[1]) && !ids.includes(match[1])) ids.push(match[1]);
  }
  const definitions = [];
  for (const id of ids) {
    const line = String(source).split("\n").find((candidate) => candidate.startsWith(`[^${id}]:`));
    if (line) definitions.push(line);
  }
  return definitions.length ? `${copied.trim()}\n\n${definitions.join("\n")}\n` : `${copied.trim()}\n`;
}

export function copyQuestionMarkdown(source, question) {
  const current = question || parseExamQuestion(source, 0);
  if (!current) throw new Error("当前文件没有 exam-question 题目卡片");
  const materialBlocks = [];
  for (const id of current.materialIds || []) {
    const block = extractBlockById(source, id);
    if (!block) continue;
    const body = stripPersonalFootnotes(block.innerLines.join("\n").trim());
    if (body) materialBlocks.push(body);
  }
  const body = stripQuestionDecorations(current);
  const number = current.number ? `${current.number}. ` : "";
  const copied = [...materialBlocks, `${number}${body}`].filter(Boolean).join("\n\n").trim();
  return appendReferencedSourceFootnotes(copied, source);
}

export function createQuestionLink(filePath, blockId, title = "题目") {
  const id = String(blockId).replace(/^\^/, "");
  if (!id) throw new Error("题目缺少块编号");
  return `[[${filePath}#^${id}|${title}]]`;
}

export function nextOptionFootnoteId(source, blockId) {
  const prefix = `exam-${String(blockId).replace(/^\^/, "")}-note-`;
  let next = 1;
  for (const match of String(source).matchAll(/\[\^(exam-[A-Za-z0-9_-]+-note-(\d+))\]/g)) {
    if (match[1].startsWith(prefix)) next = Math.max(next, Number(match[2]) + 1);
  }
  return `${prefix}${next}`;
}

export function insertOptionFootnote(source, question, start, end, note) {
  if (!question || !question.blockId) throw new Error("题目缺少块编号");
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < question.startOffset || end < start || end > source.length) {
    throw new Error("选区不在题目卡片内");
  }
  if (offsetToLine(source, end) > question.endLine) throw new Error("选区不能跨出题目卡片");
  const value = String(note || "").trim();
  if (!value) throw new Error("笔记内容不能为空");
  const id = nextOptionFootnoteId(source, question.blockId);
  const marker = `[^${id}]`;
  const definition = `[^${id}]: ${value}`;
  const withMarker = source.slice(0, end) + marker + source.slice(end);
  const separator = withMarker.endsWith("\n") ? "\n" : "\n\n";
  return { source: withMarker + separator + definition + "\n", id, marker, definition };
}
