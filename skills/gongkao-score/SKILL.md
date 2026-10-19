---
name: gongkao-score
description: "根据已批改的公考作答或结构化结果按科目分流估分；确认是行测时调用公考行测估分，确认是申论时进入尚未实现的申论估分占位，科目未知时保留待确认状态。 Use this skill to route Chinese civil-service exam scoring by subject: invoke the Xingce estimator for confirmed aptitude tests, return an explicit not-implemented status for Shenlun, and keep unknown subjects pending without guessing."
---

# 公考估分（Gongkao Score）

本技能是公考估分的统一入口。它接收已经批改的 `exam-grade-report`，也可以让用户直接调用行测子技能处理支持的 JSON/CSV 估分输入。它负责科目判断和结果状态，不重新判断答案，也不把加权估算表述为正式成绩。

## 科目分流

- 明确为行测（`xingce`、`行测` 或“行政职业能力测验”）时，调用 [公考行测估分](subskills/gongkao-xingce-score-estimator/SKILL.md)。
- 明确为申论（`shenlun` 或“申论”）时，返回“公考申论估分子技能尚未实现”，保留批改结果，不生成分数。
- 科目未知时返回待确认状态，不根据题型、题号或考试名称的模糊片段猜测。
- `other` 或明确关闭估分时跳过估分，只保留原批改报告。

## 调用入口

批改流程会自动调用本目录的 `scripts/score_router.py`。需要单独分流已生成的批改报告时，可执行：

```text
python3 scripts/score_router.py --report <exam-grade-report.json> --output-dir <新的输出目录> --exam-type auto
```

行测估分的 JSON/CSV 直接入口仍在 [公考行测估分](subskills/gongkao-xingce-score-estimator/SKILL.md)。估分输入只接受已明确的题号、模块和批改状态；缺少模块、参考答案或可判定结果时返回 `pending`，不把未知题目算成错误。

## 输出约定

行测成功时在输出目录生成 `estimate-input.json`、`estimate.json` 和 `estimate.md`，并在批改报告的 `scoreEstimate` 中记录状态、来源和分数。等权分与加权分同时输出，加权分始终注明“非官方估算”。申论和未知科目不生成伪造分数。

三个主 Skill 可以独立调用。试卷识别结果可以直接进入答题卡生成与批改，也可以跳过前置流程直接把已有批改报告交给本技能。
