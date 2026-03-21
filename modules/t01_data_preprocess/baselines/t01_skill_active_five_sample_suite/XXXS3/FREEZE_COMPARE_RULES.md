# T01 Skill v1.0.0 Freeze Compare Rules

- 默认要求当前运行结果与 freeze baseline 完全一致。
- 对比范围至少包括 validated pair、segment_body membership、trunk membership、最终 refreshed nodes/roads hash。
- 任一集合或 hash 不一致，默认判定为 FAIL。
- 未经用户明确认可，不得更新本 freeze baseline。
