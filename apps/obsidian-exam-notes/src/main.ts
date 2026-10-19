import { Notice, Plugin, TFile } from "obsidian";
import {
  copyQuestionMarkdown,
  createQuestionLink,
  findExamQuestions,
  findQuestionAtOffsets,
  insertOptionFootnote,
} from "./markdown.js";

function positionToOffset(source: string, position: { line: number; ch: number }): number {
  const lines = source.split("\n");
  let offset = 0;
  for (let index = 0; index < position.line; index += 1) offset += (lines[index] ?? "").length + 1;
  return offset + position.ch;
}
function questionNumberFromTitle(title: string): string | null {
  return (title.match(/第\s*(\d+)\s*题/) || [])[1] || null;
}

export default class ExamNotesPlugin extends Plugin {
  async onload() {
    this.addCommand({
      id: "copy-exam-question",
      name: "复制当前题目",
      editorCallback: (editor, view) => void this.copyFromEditor(editor, view),
    });
    this.addCommand({
      id: "copy-exam-question-link",
      name: "复制当前题目链接",
      editorCallback: (editor, view) => void this.copyLinkFromEditor(editor, view),
    });
    this.addCommand({
      id: "add-exam-option-footnote",
      name: "为当前选项添加脚注",
      editorCallback: (editor, view) => void this.addFootnoteFromEditor(editor, view),
    });

    this.registerMarkdownPostProcessor((element, context) => {
      const callouts: HTMLElement[] = [];
      if (element.matches(".callout[data-callout='exam-question']")) callouts.push(element);
      callouts.push(...Array.from(element.querySelectorAll<HTMLElement>(".callout[data-callout='exam-question']")));
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
      menu.addItem((item) => item.setTitle("复制当前题目").setIcon("copy").onClick(() => void this.copyFromEditor(editor, view)));
      menu.addItem((item) => item.setTitle("复制当前题目链接").setIcon("link").onClick(() => void this.copyLinkFromEditor(editor, view)));
      menu.addItem((item) => item.setTitle("为当前选项添加脚注").setIcon("pencil").onClick(() => void this.addFootnoteFromEditor(editor, view)));
    }));
  }

  private async readFile(path: string): Promise<{ file: TFile; source: string } | null> {
    const abstract = this.app.vault.getAbstractFileByPath(path);
    if (!(abstract instanceof TFile)) return null;
    return { file: abstract, source: await this.app.vault.read(abstract) };
  }

  private async writeClipboard(value: string, message: string) {
    await navigator.clipboard.writeText(value);
    new Notice(message);
  }

  private questionFromEditor(editor: any) {
    const source = editor.getValue();
    const cursor = editor.getCursor();
    const offset = positionToOffset(source, cursor);
    return { source, offset, question: findQuestionAtOffsets(source, offset, offset) };
  }

  private async copyFromEditor(editor: any, _view: any) {
    const current = this.questionFromEditor(editor);
    if (!current.question) {
      new Notice("请把光标放在 exam-question 题目卡片内");
      return;
    }
    try {
      await this.writeClipboard(copyQuestionMarkdown(current.source, current.question), "题目已复制");
    } catch (error) {
      new Notice(`复制失败：${String(error)}`);
    }
  }

  private async copyLinkFromEditor(editor: any, view: any) {
    const current = this.questionFromEditor(editor);
    if (!current.question?.blockId || !view.file) {
      new Notice("当前光标不在可引用的题目卡片内");
      return;
    }
    try {
      const link = createQuestionLink(view.file.path, current.question.blockId, current.question.title);
      await this.writeClipboard(link, "题目链接已复制");
    } catch (error) {
      new Notice(`复制链接失败：${String(error)}`);
    }
  }

  private async addFootnoteFromEditor(editor: any, _view: any) {
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
        new Notice("请选择一个选项片段，或把光标放在 A-D 选项行");
        return;
      }
      start = positionToOffset(source, { line: cursor.line, ch: option.index ?? 0 });
      end = start + option[0].length;
      from = { line: cursor.line, ch: option.index ?? 0 };
      to = { line: cursor.line, ch: (option.index ?? 0) + option[0].length };
    }
    const question = findQuestionAtOffsets(source, start, end);
    if (!question) {
      new Notice("选项必须完全位于同一道 exam-question 题目内");
      return;
    }
    const note = window.prompt("选项脚注", "")?.trim();
    if (!note) return;
    try {
      const result = insertOptionFootnote(source, question, start, end, note);
      editor.replaceRange(result.marker, to, to);
      const lastLine = editor.lastLine();
      const endPosition = { line: lastLine, ch: editor.getLine(lastLine).length };
      const separator = editor.getValue().endsWith("\n") ? "\n" : "\n\n";
      editor.replaceRange(`${separator}${result.definition}\n`, endPosition, endPosition);
      new Notice("选项脚注已添加");
    } catch (error) {
      new Notice(`添加脚注失败：${String(error)}`);
    }
  }

  private async addRenderedActions(callout: HTMLElement, sourcePath: string, sourceLine?: number) {
    if (callout.dataset.examActions === "true") return;
    const titleElement = callout.querySelector<HTMLElement>(".callout-title");
    const titleText = callout.querySelector<HTMLElement>(".callout-title-inner")?.textContent?.trim() || "";
    if (!titleElement || !titleText) return;
    callout.dataset.examActions = "true";
    const actions = document.createElement("span");
    actions.className = "exam-question-actions";
    actions.dataset.examAction = "toolbar";
    actions.append(
      this.actionButton("复制题目", async () => this.copyRenderedQuestion(sourcePath, titleText, sourceLine)),
      this.actionButton("复制链接", async () => this.copyRenderedLink(sourcePath, titleText, sourceLine)),
    );
    titleElement.appendChild(actions);
  }

  private actionButton(label: string, action: () => Promise<void>) {
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

  private async findRenderedQuestion(sourcePath: string, title: string, sourceLine?: number) {
    const loaded = await this.readFile(sourcePath);
    if (!loaded) return null;
    const questions = findExamQuestions(loaded.source);
    if (typeof sourceLine === "number") {
      const byLine = questions.find((item) => item.headerLine <= sourceLine && sourceLine <= item.endLine + 12);
      if (byLine) return { ...loaded, question: byLine };
    }
    const number = questionNumberFromTitle(title);
    const question = questions.find((item) => item.title === title || (number && item.number === number));
    return question ? { ...loaded, question } : null;
  }

  private async copyRenderedQuestion(sourcePath: string, title: string, sourceLine?: number) {
    const found = await this.findRenderedQuestion(sourcePath, title, sourceLine);
    if (!found) {
      new Notice("找不到对应的题目源文本");
      return;
    }
    try {
      await this.writeClipboard(copyQuestionMarkdown(found.source, found.question), "题目已复制");
    } catch (error) {
      new Notice(`复制失败：${String(error)}`);
    }
  }

  private async copyRenderedLink(sourcePath: string, title: string, sourceLine?: number) {
    const found = await this.findRenderedQuestion(sourcePath, title, sourceLine);
    if (!found?.question.blockId) {
      new Notice("找不到对应的题目块编号");
      return;
    }
    try {
      await this.writeClipboard(createQuestionLink(found.file.path, found.question.blockId, found.question.title), "题目链接已复制");
    } catch (error) {
      new Notice(`复制链接失败：${String(error)}`);
    }
  }
}
