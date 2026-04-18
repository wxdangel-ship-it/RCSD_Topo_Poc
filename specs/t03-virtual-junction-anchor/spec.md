# T03 / Step4-5 联合阶段变更工件

## 1. 文档定位

- 文档类型：spec-kit 变更工件
- 状态：`active change / step45-joint-phase`
- 本轮任务已确认将 `t03_virtual_junction_anchor` 从 `Step3-only` 升级为 `Step4-5` 联合阶段。
- 本文件用于固化本轮变更需求，不替代模块长期源事实。
- `Step3 legal space` 是已冻结前置层；本轮只消费其既有产物，不重新定义 allowed space，不反向扩大 corridor，不重新引入 `50m` 新口径。

## 2. 本轮目标

- 将 T03 正式范围升级为 `Step4 = RCSD 关联语义识别` 与 `Step5 = foreign 过滤与排除落地` 的联合阶段。
- 只处理 `center_junction` 与 `single_sided_t_mouth`。
- 联合阶段最终输出是供 `Step6` 消费的干净中间结果包，不是 polygon。
- 保持单 case 输出、批跑、审计与平铺 PNG 可复现。
- 默认正式批量集固定为：`raw 61 / formal 58`，默认排除 `922217 / 54265667 / 502058682`。

## 3. 正式输入契约

### 3.1 case-package 基础输入

- 正式输入根目录固定为 `/mnt/e/TestData/POC_Data/T02/Anchor/<case_id>/`
- 每个 case 必须包含：
  - `manifest.json`
  - `size_report.json`
  - `drivezone.gpkg`
  - `nodes.gpkg`
  - `roads.gpkg`
  - `rcsdroad.gpkg`
  - `rcsdnode.gpkg`

### 3.2 Step3 冻结前置输入

- `Step4-5` 只能消费同 case 的冻结 `Step3` 产物：
  - `step3_allowed_space.gpkg`
  - `step3_status.json`
  - `step3_audit.json`
- 官方默认 `--step3-root` 指向仓库内现行 Step3 正式基线 run root；显式单 case 调试可改写。

### 3.3 字段与空间前提

- 所有空间处理统一到 `EPSG:3857`
- `nodes` 至少需具备：`id / mainnodeid / has_evd / is_anchor / kind_2 / grade_2`
- `roads / rcsdroad` 至少需具备：`id / snodeid / enodeid / direction`
- `rcsdnode` 至少需具备：`id / mainnodeid`

## 4. 联合阶段业务定义

### 4.1 冻结前置层

- `Step1`、`Step2`、`Step3` 是已冻结前置层。
- 联合阶段不得重新定义：
  - `allowed space`
  - `negative mask`
  - `corridor`
  - `50m fallback`

### 4.2 Step4 定义

- `Step4` 负责在冻结 `Step3 allowed space` 内选择 RCSD，并完成 `A / B / C` 分类。
- `Step4-5` 只允许处理当前 SWSD 路口所在道路面上的对象；其他道路面对象不参与当前 case 全局处理。
- 当前 SWSD 道路面由 `Step3 selected_road_ids` 在 `drivezone` 内构成的局部道路面近似得到。
- `A`：RCSD 也构成当前 case 对应语义路口
- `B`：RCSD 不构成完整语义路口，但存在相关 `RCSDRoad`
- `C`：无相关 `RCSDRoad`
- `A` 类输出 `required_rcsdnode / required_rcsdroad`
- `B` 类输出重点是 `required hook zone`，不是整条 road 全段
- `C` 类不新增 RC 侧 required
- 若 RCSD 下没有稳定语义路口 core，但存在 support / hook zone，则统一按 `B / review` 处理，并显式记 `rcsd_semantic_core_missing = true`
- `degree = 2` 的 `RCSDNode` 只视为 connector，不进入 `required semantic core`
- 对 `single_sided_t_mouth` 的平行重复 `support RCSDRoad`，应优先保留更贴近竖方向退出当前面一侧的那条，而不是泛化地按“离 semantic core 更近”保留

### 4.3 Step5 定义

- `Step5` 负责：
  - 将 `excluded RC` 直接视为 `foreign RC`
  - 明确 foreign `SWSD / RCSD / roads / arms / corridors`
  - 为 `Step6` 提供硬边界
- `Step5` 不是：
  - 重新做 `Step4` 关联
  - 生成最终 polygon
  - 做最终 accepted/rejected 判定

## 5. 输出契约

### 5.1 单 case 固定输出

- `step45_required_rcsdnode.gpkg`
- `step45_required_rcsdroad.gpkg`
- `step45_support_rcsdnode.gpkg`
- `step45_support_rcsdroad.gpkg`
- `step45_excluded_rcsdnode.gpkg`
- `step45_excluded_rcsdroad.gpkg`
- `step45_required_hook_zone.gpkg`
- `step45_foreign_swsd_context.gpkg`
- `step45_foreign_rcsd_context.gpkg`
- `step45_status.json`
- `step45_audit.json`
- `step45_review.png`

### 5.3 审计补充字段

- `step45_status.json / step45_audit.json` 需补充：
  - `rcsd_semantic_core_missing`
  - `nonsemantic_connector_rcsdnode_ids`
  - `true_foreign_rcsdnode_ids`
  - `parallel_support_duplicate_dropped_rcsdroad_ids`
- `step45_audit.json` 需补充当前 SWSD 道路面过滤审计：
  - `active_rcsdnode_ids / active_rcsdroad_ids`
  - `ignored_outside_current_swsd_surface_rcsdnode_ids / ignored_outside_current_swsd_surface_rcsdroad_ids`
- `nonsemantic_connector_rcsdnode_ids` 与 `true_foreign_rcsdnode_ids` 必须分开落盘，避免将 local connector node 误记为真正 foreign semantic node

### 5.2 批次固定输出

- `preflight.json`
- `summary.json`
- `step45_review_index.csv`
- `step45_review_flat/`
- `cases/`

### 5.3 批次输出要求

- `step45_review_flat/` 内禁止子目录
- 平铺所有 case PNG
- 命名稳定、可排序
- 便于连续人工目视检查

## 6. 状态枚举

- `step45_state` 只允许：
  - `established`
  - `review`
  - `not_established`
- `association_class` 只允许：
  - `A`
  - `B`
  - `C`

## 7. CLI 要求

- 官方入口：

```bash
python3 -m rcsd_topo_poc t03-step45-rcsd-association --help
```

- 必须支持：
  - 单 case 模式
  - 批量模式
  - 默认正式 `58` case
  - 显式点名单 case 调试
  - 输出目录可控
  - `debug render` 可控

## 8. 验证与验收

- 至少补齐：
  - loader / writer 基础测试
  - `Step4 A/B/C` 分类测试
  - `B` 类 hook zone 不是整条 road 的测试
  - `Step5 excluded -> foreign` 转换测试
  - `step45_state` 三态映射测试
  - batch `summary / index / flat review` 输出测试
  - flat PNG 无子目录测试
- 必须真实跑：
  - CLI `--help`
  - 若干代表性单 case smoke
  - 默认正式 `58` case 批跑
- `summary.json` 中必须明确表达：
  - `raw_case_count = 61`
  - `default_formal_case_count = 58`
  - `excluded_case_ids`
  - `effective_case_ids`
  - `missing_case_ids == []`
  - `failed_case_ids == []`
