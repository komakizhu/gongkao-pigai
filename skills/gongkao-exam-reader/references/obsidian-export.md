# Obsidian 题目导出约定

导出入口是 `python3 skills/gongkao-exam-reader/scripts/ocr_review.py exam-lite-obsidian-export`，输入必须是完成验收的 `exam-lite-v1` 候选和布局；revision 2 候选会保留其拓扑元数据，旧版候选则保留旧版的空元数据。它只写新目录，不覆盖用户已经写过的 Markdown。

## Markdown 结构

```markdown
# 2025国考行测地市级

> [!exam-question] 第 66 题
> 原题干……
>
> A. 选项一
> B. 选项二
> C. 选项三
> D. 选项四

^q66

标签：
关联：

> [!success]- 答案与解析
> 待补充。

> [!note]- 我的笔记
>
```

题目卡片不使用三级标题，因此大纲只显示试卷、科目和题型标题。题目边界只有在候选文字、布局和复核证据足够可靠时才建立；跨页题合并为一条记录，嵌入正文的题号和共享材料无法唯一归属时保留原文并写入未决清单。

图片被提取到 `attachments/`，在 Markdown 中使用库内 `![[attachments/...]]`；HTML 表格、合并单元格和原卷脚注不被转换成普通文字。`questions.json` 是验证和后续工具的索引，插件日常操作以 Markdown 为准。

## 插件行为

插件只处理 `exam-question` Callout，不改写普通 Callout，也不会打开文件时重写内容。阅读视图/实时预览提供复制和链接按钮，源码编辑可用命令面板或右键菜单执行。复制题目保留材料、图片、表格、公式和原卷脚注，但移除个人脚注、答案、笔记、块编号和题目包装；复制链接使用源文件路径及稳定块编号。

插件停用后所有内容仍是普通 Markdown。跨库迁移时必须一起携带 `attachments/`。
