import test from "node:test";
import assert from "node:assert/strict";
import {
  copyQuestionMarkdown,
  createQuestionLink,
  findExamQuestions,
  findQuestionAtOffsets,
  insertOptionFootnote,
  stripPersonalFootnotes,
} from "../src/markdown.js";

const source = `# 试卷

> [!exam-material] 共享材料
> 材料文字
> ![[attachments/table.png]]

^m-material-01

> [!exam-question] 第 66 题
> 题干文字
>
> A.甲[^exam-q66-note-1]
> B.乙[^source-note]
> C.丙
> D.丁

^q66

标签：#政治
关联：
材料：[[#^m-material-01|共享材料]]

> [!success]- 答案与解析
> 答案

> [!note]- 我的笔记
> 用户笔记

[^exam-q66-note-1]: 旧的个人选项笔记
[^source-note]: 原卷注释
`;

test("parses only exam question callouts and stable blocks", () => {
  const questions = findExamQuestions(source);
  assert.equal(questions.length, 1);
  assert.equal(questions[0].number, "66");
  assert.equal(questions[0].blockId, "q66");
  assert.deepEqual(questions[0].materialIds, ["m-material-01"]);
});
test("copies question with expanded material and removes personal notes", () => {
  const question = findExamQuestions(source)[0];
  const copied = copyQuestionMarkdown(source, question);
  assert.match(copied, /材料文字/);
  assert.match(copied, /!\[\[attachments\/table\.png\]\]/);
  assert.match(copied, /66\. 题干文字/);
  assert.match(copied, /A\.甲/);
  assert.doesNotMatch(copied, /答案|用户笔记|exam-q66-note|\^q66|exam-question/);
  assert.match(copied, /\[\^source-note\]/);
});

test("creates a stable block link", () => {
  assert.equal(createQuestionLink("行测/2025.md", "q66", "第 66 题"), "[[行测/2025.md#^q66|第 66 题]]");
});

test("adds an option footnote within one question", () => {
  const question = findExamQuestions(source)[0];
  const start = source.indexOf("A.甲");
  const result = insertOptionFootnote(source, question, start, start + 3, "容易把甲看成乙");
  assert.match(result.source, /A\.甲\[\^exam-q66-note-2\]/);
  assert.match(result.source, /\[\^exam-q66-note-2\]: 容易把甲看成乙/);
  assert.throws(() => insertOptionFootnote(source, question, source.indexOf("用户笔记"), source.indexOf("用户笔记") + 4, "x"));
});

test("strips only plugin personal footnotes", () => {
  const value = "A[^exam-q1-note-1] B[^source-note]\n\n[^exam-q1-note-1]: memo\n[^source-note]: source";
  const stripped = stripPersonalFootnotes(value);
  assert.equal(stripped, "A B[^source-note]\n\n[^source-note]: source");
});
