# 答题助手 Skill＋iPad 分屏网页执行记录

执行日期：2026-10-16。迁移后源码位于 `apps/ipad-answer-card/`；依赖、浏览器和构建临时资料位于 `/Volumes/T7_1T/Agent/work/公考答题卡/`，长期测试归档位于 `/Volumes/T7_1T/Agent/archive/公考答题卡/`。T7_1T 已确认挂载且可写，测试时保留了原始输入和批改批次。

## 已完成

- [x] 数据接口升级到 schemaVersion 2，支持 `single`、`multiple`、`boolean`，加入 `paperId`、`paperVersion`、`questionId`、`attemptId`。
- [x] 保留旧 schema 1 JSON 和旧 IndexedDB 记录的转换路径，不清库；恢复副本生成新的本地身份但保留题目身份与答案。
- [x] 网页支持公开配置导入、三类题型、窄屏 44×44 触控区域、筛选固定集合、清空/复查、完成后重新编辑和 JSON/CSV 导出。
- [x] 修复保存时序：答案修订号不再被滚动改动；保存队列使用最后成功修订号，连续改选不会用旧快照回滚；保存失败保留内存答案，提供重试和紧急 JSON；完成和普通导出等待成功保存。
- [x] 滚动位置移入独立 IndexedDB store；Service Worker 只管理自己的缓存命名空间，生产构建生成完整 JS/CSS 预缓存清单，未控制页面不显示“离线可用”。
- [x] 迁移网页配套的 `skills/gongkao-exam-answer-workflow/`，安装到 `/Users/mac2/.codex/skills/gongkao-exam-answer-workflow`，中文入口 `/Users/mac2/.codex/skills/公考答题卡生成与批改`，并保留 `/Users/mac2/.codex/skills/答题助手` 兼容别名。
- [x] Skill 可提取 TXT/Markdown/PDF/DOCX/DOC，保留来源和待核实标记；可生成私有答案集合、无答案公开配置，并对 JSON/CSV 作答按稳定题目身份确定性批改和归档。

## 实际验证

- `python3 -m unittest discover -s ../../skills/gongkao-exam-answer-workflow/tests -v`：批改 Skill 测试覆盖混合三类题型、公开配置无答案、冲突阻断和 JSON 批改。
- `python3 -m py_compile ../../skills/gongkao-exam-answer-workflow/scripts/answer_workflow.py`：通过。
- 双语验证器：迁移后使用 `/Users/mac2/.codex/skills/公考答题卡生成与批改` 入口验证。
- `npm run typecheck`：通过。
- `npm test`：通过，2 个测试文件共 9 个网页领域/IndexedDB 用例。
- `npm run build`：通过，生成 `dist/precache-manifest.js`、哈希 JS/CSS、manifest、图标和 Service Worker 静态构建。
- `PLAYWRIGHT_BROWSERS_PATH=/Volumes/T7_1T/Agent/work/公考答题卡/browser-cache npm run test:e2e`：Chromium 与 WebKit 各 5 个用例，共 10 个通过，覆盖 320/375/430/768 宽度、筛选、刷新恢复、三类题型配置导入、完成未答和缓存离线重开。
- Skill 夹具：三类题型答案生成公开配置；多选少选报告 `missingOptions`；JSON 和 UTF-8 BOM CSV 作答均产生正确/错误结果。夹具和报告保存在 T7 work/archive 目录，不进入公开构建。
- 截图：`/Volumes/T7_1T/Agent/work/公考答题卡/screenshots-final-20261016/01-home.png`、`02-answer-narrow.png`、`03-completed.png`；生产构建副本：`/Volumes/T7_1T/Agent/work/公考答题卡/build-output-final-20261016/`。

## 尚未执行或受限

- Playwright WebKit 真正运行需要宿主提供兼容浏览器；当前只确认缓存目录存在，未将 Chromium 结果冒充 Safari。
- 未执行真实用户 Word/PDF、扫描件和复杂表格材料；当前只用明确的文字夹具验证提取和来源字段。
- 未执行真实 iPad Safari 分屏、Notability/Goodnotes、Apple Pencil、主屏幕启动和系统切换恢复。
- 当前宿主没有可调用的 Large 原生 Review 入口；没有将自查、类型检查或测试冒充 Review。交付时需由宿主执行原生 Review，审查对象为全部新增文件。
- 没有部署、上传、提交、合并或公开仓库；首次 HTTPS 部署仍需用户提供授权环境并按 README 操作。

## 回退

回退网页构建只替换静态文件，不删除浏览器 IndexedDB；旧版记录可由当前迁移逻辑读取。Skill 报告和原始作答按批次保留，发现答案版本错误时生成新答案集和新批次，不覆盖旧文件。长期副本存放在 `/Volumes/T7_1T/Agent/archive/公考答题卡/`。
