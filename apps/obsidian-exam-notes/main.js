"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/main.ts
var main_exports = {};
__export(main_exports, {
  default: () => ExamNotesPlugin
});
module.exports = __toCommonJS(main_exports);
var import_obsidian = require("obsidian");

// src/markdown.js
var QUESTION_HEADER = /^>\s*\[!exam-question\]\s*(?<title>.*)$/;
var CALLOUT_LINE = /^>\s?(.*)$/;
var BLOCK_ID = /^\^([A-Za-z0-9_-]+)\s*$/;
var PERSONAL_FOOTNOTE = /^exam-[A-Za-z0-9_-]+-note-(\d+)$/;
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
    endOffset: lines[Math.min(cursor, lines.length - 1)]?.start ?? lines[lines.length - 1]?.end ?? 0
  };
}
function findExamQuestions(source) {
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
function parseExamQuestion(source, lineOrOffset = 0) {
  const questions = findExamQuestions(source);
  const line = typeof lineOrOffset === "number" && lineOrOffset >= 0 ? source.slice(0, lineOrOffset).split("\n").length - 1 : 0;
  return questions.find((question) => question.headerLine <= line && line <= question.endLine + 12) || questions[0] || null;
}
function offsetToLine(source, offset) {
  return source.slice(0, Math.max(0, offset)).split("\n").length - 1;
}
function findQuestionAtOffsets(source, start, end = start) {
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
function extractBlockById(source, blockId) {
  return calloutByBlockId(source, String(blockId).replace(/^\^/, ""));
}
function stripPersonalFootnotesSafe(text) {
  const value = String(text);
  const ids = /* @__PURE__ */ new Set();
  for (const match of value.matchAll(/\[\^([^\]]+)\]/g)) {
    if (PERSONAL_FOOTNOTE.test(match[1])) ids.add(match[1]);
  }
  const kept = value.split("\n").filter((line) => ![...ids].some((id) => line.startsWith(`[^${id}]:`)));
  let result = kept.join("\n");
  for (const id of ids) result = result.replaceAll(`[^${id}]`, "");
  return result.replace(/\n{3,}/g, "\n\n").trim();
}
function stripPersonalFootnotes(text) {
  return stripPersonalFootnotesSafe(text);
}
function stripQuestionDecorations(question) {
  const body = question.innerLines.join("\n").trim();
  return stripPersonalFootnotes(body).split("\n").filter((line) => !/^材料：/.test(line) && !/^标签：/.test(line) && !/^关联：/.test(line)).join("\n").replace(/\n{3,}/g, "\n\n").trim();
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
  return definitions.length ? `${copied.trim()}

${definitions.join("\n")}
` : `${copied.trim()}
`;
}
function copyQuestionMarkdown(source, question) {
  const current = question || parseExamQuestion(source, 0);
  if (!current) throw new Error("\u5F53\u524D\u6587\u4EF6\u6CA1\u6709 exam-question \u9898\u76EE\u5361\u7247");
  const materialBlocks = [];
  for (const id of current.materialIds || []) {
    const block = extractBlockById(source, id);
    if (!block) continue;
    const body2 = stripPersonalFootnotes(block.innerLines.join("\n").trim());
    if (body2) materialBlocks.push(body2);
  }
  const body = stripQuestionDecorations(current);
  const number = current.number ? `${current.number}. ` : "";
  const copied = [...materialBlocks, `${number}${body}`].filter(Boolean).join("\n\n").trim();
  return appendReferencedSourceFootnotes(copied, source);
}
function createQuestionLink(filePath, blockId, title = "\u9898\u76EE") {
  const id = String(blockId).replace(/^\^/, "");
  if (!id) throw new Error("\u9898\u76EE\u7F3A\u5C11\u5757\u7F16\u53F7");
  return `[[${filePath}#^${id}|${title}]]`;
}
function nextOptionFootnoteId(source, blockId) {
  const prefix = `exam-${String(blockId).replace(/^\^/, "")}-note-`;
  let next = 1;
  for (const match of String(source).matchAll(/\[\^(exam-[A-Za-z0-9_-]+-note-(\d+))\]/g)) {
    if (match[1].startsWith(prefix)) next = Math.max(next, Number(match[2]) + 1);
  }
  return `${prefix}${next}`;
}
function insertOptionFootnote(source, question, start, end, note) {
  if (!question || !question.blockId) throw new Error("\u9898\u76EE\u7F3A\u5C11\u5757\u7F16\u53F7");
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < question.startOffset || end < start || end > source.length) {
    throw new Error("\u9009\u533A\u4E0D\u5728\u9898\u76EE\u5361\u7247\u5185");
  }
  if (offsetToLine(source, end) > question.endLine) throw new Error("\u9009\u533A\u4E0D\u80FD\u8DE8\u51FA\u9898\u76EE\u5361\u7247");
  const value = String(note || "").trim();
  if (!value) throw new Error("\u7B14\u8BB0\u5185\u5BB9\u4E0D\u80FD\u4E3A\u7A7A");
  const id = nextOptionFootnoteId(source, question.blockId);
  const marker = `[^${id}]`;
  const definition = `[^${id}]: ${value}`;
  const withMarker = source.slice(0, end) + marker + source.slice(end);
  const separator = withMarker.endsWith("\n") ? "\n" : "\n\n";
  return { source: withMarker + separator + definition + "\n", id, marker, definition };
}

// src/main.ts
function positionToOffset(source, position) {
  const lines = source.split("\n");
  let offset = 0;
  for (let index = 0; index < position.line; index += 1) offset += (lines[index] ?? "").length + 1;
  return offset + position.ch;
}
function questionNumberFromTitle(title) {
  return (title.match(/第\s*(\d+)\s*题/) || [])[1] || null;
}
var ExamNotesPlugin = class extends import_obsidian.Plugin {
  async onload() {
    this.addCommand({
      id: "copy-exam-question",
      name: "\u590D\u5236\u5F53\u524D\u9898\u76EE",
      editorCallback: (editor, view) => void this.copyFromEditor(editor, view)
    });
    this.addCommand({
      id: "copy-exam-question-link",
      name: "\u590D\u5236\u5F53\u524D\u9898\u76EE\u94FE\u63A5",
      editorCallback: (editor, view) => void this.copyLinkFromEditor(editor, view)
    });
    this.addCommand({
      id: "add-exam-option-footnote",
      name: "\u4E3A\u5F53\u524D\u9009\u9879\u6DFB\u52A0\u811A\u6CE8",
      editorCallback: (editor, view) => void this.addFootnoteFromEditor(editor, view)
    });
    this.registerMarkdownPostProcessor((element, context) => {
      const callouts = [];
      if (element.matches(".callout[data-callout='exam-question']")) callouts.push(element);
      callouts.push(...Array.from(element.querySelectorAll(".callout[data-callout='exam-question']")));
      for (const callout of callouts) {
        const section = context.getSectionInfo(callout);
        this.addRenderedActions(callout, context.sourcePath, section?.lineStart);
      }
    });
    this.registerEvent(this.app.workspace.on("editor-menu", (menu, editor, view) => {
      const source = editor.getValue();
      const cursor = editor.getCursor();
      const offset = positionToOffset(source, cursor);
      const question = findQuestionAtOffsets(source, offset, offset);
      if (!question) return;
      menu.addItem((item) => item.setTitle("\u590D\u5236\u5F53\u524D\u9898\u76EE").setIcon("copy").onClick(() => void this.copyFromEditor(editor, view)));
      menu.addItem((item) => item.setTitle("\u590D\u5236\u5F53\u524D\u9898\u76EE\u94FE\u63A5").setIcon("link").onClick(() => void this.copyLinkFromEditor(editor, view)));
      menu.addItem((item) => item.setTitle("\u4E3A\u5F53\u524D\u9009\u9879\u6DFB\u52A0\u811A\u6CE8").setIcon("pencil").onClick(() => void this.addFootnoteFromEditor(editor, view)));
    }));
  }
  async readFile(path) {
    const abstract = this.app.vault.getAbstractFileByPath(path);
    if (!(abstract instanceof import_obsidian.TFile)) return null;
    return { file: abstract, source: await this.app.vault.read(abstract) };
  }
  async writeClipboard(value, message) {
    await navigator.clipboard.writeText(value);
    new import_obsidian.Notice(message);
  }
  questionFromEditor(editor) {
    const source = editor.getValue();
    const cursor = editor.getCursor();
    const offset = positionToOffset(source, cursor);
    return { source, offset, question: findQuestionAtOffsets(source, offset, offset) };
  }
  async copyFromEditor(editor, _view) {
    const current = this.questionFromEditor(editor);
    if (!current.question) {
      new import_obsidian.Notice("\u8BF7\u628A\u5149\u6807\u653E\u5728 exam-question \u9898\u76EE\u5361\u7247\u5185");
      return;
    }
    try {
      await this.writeClipboard(copyQuestionMarkdown(current.source, current.question), "\u9898\u76EE\u5DF2\u590D\u5236");
    } catch (error) {
      new import_obsidian.Notice(`\u590D\u5236\u5931\u8D25\uFF1A${String(error)}`);
    }
  }
  async copyLinkFromEditor(editor, view) {
    const current = this.questionFromEditor(editor);
    if (!current.question?.blockId || !view.file) {
      new import_obsidian.Notice("\u5F53\u524D\u5149\u6807\u4E0D\u5728\u53EF\u5F15\u7528\u7684\u9898\u76EE\u5361\u7247\u5185");
      return;
    }
    try {
      const link = createQuestionLink(view.file.path, current.question.blockId, current.question.title);
      await this.writeClipboard(link, "\u9898\u76EE\u94FE\u63A5\u5DF2\u590D\u5236");
    } catch (error) {
      new import_obsidian.Notice(`\u590D\u5236\u94FE\u63A5\u5931\u8D25\uFF1A${String(error)}`);
    }
  }
  async addFootnoteFromEditor(editor, _view) {
    const source = editor.getValue();
    const cursor = editor.getCursor();
    let from = editor.getCursor("from");
    let to = editor.getCursor("to");
    let start = positionToOffset(source, from);
    let end = positionToOffset(source, to);
    if (start === end) {
      const line = editor.getLine(cursor.line);
      const option = line.match(/\b[A-D]\.[^\n]*/);
      if (!option) {
        new import_obsidian.Notice("\u8BF7\u9009\u62E9\u4E00\u4E2A\u9009\u9879\u7247\u6BB5\uFF0C\u6216\u628A\u5149\u6807\u653E\u5728 A-D \u9009\u9879\u884C");
        return;
      }
      start = positionToOffset(source, { line: cursor.line, ch: option.index ?? 0 });
      end = start + option[0].length;
      from = { line: cursor.line, ch: option.index ?? 0 };
      to = { line: cursor.line, ch: (option.index ?? 0) + option[0].length };
    }
    const question = findQuestionAtOffsets(source, start, end);
    if (!question) {
      new import_obsidian.Notice("\u9009\u9879\u5FC5\u987B\u5B8C\u5168\u4F4D\u4E8E\u540C\u4E00\u9053 exam-question \u9898\u76EE\u5185");
      return;
    }
    const note = window.prompt("\u9009\u9879\u811A\u6CE8", "")?.trim();
    if (!note) return;
    try {
      const result = insertOptionFootnote(source, question, start, end, note);
      editor.replaceRange(result.marker, to, to);
      const lastLine = editor.lastLine();
      const endPosition = { line: lastLine, ch: editor.getLine(lastLine).length };
      const separator = editor.getValue().endsWith("\n") ? "\n" : "\n\n";
      editor.replaceRange(`${separator}${result.definition}
`, endPosition, endPosition);
      new import_obsidian.Notice("\u9009\u9879\u811A\u6CE8\u5DF2\u6DFB\u52A0");
    } catch (error) {
      new import_obsidian.Notice(`\u6DFB\u52A0\u811A\u6CE8\u5931\u8D25\uFF1A${String(error)}`);
    }
  }
  async addRenderedActions(callout, sourcePath, sourceLine) {
    if (callout.dataset.examActions === "true") return;
    const titleElement = callout.querySelector(".callout-title");
    const titleText = callout.querySelector(".callout-title-inner")?.textContent?.trim() || "";
    if (!titleElement || !titleText) return;
    callout.dataset.examActions = "true";
    const actions = document.createElement("span");
    actions.className = "exam-question-actions";
    actions.dataset.examAction = "toolbar";
    actions.append(
      this.actionButton("\u590D\u5236\u9898\u76EE", async () => this.copyRenderedQuestion(sourcePath, titleText, sourceLine)),
      this.actionButton("\u590D\u5236\u94FE\u63A5", async () => this.copyRenderedLink(sourcePath, titleText, sourceLine))
    );
    titleElement.appendChild(actions);
  }
  actionButton(label, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "exam-question-action";
    button.dataset.examAction = label;
    button.textContent = label;
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      void action();
    });
    return button;
  }
  async findRenderedQuestion(sourcePath, title, sourceLine) {
    const loaded = await this.readFile(sourcePath);
    if (!loaded) return null;
    const questions = findExamQuestions(loaded.source);
    if (typeof sourceLine === "number") {
      const byLine = questions.find((item) => item.headerLine <= sourceLine && sourceLine <= item.endLine + 12);
      if (byLine) return { ...loaded, question: byLine };
    }
    const number = questionNumberFromTitle(title);
    const question = questions.find((item) => item.title === title || number && item.number === number);
    return question ? { ...loaded, question } : null;
  }
  async copyRenderedQuestion(sourcePath, title, sourceLine) {
    const found = await this.findRenderedQuestion(sourcePath, title, sourceLine);
    if (!found) {
      new import_obsidian.Notice("\u627E\u4E0D\u5230\u5BF9\u5E94\u7684\u9898\u76EE\u6E90\u6587\u672C");
      return;
    }
    try {
      await this.writeClipboard(copyQuestionMarkdown(found.source, found.question), "\u9898\u76EE\u5DF2\u590D\u5236");
    } catch (error) {
      new import_obsidian.Notice(`\u590D\u5236\u5931\u8D25\uFF1A${String(error)}`);
    }
  }
  async copyRenderedLink(sourcePath, title, sourceLine) {
    const found = await this.findRenderedQuestion(sourcePath, title, sourceLine);
    if (!found?.question.blockId) {
      new import_obsidian.Notice("\u627E\u4E0D\u5230\u5BF9\u5E94\u7684\u9898\u76EE\u5757\u7F16\u53F7");
      return;
    }
    try {
      await this.writeClipboard(createQuestionLink(found.file.path, found.question.blockId, found.question.title), "\u9898\u76EE\u94FE\u63A5\u5DF2\u590D\u5236");
    } catch (error) {
      new import_obsidian.Notice(`\u590D\u5236\u94FE\u63A5\u5931\u8D25\uFF1A${String(error)}`);
    }
  }
};
