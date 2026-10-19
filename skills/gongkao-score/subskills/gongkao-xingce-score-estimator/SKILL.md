---
name: gongkao-xingce-score-estimator
description: "读取已批改的国考或省考行测 JSON/CSV 答题数据，确定性地计算等权估分、非官方经验加权估分、六大模块统计和差异分析；作为公考估分子技能，仅在明确为行测或用户明确要求行测估分时使用。 Read corrected Chinese civil-service aptitude-test JSON/CSV answer data and deterministically produce equal-weight scores, non-official empirical weighted scores, six-module statistics, and difference analysis; use as the Gongkao Score subskill only for confirmed Xingce exams or explicit Xingce score-estimation requests."
---

# 公考行测估分（Xingce Score Estimator）

使用 `scripts/estimate.py` 执行确定性计算，不凭语言模型直觉计算成绩。加权成绩必须标注为非官方估算，不能表述为正式考试成绩。

## 作为公考估分子技能

本技能位于 `skills/gongkao-score/subskills/gongkao-xingce-score-estimator/`，由“公考估分”在确认行测后调用。批改适配器 `scripts/grade_estimate.py` 只读取 `exam-grade-report` 的题号、模块和 `correct`/`wrong`/`unanswered` 状态，不重复判答案。缺参考答案、无法判定、重复身份或模块缺失时返回 `pending`。

成功时生成 `estimate-input.json`、`estimate.json` 和 `estimate.md`；未作答按估分分母计入。等权和加权结果同时输出，权重模型、来源、适用范围和不确定性写入报告。

## 直接调用

```text
python3 scripts/estimate.py INPUT.json --format json
python3 scripts/estimate.py INPUT.csv --format markdown
python3 scripts/estimate.py INPUT.json --format both --output-dir OUTPUT_DIR
```

输入可以包含题目数组或 `questions`、`items`、`records`、`data` 数组；题号和模块必须来自输入或显式映射。默认模型来自 [weights.json](references/weights.json)，详细来源见 [sources.md](references/sources.md)。局部范围只能解释为纳入题目的估分，不能称作整卷成绩。

运行测试：

```text
python3 -m unittest discover -s tests -v
```
