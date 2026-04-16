# Step Checklist

## Step1
- 本步机器结论：当前哪些 SWSD node 被视为同一语义路口。
- 你应重点检查什么：语义路口范围、representative node、boundary roads / arms 是否合理。
- 如果这一步不对，后面大概率会怎样偏：模板、legal space 和 RC 匹配会一起偏。

## Step2
- 本步机器结论：当前 case 被归入哪个模板、主方向如何理解。
- 你应重点检查什么：`758888` 是否被识别成正确的 T 型模板与主结构。
- 如果这一步不对，后面大概率会怎样偏：frontier、mouth 与 tail 方向会错。

## Step3
- 本步机器结论：当前 legal space / frontier 允许 polygon 往哪些方向生长。
- 你应重点检查什么：哪些方向本该停止、哪些空间本不该进入。
- 如果这一步不对，后面大概率会怎样偏：后续 polygon 会在错误方向继续扩张。

## Step4
- 本步机器结论：哪些 RC 被当作 required / support / excluded。
- 你应重点检查什么：必须吃到的 RC 是否缺失、被排除的 RC 是否合理。
- 如果这一步不对，后面大概率会怎样偏：Step5/Step6 会围绕错误 RC 关系继续求解。

## Step5
- 本步机器结论：哪些 foreign 只是 seen，哪些被视为 blocking / canonical。
- 你应重点检查什么：foreign 是否看宽、是否把 provenance-only 误当 blocking。
- 如果这一步不对，后面大概率会怎样偏：最终会被错误压到 review / rejected。

## Step6
- 本步机器结论：当前 final polygon 如何组装、哪里是核心、哪里像 surplus tail。
- 你应重点检查什么：核心 polygon 是否已成立、是否仍沿 trunk 过度外推。
- 如果这一步不对，后面大概率会怎样偏：Step7 只是忠实承接一个已经偏掉的 polygon。

## Step7
- 本步机器结论：为什么最终落到当前 `acceptance_class / acceptance_reason / root_cause_layer`。
- 你应重点检查什么：Step7 是忠实承接前面结果，还是把合理结果错误压坏。
- 如果这一步不对，后面大概率会怎样偏：前面看起来合理的几何仍会被最终准出逻辑改写。
