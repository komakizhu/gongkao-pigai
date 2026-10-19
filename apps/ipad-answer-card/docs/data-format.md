# 公考答题卡数据格式

## 公开答题卡配置（schemaVersion 2）

```json
{
  "schemaVersion": 2,
  "type": "answer-recorder-config",
  "paperId": "paper-demo",
  "paperVersion": "2026-v1",
  "name": "示例试卷",
  "questions": [
    {"questionId":"paper-demo:q:default:41","number":41,"type":"single","options":["A","B","C","D"]},
    {"questionId":"paper-demo:q:default:42","number":42,"type":"multiple","options":["A","B","C","D"]},
    {"questionId":"paper-demo:q:default:43","number":43,"type":"boolean","options":["对","错"]}
  ]
}
```

公开配置只允许名称、试卷身份、题目身份、分区、题号、题型和选项。`answer`、`referenceAnswer`、解析、题干摘录和来源都属于私有资料，导入器会拒绝这些字段。

## 网页作答导出

JSON 的顶层类型是 `answer-recorder-attempt`，每题保留稳定 `questionId`、题号、题型、选项、最终 `answer`、可选的 `uncertainOptions`、`review` 和作答身份 `attemptId`。`uncertainOptions` 是独立于最终答案和待复查状态的选项标签数组；可以与最终答案重合，也可以在未作答时填写。

- `single`：选项字符串或 `null`；
- `multiple`：去重选项数组或 `null`，集合顺序不影响批改；
- `boolean`：`true`、`false` 或 `null`。
- `uncertainOptions`：按该题原有选项顺序排列、去重后的选项标签数组；判断题使用 `"对"`、`"错"`，没有标记时为 `[]`。schemaVersion 2 的导入备份可以省略此字段，网页按 `[]` 处理；如果字段不是数组，或包含该题不存在的选项，导入会拒绝且不覆盖已有练习。

CSV 使用 UTF-8 BOM 和标准字段转义：

```text
schema_version,paper_id,paper_version,attempt_id,exercise_id,exercise_name,exercise_status,question_id,section,question_number,question_type,answer,answered,review_flag,uncertain_options
```

多选答案写成规范排序的 `A|C`，判断答案写成 `true/false`，未答留空；`uncertain_options` 按题目标签拼接，多选可写成 `A|C`，判断题可写成 `对|错`，没有标记时留空。批改脚本只读取 `answer`，会忽略该新增列，因此不改变批改或估分结果；旧 CSV 没有该列时仍可读取。以 `= + - @` 开头的单元格会添加前缀，避免被表格软件当作公式。

## 私有答案集合与报告

Skill 的 `answer-set.json` 在相同的 `paperId`、`paperVersion` 和 `questionId` 上增加 `referenceAnswer` 与 `source`，并保留 `issues`。批改报告是新的 `exam-grade-report` 批次，逐题包含题型、我的答案、参考答案、结果、来源和多选漏选/多选项；统计区分正确、错误、未答、缺参考答案和无法判定，零分母正确率为 `null`，Markdown 显示为 `—`。原始材料、原始作答和旧报告不被覆盖。

## 兼容与身份

网页能读取旧版 `schemaVersion: 1` 四选一 JSON 与旧 IndexedDB 记录，并将缺失的 `paperId` 标为 `legacy:<exerciseId>`；旧记录缺少 `uncertainOptions` 时补为 `[]`，同时保留旧的单选、多选和判断答案。恢复备份会生成新的本地练习 ID 和 `attemptId`，保留原试卷身份、稳定题目身份、题号、最终作答和不确定标记；用户明确“再次作答”时才应使用新的全空作答副本。旧版网页读取并重新导出时可能丢弃新增标记，不承诺旧版往返保留该字段。
