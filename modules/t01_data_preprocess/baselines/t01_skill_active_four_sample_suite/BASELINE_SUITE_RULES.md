# T01 Active Four-Sample Freeze Suite

- 当前活动基线由 XXXS / XXXS2 / XXXS3 / XXXS4 四组样例共同定义。
- 后续性能优化、结构重构或规则调整，必须同时与四组活动基线对齐。
- 任一样例 compare 不一致，都需要先输出差异并等待用户确认，不得 silent 覆盖当前 freeze baseline。
- 逐样例 compare 仍使用官方入口 python -m rcsd_topo_poc t01-compare-freeze。
