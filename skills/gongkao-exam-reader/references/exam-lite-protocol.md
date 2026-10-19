# exam-lite-v1 迁移协议

此目录承载公考题目 Skill 的开发版实现，协议本身仍使用 `exam-lite-v1`，但不把目标 Skill 标识成 MinerU。MinerU 只作为候选解析引擎；复核角色、证据、候选版本和来源映射由本 Skill 的 run 目录管理。

## 输入和任务包

`exam-lite-prepare` 读取 PDF 已有文字层和坐标，不调用 WPS。`manifest.json`、`wps.json`、`mineru.json`、对应 layout 和 checkpoint 必须位于同一 run；空白页与纯图片页写入页清单，正文缺文字层写入 `wps-input-report.json` 并阻断完成。

`exam-lite-dispatch` 创建：

- 一个全卷 A 任务。它只能读 WPS/MinerU 文字层、坐标、页面顺序和相邻页文字，不得访问图片载荷或源 PDF。
- 每两页一个 B 分片。每个分片有不重复的 `primary_pages`，前后各一页可列入 `context_pages`；补丁只能作用于主责任页。

每个任务包保存输入摘要、candidate digest、独立上下文 ID、attempt 和 task scope。报告缺失、输入摘要不匹配、上下文重复或覆盖不完整都阻断合并。

## 合并、验收与导出

合并只接受精确 Unicode `page/start/end/before/after` 和匹配版本的补丁。相同补丁去重；重叠或同点候选形成冲突组。未决冲突恢复原文，保留审计记录。

有实际修改时 C 只接收原候选、临时候选、修改页图片、源 PDF 对应页、版本信息和匿名候选方案，逐项输出 `accept`、`revert` 或 `unresolved`。C 不读取 A/B 报告。应用验收结果时从原候选重新构造最终候选，并保留回退版本。

排版在 C 之后执行，随后生成普通 Markdown、source-map 和 Obsidian 包。没有修改时跳过 C，但必须继续进行页覆盖、媒体、源元数据、映射和 Markdown 可导出性检查。

## 计时字段

`timing.jsonl` 至少记录输入检查、MinerU、页面渲染、A、每个 B 分片、合并、C、排版、导出、验证、等待、重试，以及页面和 checkpoint 复用数。`parallel` 摘要记录 B 最大并行数、真实区间和重叠；不能将并行 Agent 的耗时简单相加。
