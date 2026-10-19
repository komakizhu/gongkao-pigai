# 公考工具集

本工作区维护三个可独立调用的主 Skill，以及两个配套应用。三个主入口都使用“公考”中文名称，按任务需要独立使用或互相交接。

```text
skills/
├── gongkao-exam-reader/       公考试卷识别
├── gongkao-exam-answer-workflow/ 公考答题卡生成与批改
└── gongkao-score/             公考估分
    └── subskills/
        ├── gongkao-xingce-score-estimator  公考行测估分
        └── gongkao-shenlun-score-estimator 公考申论估分（占位）

apps/
├── ipad-answer-card/          iPad 公考答题卡网页
└── obsidian-exam-notes/       Obsidian 公考题目插件
```

“公考试卷识别”负责 `exam-lite-v1` 文字与结构复核，并在用户明确要求时导出 Obsidian 题目包；通用 `mineru-ocrs` Skill 保持独立。“公考答题卡生成与批改”负责私有答案集合、公开配置、iPad JSON/CSV 作答批改和批次归档。“公考估分”按科目分流，确认行测时调用行测子 Skill，申论返回尚未实现状态，未知科目不猜测。

网页协议保持 `answer-recorder-config` 与 `answer-recorder-attempt` schemaVersion 2。作答导出可包含独立的 `uncertainOptions`/`uncertain_options` 个人标记，但批改严格只使用最终 `answer`，因此不改变判题或估分；批改仍严格匹配 `paperId`、`paperVersion` 和 `questionId`，参考答案不会进入网页配置。

全局入口包括：

- `/Users/mac2/.codex/skills/公考试卷识别`
- `/Users/mac2/.codex/skills/公考答题卡生成与批改`
- `/Users/mac2/.codex/skills/公考估分`

原有 `exam-answer-workflow`、`答题助手`、`xingce-score-estimator` 和 `行测双轨估分` 入口保留为兼容软链接，均指向当前工作区的唯一 `gongkao-*` 实现。

## 验证

Python Skill 测试：

```text
python3 -m unittest discover -s skills/gongkao-exam-answer-workflow/tests -v
python3 -m unittest discover -s skills/gongkao-score/subskills/gongkao-xingce-score-estimator/tests -v
python3 -m unittest discover -s skills/gongkao-exam-reader/scripts -p 'test_*.py' -v
```

iPad 网页和 Obsidian 插件分别在 `apps/` 下运行 `npm test`、类型检查和构建；iPad 端的 Playwright 端到端测试使用 T7 上的浏览器缓存。

本次迁移备份位于 `/Volumes/T7_1T/Agent/archive/公考工具集/20261017/`。旧的 `/Users/mac2/Documents/ChatGPT/公考答题卡` 工作区未删除，完整 Git 历史也已保留在备份中。
