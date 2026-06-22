# 05 Quality Requirements

## 1. 业务正确性

- `<关键业务正确性要求。>`

## 2. 输出与契约稳定性

- `<输出完整性、字段稳定性、copy-on-write 或兼容要求。>`

## 3. Review 与 formal 分层

- `<review-only 不能反写 formal 的要求；无 review-only 时说明无。>`

## 4. 观测、恢复与性能

- `<progress、summary、terminal record、性能指标或失败恢复要求。>`

## 5. 治理要求

- 模块文档面、项目级盘点、官方入口事实与当前实现保持一致。
- 不把 solver 常量、启发式参数或单轮 closeout 结果误写成长期业务契约。
- 不新增、不删除、不重命名 repo 官方入口，除非后续单独获得入口治理任务授权。
