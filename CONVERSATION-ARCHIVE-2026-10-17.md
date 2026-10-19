# 公考批改 Skill 读取确认与归档

日期：2026-10-17（Asia/Shanghai）

## 对话与结论

用户指定本仓库下的 xingce-score-estimator/SKILL.md 作为当前 Skill 说明，要求只读取并确认 agents/openai.yaml、scripts/estimate.py、scripts/ocr_review.py、scripts/ocr_obsidian.py 及 obsidian-exam-notes/。此前误放在“考公skill”的 worktree 未读取或使用。

已完成静态读取：功能包括行测等权与非官方加权估分、exam-lite-v1 revision 2 试卷复核、Obsidian 题目导出。插件版本为 0.1.0，包含复制题目、复制题目链接、选项脚注功能。此前未修改源码、安装、构建或启动试卷处理；未验证运行效果。

用户随后发出 commit。本次按无代码变更对话归档规则，新增本记录，将已有项目材料与记录一起纳入首次提交；不合并、不发布、不安装，不调整版本。

## 保存位置

工作仓库：/Volumes/T7_1T/Agent/work/gongkao-xingce-exam-lite-obsidian

归档副本：/Volumes/T7_1T/Agent/archive/gongkao-xingce-exam-lite-obsidian/2026-10-17-commit

本次对话未收到实际图片、截图或附件文件；“截图所示”只是交接说明中的文字引用，因此没有可归档的截图文件。

## 文件清单

下表每个项目文件均随本次提交保存，并在归档目录中按相同相对路径复制。原始路径为工作仓库路径加相对路径，归档路径为归档目录加相对路径。

| 文件名 | 仓库内相对路径 | 与讨论的关系 |
| --- | --- | --- |
| .gitignore | `.gitignore` | Git 忽略配置 |
| SKILL.md | `xingce-score-estimator/SKILL.md` | 指定读取的 Skill 说明 |
| openai.yaml | `xingce-score-estimator/agents/openai.yaml` | 指定检查的界面元数据 |
| README.md | `xingce-score-estimator/obsidian-exam-notes/README.md` | Obsidian 配套插件及测试、构建材料 |
| esbuild.config.mjs | `xingce-score-estimator/obsidian-exam-notes/esbuild.config.mjs` | Obsidian 配套插件及测试、构建材料 |
| main.js | `xingce-score-estimator/obsidian-exam-notes/main.js` | Obsidian 配套插件及测试、构建材料 |
| manifest.json | `xingce-score-estimator/obsidian-exam-notes/manifest.json` | Obsidian 配套插件及测试、构建材料 |
| package-lock.json | `xingce-score-estimator/obsidian-exam-notes/package-lock.json` | Obsidian 配套插件及测试、构建材料 |
| package.json | `xingce-score-estimator/obsidian-exam-notes/package.json` | Obsidian 配套插件及测试、构建材料 |
| main.ts | `xingce-score-estimator/obsidian-exam-notes/src/main.ts` | Obsidian 配套插件及测试、构建材料 |
| markdown.js | `xingce-score-estimator/obsidian-exam-notes/src/markdown.js` | Obsidian 配套插件及测试、构建材料 |
| styles.css | `xingce-score-estimator/obsidian-exam-notes/styles.css` | Obsidian 配套插件及测试、构建材料 |
| markdown.test.js | `xingce-score-estimator/obsidian-exam-notes/tests/markdown.test.js` | Obsidian 配套插件及测试、构建材料 |
| tsconfig.json | `xingce-score-estimator/obsidian-exam-notes/tsconfig.json` | Obsidian 配套插件及测试、构建材料 |
| data-format.md | `xingce-score-estimator/references/data-format.md` | Skill 配套协议、配置、脚本及测试材料 |
| exam-lite-protocol.md | `xingce-score-estimator/references/exam-lite-protocol.md` | Skill 配套协议、配置、脚本及测试材料 |
| material-processing.md | `xingce-score-estimator/references/material-processing.md` | Skill 配套协议、配置、脚本及测试材料 |
| obsidian-export.md | `xingce-score-estimator/references/obsidian-export.md` | Skill 配套协议、配置、脚本及测试材料 |
| sources.md | `xingce-score-estimator/references/sources.md` | Skill 配套协议、配置、脚本及测试材料 |
| weights.json | `xingce-score-estimator/references/weights.json` | Skill 配套协议、配置、脚本及测试材料 |
| context_ocr_worker.py | `xingce-score-estimator/scripts/context_ocr_worker.py` | Skill 配套协议、配置、脚本及测试材料 |
| context_pipeline.py | `xingce-score-estimator/scripts/context_pipeline.py` | Skill 配套协议、配置、脚本及测试材料 |
| context_render.py | `xingce-score-estimator/scripts/context_render.py` | Skill 配套协议、配置、脚本及测试材料 |
| estimate.py | `xingce-score-estimator/scripts/estimate.py` | 指定检查的核心脚本 |
| ocr_layout.py | `xingce-score-estimator/scripts/ocr_layout.py` | Skill 配套协议、配置、脚本及测试材料 |
| ocr_obsidian.py | `xingce-score-estimator/scripts/ocr_obsidian.py` | 指定检查的核心脚本 |
| ocr_review.py | `xingce-score-estimator/scripts/ocr_review.py` | 指定检查的核心脚本 |
| test_context_ocr_worker.py | `xingce-score-estimator/scripts/test_context_ocr_worker.py` | Skill 配套协议、配置、脚本及测试材料 |
| test_context_pipeline.py | `xingce-score-estimator/scripts/test_context_pipeline.py` | Skill 配套协议、配置、脚本及测试材料 |
| test_exam_lite.py | `xingce-score-estimator/scripts/test_exam_lite.py` | Skill 配套协议、配置、脚本及测试材料 |
| test_ocr_obsidian.py | `xingce-score-estimator/scripts/test_ocr_obsidian.py` | Skill 配套协议、配置、脚本及测试材料 |
| test_ocr_review.py | `xingce-score-estimator/scripts/test_ocr_review.py` | Skill 配套协议、配置、脚本及测试材料 |
| test_throughput_queue.py | `xingce-score-estimator/scripts/test_throughput_queue.py` | Skill 配套协议、配置、脚本及测试材料 |
| throughput_queue.py | `xingce-score-estimator/scripts/throughput_queue.py` | Skill 配套协议、配置、脚本及测试材料 |
| CONVERSATION-ARCHIVE-2026-10-17.md | `CONVERSATION-ARCHIVE-2026-10-17.md` | 本次对话总结及归档清单 |

## 本次检查

所有待保存 Python 文件通过 ast.parse 语法解析，JSON 文件通过 json.loads 解析。未执行程序、测试、构建或整批试卷处理。
