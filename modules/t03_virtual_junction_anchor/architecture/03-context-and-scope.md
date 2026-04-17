# 03 Context And Scope

## 上下文

- T03 继承 T02 的正式业务契约，而不是其既有结构债
- `Step3` 修复轮仍以 `A-H`、allowed space、negative mask、`step3_state` 为正式业务范围
- T03 当前只对 `kind_2 in {4, 2048}` 的 `Step3` 建立新基线

## 当前范围

- case loader
- Step1 最小上下文
- Step2 模板归类
- Step3 legal space
- 批量运行与审查产物

## 当前范围外

- `Step4-7` 的完整 `foreign / geometry / acceptance` 语义
- stage4 连续链与 `complex 128`

## 说明

- `Step3` 内部需要的 `foreign / geometry / acceptance` 边界证据仍在范围内，且可作为 A/B/C/D/E/F/G 的审计依据
- 本文件排除的是 `Step4-7` 的完整 `foreign / geometry / acceptance` 语义，而不是 Step3 为完成 A-H 所需的边界表达
- 对当前语义路口 branch 的追溯范围，当前以“进入路口与退出路口都属于合法活动链，并双向追溯到上一个或下一个语义路口”为准
- `foreign / opposite` 的判定不得覆盖当前语义路口关联 road 与其二度衔接 road；这些对象仍属于 Step3 内部边界语义的一部分
- `Rule A` 入口截断当前以局部 road surface 截面为准；`Rule E` 中 `RCSDRoad` 仅作为挂靠 opposite `SWSD road` 的 near-corridor proxy，而非独立主判据
