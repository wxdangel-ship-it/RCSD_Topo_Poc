# T01 高等级 Segment 业务迭代 Tasks

- [x] T001 建立 XS2 / XS3 当前基线，记录 Segment count、unsegmented count、XS3 `1608731_1602185` 命中情况。
- [x] T002 审计 XS3 debug 产物，确认 `1608731_1602185` 未进入 candidate 的直接原因。
- [x] T003 将 Step4 历史 hard-stop 来源调整为 `validated_pairs.csv` 优先、`endpoint_pool.csv` 兼容回退。
- [x] T004 将 Step5 S2 / STEP4 历史 hard-stop 来源同步调整为 validated 优先。
- [x] T005 扩展 final fallback，使 residual 双向 road 也能作为 single-road `0-2双` Segment 发布。
- [x] T006 增加单元测试覆盖历史边界读取优先级与双向 final fallback。
- [x] T007 增加 Step4 高等级降级来源标记与 Step6 grade-kind 审计豁免。
- [x] T008 增加 final side-attachment merge，覆盖 50m 内挂接合并与超距保留。
- [x] T009 增加双向主干动态间距门限：`max(50m, pair 两端语义路口内部成员节点最大距离)`。
- [x] T010 运行 T01 相关单元测试。
- [x] T011 运行 XS2 / XS3 全链路 release 回归并对比 baseline。
- [x] T012 收紧 final side-attachment merge，按候选 Segment 连通分量整体判断至少两点回挂主 Segment，并增加多主 Segment 仲裁审计。
