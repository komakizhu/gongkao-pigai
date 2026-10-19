---
name: gongkao-exam-reader
description: "识别和复核带文字层的公考试卷 PDF，保留题目、选项、表格、图片与来源映射，并在用户明确要求时导出可在 Obsidian 中整理的题目笔记；用于处理国考或省考试卷、exam-lite-v1 复核、结构化导出或 Obsidian 题目导入。 Review text-layer Chinese civil-service exam PDFs with exam-lite-v1, preserve questions, options, tables, media, and source maps, and export Obsidian-ready question notes when requested; use for national or provincial exam review, structured export, or Obsidian question import."
---

# 公考试卷识别（Gongkao Exam Reader）

本技能负责公考试卷的文字与结构复核，以及可追溯的 Markdown/Obsidian 题目导出。它处理试卷材料，不判断用户作答正误，也不生成参考答案。通用 `mineru-ocrs` Skill 继续独立维护；这里仅保留公考试卷的 `exam-lite-v1` 流程。

## 适用边界

- 输入以带文字层的国考、省考试卷 PDF 为主；流程会记录文字层缺口、空白页和纯图片页。
- 使用 `exam-lite-v1` 的 A 文字复核、B 两页分片结构复核、C 改动验收，并保留页码、坐标、素材和来源映射。
- 只有完成验收、排版和结构验证，且用户明确要求时，才导出 Obsidian 题目包。
- 复杂扫描卷、教材和普通 OCR 任务交给独立的 `mineru-ocrs` Skill，不在本技能内猜测题目或答案。

## 工作流程

每份试卷使用新的运行目录，源 PDF 只读。先执行 `exam-lite-prepare`，再按顺序完成页面渲染、A/B 任务包、合并、应用、C 验收、排版、导出和验证。任务包必须记录真实上下文、页覆盖、版本、重试和并行事件；缺报告、缺验收、版本冲突或来源映射不完整时不能标记完成。

```text
输入检查 → A 文字复核 + B 两页分片 → 合并 → C 改动验收
      → 确定性排版 → Markdown / Obsidian 导出 → 结构验证
```

正式 Markdown 和 Obsidian 导出会从当前运行目录的原始候选、合并决定和验收决定重建并核对验收内容。自动验收、人工接受、回退以及由验收内容生成的确定性排版文件可以导出；另传改写候选或修改已验收文件后不能冒充正式结果。若旧运行目录缺少当前应用、验收报告或重建所需资料，会明确提示重新验收，不自动补写历史记录；显式 `--allow-draft` 仍可导出草稿，并在 Markdown、映射和机器可读结果中明确标记为草稿。

命令入口：

```text
python3 scripts/ocr_review.py doctor --mineru-python <本地 MinerU Python>
python3 scripts/ocr_review.py exam-lite-prepare --pdf <试卷.pdf> --run <运行目录> --mineru-python <本地 MinerU Python>
python3 scripts/ocr_review.py render-pages --run <运行目录> --dpi 150
python3 scripts/ocr_review.py exam-lite-dispatch --run <运行目录> --dpi 150
python3 scripts/ocr_review.py exam-lite-packet --run <运行目录> --role A
python3 scripts/ocr_review.py exam-lite-packet --run <运行目录> --role B --shard-id B-01
python3 scripts/ocr_review.py exam-lite-merge --run <运行目录>
python3 scripts/ocr_review.py exam-lite-apply --run <运行目录>
python3 scripts/ocr_review.py exam-lite-accept-packet --run <运行目录> --dpi 150
python3 scripts/ocr_review.py exam-lite-apply-acceptance --run <运行目录>
python3 scripts/ocr_review.py exam-lite-format --run <运行目录>
python3 scripts/ocr_review.py exam-lite-export --run <运行目录> --output <最终 Markdown>
python3 scripts/ocr_review.py exam-lite-verify --run <运行目录> --candidate <候选.json> --markdown <最终 Markdown>
```

详细协议见 [exam-lite-protocol.md](references/exam-lite-protocol.md)、[material-processing.md](references/material-processing.md) 和 [obsidian-export.md](references/obsidian-export.md)。脚本只在运行目录写入中间结果，不覆盖源 PDF 或用户已有笔记。

## Obsidian 配套插件

`apps/obsidian-exam-notes/` 是配套插件，负责对 `exam-question` Callout 提供复制题目、复制题目链接和选项脚注。插件不重写普通 Markdown；停用插件后，题目、附件、双链和笔记仍是普通文件。插件测试与构建在其目录执行：

```text
npm test
npm run build
```

插件不写入日常 Obsidian 库。导出包使用新的空目录，图片和表格使用库内相对引用，`source-map.json` 只对应当前导出快照。

## 与其他 Skill 的边界

识别后的题目清单可以交给“公考答题卡生成与批改”生成公开答题卡，也可以独立导出 Obsidian 题目笔记。答题卡批改和分数估算不在本技能内完成；批改结果如需估分，交给“公考估分”按科目分流。
