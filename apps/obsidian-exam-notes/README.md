# 公考题目插件（obsidian-exam-notes）

版本：`0.2.0`

这是“公考试卷识别”Skill 的 Obsidian 配套插件，服务于 `exam-lite-v1` 题目导出。它只处理 `exam-question` 题目 Callout，不改写普通 Callout，也不会在打开文件时重写 Markdown。MinerU 只是上游候选解析器，插件不依赖 MinerU 运行。

## 手动安装

1. 在 Obsidian 库中打开“设置 → 第三方插件 → 已安装插件”，确认允许第三方插件。
2. 将本目录中的 `main.js`、`manifest.json`、`styles.css` 复制到库内：

   `.obsidian/plugins/obsidian-exam-notes/`

3. 在 Obsidian 的第三方插件列表中启用“Obsidian 题目插件”。交付 ZIP 已经包含这三个运行文件，解压后目录名应保持为 `obsidian-exam-notes`。

日常使用不需要把插件源码、`node_modules` 或 TypeScript 文件复制到库中。停用或卸载插件不会删除题目、附件、块引用、脚注和个人笔记；普通 Markdown 仍然可读。

## 题目格式

Skill 导出的题目类似：

```markdown
> [!exam-question] 第 66 题
> 张某8:00开车从A地出发……
>
> A. 10/13
> B. 13/10
> C. 20/13
> D. 13/5

^q66

标签：
关联：

> [!success]- 答案与解析
> 待补充。

> [!note]- 我的笔记
>
```

共享材料用单独的 `exam-material` Callout 和 `^m-material-XX` 块编号。题目卡片内的材料链接在复制时会展开；同一材料在文件中只保存一份。图片使用导出包内的 `attachments/` 路径，表格保留为 Markdown/HTML 原文。跨库迁移时要把附件目录一起带走。

## 功能

- **复制当前题目**：在阅读视图/实时预览的题目卡片上点击复制按钮，或在源码编辑器中把光标放入题目后运行命令。复制内容包含共享材料、题干、选项、图片、表格、公式和原卷注释；不包含 Callout 包装、块编号、答案、个人笔记、个人脚注引用或个人脚注定义。
- **复制当前题目链接**：复制当前文件内稳定的 `[[文件路径#^q66|第 66 题]]` 双链。链接使用源文件路径，不从嵌入视图推断路径。
- **为当前选项添加脚注**：选中一个选项片段，或把光标放在 A/B/C/D 选项行中，运行命令并输入注释。脚注引用和定义一次插入，支持 Obsidian 撤销；跨越多个题目时拒绝操作。

原卷脚注（非 `exam-note-` 编号）在复制时保留。用户脚注使用 `exam-note-题目块编号-序号` 形式；复制题目会移除它们，避免把个人记录带到题目副本中。标准脚注语法负责显示、跳转和返回；若主题对 Callout 内脚注呈现不同，底层 Markdown 仍保持可编辑。

题目卡片在浅色和深色主题中都有边框与间距。答案解析和个人笔记是原生折叠 Callout，插件不替用户填入答案，也不另建题库数据库。

## 与公考试卷识别 Skill 配合

先完成 `skills/gongkao-exam-reader/` 中 `exam-lite-v1` 的 A/B/C、普通排版和结构验证，再执行：

```bash
python3 ../../skills/gongkao-exam-reader/scripts/ocr_review.py exam-lite-obsidian-export \
  --run /absolute/work/exam \
  --candidate /absolute/work/exam/exam-lite-final.formatted-v2.json \
  --layout /absolute/work/exam/mineru-layout.json \
  --exam-id 2025国考行测地市级 \
  --output-dir /absolute/work/exam/obsidian-export
```

导出默认拒绝缺少 revision 2 完整验收的 run；这是为了避免把旧 exam-lite、single-pass 或 legacy 报告伪装成新的题目结构。仅检查草稿时可显式增加 `--allow-draft`。每次重新导出都写入新的输出目录，不覆盖已经有用户笔记的文件；source-map 只对应该次导出快照。

## 开发与构建

```bash
npm install
npm test
npm run build
```

构建结果是根目录的 `main.js`，配合 `manifest.json` 和 `styles.css` 即可手动安装。插件 ZIP 不包含源码和依赖目录。
