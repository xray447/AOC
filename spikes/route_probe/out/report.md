# V-05 / V-06 航路优先级探针报告（自动生成）

- navdata：OK / AIRAC 2609 / load 80.8ms
- graph：OK / load 699.2ms
- AIP：offline_fixture / 无错误

| 用例 | 期望 | 实际 provider | 状态 | 置信度 | 覆盖 | 高度 | 耗时 | 备注 |
|---|---|---|---|---|---|---|---|---|
| AIP_RJTT_RJAA | AIP | AIP | ok | high | 未检查 | 未检查 | 781.1ms | coverage_route_too_short,altitude_unverified |
| GRAPH_ZBAA_ZSSS | GRAPH | GRAPH | ok | high | PASS | PASS | 314.6ms | - |
| SIMBRIEF_LROP_LFPG | SIMBRIEF | SIMBRIEF | deferred | low | 未检查 | 未检查 | 0.0ms | requires_online,no_offline_candidate |
| CROSS_EGLL_KJFK | SIMBRIEF | SIMBRIEF | deferred | low | 未检查 | 未检查 | 9.0ms | requires_online,no_offline_candidate |
| NO_NAVDATA_RJTT_RJAA | AIP | AIP | ok | medium | 未检查 | 未检查 | 467.8ms | navdata_unavailable |

## 断言

- 全部通过