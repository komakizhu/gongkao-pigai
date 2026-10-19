# 公考答题卡（iPad 分屏网页）

这个配套应用记录最终作答、每题独立的不确定选项和待复查状态；`gongkao-exam-answer-workflow` Skill 负责整理 Word/PDF 答案材料、生成不含答案的答题卡配置、批改网页导出的 JSON/CSV，并按试卷和批次留存报告。支持单选、多选和判断题；参考答案和个人标记不进入公开答题卡配置，参考答案也不进入静态构建或 Service Worker 缓存。

## 日常使用

1. 把参考答案材料交给“公考答题卡生成与批改（Exam Answer Workflow）”。先运行 `extract`，检查带页码/段落来源的 Markdown；再用明确的题型和题号运行 `prepare`。
2. 处理 `answer-set.json` 里的重复、冲突、题型不明和识别不清问题。只有没有阻断问题时才运行 `generate-config`。
3. 将生成的公开 JSON 通过 AirDrop 或“文件”App 送到 iPad，在网页首页选择“导入答题卡”。网页会为每道题保留稳定身份。
4. 在分屏中看题，网页点击单选、多选或“对／错”。整个页面只有一层文档滚动，题目列表不再独立滚动。展开“不确定”后第一行为“题号｜黄色选项｜★ ○ ?”，第二行为“题型｜蓝色选项｜不确定”；两套选项逐列对齐，选项与标记按钮等大，圆圈选中为绿色。备注位于题号菜单。每次输入同步留下防丢记录，再异步写入 IndexedDB；不重建题目或按钮，拖动后的残留点击不记成答案。
5. 页面不提供“完成练习”按钮。“保存”只保存当前全部作答并读回确认，不下载 HTML，不打开系统分享。JSON/CSV 随时导出当前全部题目，交给 Skill 批改；完整 JSON 也能用于跨环境恢复。报告包含逐题我的答案、参考答案、结果、来源、漏选/多选和统计；重新批改会产生新批次，不改原始作答。

在同一查看器、同一存储来源重开原文件可继续作答。查看器若清除数据或更换来源，网页不能让其永久保留；长期留存或换环境时导出完整 JSON。网页首次访问需要 HTTPS（本地开发使用 localhost）完成资源缓存，单文件 HTML 则不需要服务器或联网。

## 保存与导出的实际含义

新记录及修改后显示“未保存”，后台防丢写入不代表手动保存。“保存”等待排队写入完成，从实际 IndexedDB 或本地恢复记录读回校验，而不是从内存取出同一个对象自证成功；成功后确认当前 `savedRevision`，重新打开保留确认状态，继续修改则重新显示“未保存”。保存包括被筛选隐藏的题目、备注和全部标记，不改写原 HTML 文件，也不触发导出。

“导出.json”和“导出.csv”才交付文件。支持文件分享的 iPad 查看器直接打开系统分享面板，用户可选择“存储到文件”或可接收文件的 App。保留真实扩展名与 MIME 类型，能力按实际接口检查，不根据 Safari、Chrome 或第三方 App 名称猜测。

不支持文件分享时，页面发起标准文件下载，同时保留完整内容、手动下载、复制与全选入口。分享取消、权限拒绝、调用失败都保留当前作答。发起下载或系统接收分享不等于用户已经完成磁盘保存，界面不会据此显示“文件已保存”。遇到查看器只能输出 PDF 时，复制 JSON 完整内容可供批改；首页“粘贴恢复”支持在另一环境恢复完整记录，不需要 PDF。

重开旧 HTML 时只恢复同一作答的较新状态，旧快照不能覆盖后来作答；兼容读取既有内嵌状态的 HTML。IndexedDB 被禁用时使用本地恢复记录；两种存储都被禁用或读回校验失败时，“保存”明确报错，答案仍在内存并可完整导出或复制，不再伪报已保存。备注在输入时保存，不等失焦。

验证包含 Chromium、WebKit 下的 100 题连续快速点选且按钮不被替换、固定按钮文字、四种屏宽下的标记同排、保存不下载、关闭整个浏览器进程后重开原文件、全部答案/标记/备注恢复、旧快照不覆盖新答案、禁止存储时保存报错但仍能导出、系统分享取消/拒绝及文本粘贴恢复。系统分享接口由测试替身验证，不代表用户的 iPad Artifact Viewer 已完成真机验收。

用户反馈 Artifact Viewer 仍有退出清零，因此该软件的持久恢复目前未解决。它通过本地 HTTP 服务运行 HTML，不能用直接打开文件的测试推断同样保留存储；需比较实际退出前后的来源与存储记录。`artifacts/2000-save-export-fix/保存环境检查.html` 只写独立测试码，不读取答案，可用于目标设备检查。未取得证据前不能宣称修复，也不自动扩展为部署网站或开发第三方查看器。

## 网页开发与验证

源码使用 TypeScript、Vite、原生 DOM、简单 CSS、IndexedDB 和 Service Worker。当前仓库没有把 `node_modules` 放在工作区；依赖、缓存、浏览器和构建临时资料统一放在 `/Volumes/T7_1T/Agent/work/公考答题卡/`。

```bash
npm install
npm run dev
npm run typecheck
npm test
npm run build
npm run build:standalone -- <公开配置.json> <输出.html>
npm run preview
```

Playwright 浏览器缓存示例：

```bash
PLAYWRIGHT_BROWSERS_PATH=/Volumes/T7_1T/Agent/work/公考答题卡/browser-cache npm run test:e2e
```

生产文件位于 `dist/`，可部署到任意 HTTPS 静态站点。Vite 使用相对资源路径，并生成 `precache-manifest.js`；根路径和子目录部署都应通过实际站点验证。更新由 Service Worker 等待用户主动处理，不强制刷新正在作答的页面，也不删除其他同源应用缓存。

## Skill 安装与命令

工作区内 Skill 位于 `../../skills/gongkao-exam-answer-workflow/`，安装入口为：

```text
/Users/mac2/.codex/skills/gongkao-exam-answer-workflow
/Users/mac2/.codex/skills/公考答题卡生成与批改 -> gongkao-exam-answer-workflow
/Users/mac2/.codex/skills/答题助手 -> gongkao-exam-answer-workflow（兼容别名）
```

Skill 运行脚本只使用 Python 标准库：

```bash
python3 ../../skills/gongkao-exam-answer-workflow/scripts/answer_workflow.py extract 材料.pdf --output 提取稿
python3 ../../skills/gongkao-exam-answer-workflow/scripts/answer_workflow.py prepare 提取稿/extracted.md \
  --output 私有答案 --paper-id paper-demo --paper-version 2026-v1 --name "示例试卷" \
  --type-map 41:single,42:multiple,43:boolean
python3 ../../skills/gongkao-exam-answer-workflow/scripts/answer_workflow.py generate-config 私有答案/answer-set.json --output 公开答题卡.json
python3 ../../skills/gongkao-exam-answer-workflow/scripts/answer_workflow.py grade 私有答案/answer-set.json 作答.json \
  --output 批改报告 --archive-dir /Volumes/T7_1T/Agent/archive/公考答题卡
```

答案行必须明确，例如 `41 single C`、`42 multiple AC`、`43 boolean 错`。单一题型也可以使用 `--question-type single`。脚本不会从正文中随意抓字母；重复、冲突、缺题或题型不明会进入 `issues`，有阻断问题时不会生成可能串号的公开配置。PDF、DOCX 和旧版 DOC 的提取会保留来源；扫描材料没有可靠文字时只标记待核实。

## 数据格式

网页公开配置是 `schemaVersion: 2` 的 `answer-recorder-config`，包含 `paperId`、`paperVersion`、题目稳定身份、题号、分区、题型和选项，不包含参考答案或个人不确定标记。网页导出的作答是 `answer-recorder-attempt`，每题保留 `answer`（单选字符串、多选数组、判断布尔值或 `null`）、可选的 `uncertainOptions`（按题目选项顺序排列的标签数组）和 `review`。CSV 使用 UTF-8 BOM，末尾增加 `uncertain_options` 列；多选答案和多选不确定标记使用 `A|C`，判断答案使用 `true/false`，判断不确定标记使用 `对|错`，未答题或无标记留空，仍保留整行并防止公式注入。批改只使用最终 `answer`，新增标记不会改变判题或估分；旧 JSON/CSV 仍可导入。

旧版 schema 1 JSON 和旧 IndexedDB 记录会转换为兼容模型，缺少 `uncertainOptions` 时按空数组处理，并保留单选、多选和判断答案；恢复副本只生成新的本地记录/作答身份，仍关联原试卷。保存事务按练习串行，滚动位置独立保存；保存失败会保留内存作答并提供重试与紧急 JSON 导出。更新后的网页使用新的离线缓存名称，等待旧页面关闭后再激活，不强制刷新作答页面，也不清除 IndexedDB。

## 真机与部署边界

自动化测试覆盖 320、375、430、768 CSS 像素、窄屏无横向滚动、三类题型导入、筛选、刷新恢复、未答题直接保存、离线重开和构建缓存。浏览器模拟不能代替 Safari 与 Notability/Goodnotes 真机分屏、Apple Pencil、主屏幕启动、系统切换恢复和真实答案材料识别；这些项目仍需在目标设备和实际材料上确认。本轮不自动公开部署、不上传参考答案、不提交或合并代码。
