# 公考答题卡数据格式

## 公开答题卡配置

```json
{
  "schemaVersion": 2,
  "type": "answer-recorder-config",
  "paperId": "paper-demo",
  "paperVersion": "2026-10-v1",
  "name": "26国考行测",
  "questions": [
    {"questionId":"paper-demo:q:言语理解:41","number":41,"section":"言语理解","type":"single","options":["A","B","C","D"]},
    {"questionId":"paper-demo:q:数量关系:42","number":42,"section":"数量关系","type":"multiple","options":["A","B","C","D"]},
    {"questionId":"paper-demo:q:判断推理:43","number":43,"section":"判断推理","type":"boolean","options":["对","错"]}
  ]
}
```

配置不能出现 `answer`、`referenceAnswer`、`uncertainOptions`、解析或来源字段。
当原始材料明确存在模块/分区时，公开配置中的每道题都必须保留非空 `section`；它不能只存在于原始 PDF、提取稿标题或私有答案集之外的说明中。

## 网页作答导出

网页导出仍使用 `schemaVersion: 2` 的 `answer-recorder-attempt`。每题的 `answer` 是最终作答，`review` 是整题待复查标记；可选的 `uncertainOptions` 是按该题原有选项顺序排列、去重后的个人不确定选项数组。它可以与最终答案重合，也可以在未作答时存在；判断题使用 `"对"`、`"错"`。旧备份或旧 IndexedDB 记录缺少该字段时按 `[]` 读取，字段不是数组或含有题外选项时拒绝 JSON 导入且不覆盖已有练习。

CSV 在现有字段末尾增加 `uncertain_options`：多选题可写 `A|C`，判断题可写 `对|错`，没有标记时留空。该列只供追踪个人标记，批改脚本仍只使用 `answer`，因此有无标记不改变批改或估分；没有该列的旧 CSV 继续兼容。CSV 保留 UTF-8 BOM、现有转义和整题行。

### 完整性检查

`exercise.questionCount` 是声明值，检查导出时必须同时核对 `exercise.questions.length`、题号、稳定身份集合，以及最终 `answer` 的非空数量。`false` 是有效判断答案，不能用普通布尔真值判断“已答”；`null` 和空多选数组表示未答，个人标记不算最终答案。

题目集合完整与全部作答是两个独立结论。例如 100 条题目记录只有 4 个最终答案，其余 96 条 `answer: null`，仍是完整导出，只能报告已答 4 题。CSV 按记录解析并保留未答题行，不能直接把物理换行数当作题目数，因为备注允许换行。

## 私有答案与报告

私有答案集合使用同一套 `paperId`、`paperVersion`、`questionId`、题型和逐题 `section`，并额外保存 `referenceAnswer` 与 `source`。如果原始材料有模块而任意题目的 `section` 为空，答案集必须标记为阻断问题，不能生成公开配置；不能依靠题号连续或整卷 `category` 事后补猜。批改报告保留 `attemptId`、答案版本、每题 `myAnswer`、`referenceAnswer`、`result`、多选漏选/多选，以及统计字段。任何版本变更都生成新报告批次，不修改原始作答。


## 行测条件分流

私有答案集合可保存 `examType: "xingce" | "other" | "unknown"`、`year`、`category`、`total_questions`、`scope: "full" | "partial"`、`complete`。逐题的规范模块字段是 `section`；外部估分输入可把它映射为 `module`，但不能用 `module` 缺失来掩盖答案集 `section` 缺失。上述考试信息用于批改后的估分，私有参考答案仍不进入公开配置。

批改报告增加 `exam`（考试元数据）及 `scoreEstimate`：`skipped` 表示非行测或科目未知，`pending` 表示已确认行测但数据不全，`complete` 表示已生成双轨分数，`failed` 表示子技能运行失败。原 `counts`、`rows` 及批改正确率保持原口径。估分输入逐题只提供题号、模块及已判定状态，不重复判答案；原 `questionId` 对照保留在 `source_question_ids`，身份、版本、作答和批次写入 `grading_source`。
