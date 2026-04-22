# default-imp 使用说明

## 什么时候用 `default-imp`

- 日常小中型代码修改。
- 不需要完整 Spec Kit 流程的任务。
- 边界相对清晰、可以通过最小改动解决的问题。

## 什么时候改走 Spec Kit

- 新需求。
- 跨模块改动。
- 需要正式 `spec / plan / tasks`。
- 边界不清或影响扩大。

## 触发语句示例

```text
按 default-imp 执行：
<任务目标>
```

```text
本轮是大型变更，转入 Spec Kit 流程。
```

```text
本轮 implement 阶段默认遵循 default-imp。
```
