# V-03 轨迹自适应采样报告（自动生成）

| 用例 | 时长 | 原始点 | 落盘点 | 压缩率 | 最大间隔 | 偏差 max/p95 | BIN_V1 体积 | 预算 | 结论 |
|---|---|---|---|---|---|---|---|---|---|
| track_2h | 126.0min | 7560 | 1116 | 85.24% | 20.0s | 27.5/0.2m | 14.9KB | 500KB | PASS |
| track_3h | 187.8min | 11269 | 1342 | 88.09% | 20.0s | 22.2/0.2m | 17.2KB | 750KB | PASS |

## 细节

### track_2h
- 模式分布（落盘点）：{'TAXI': 55, 'STRAIGHT': 305, 'CLIMB_DESCENT': 496, 'TURN': 74, 'APPROACH': 186}
- 保存理由：{'first': 1, 'hdg': 158, 'interval:TAXI': 13, 'event': 17, 'mode:TAXI->STRAIGHT': 1, 'mode:STRAIGHT->CLIMB_DESCENT': 2, 'interval:CLIMB_DESCENT': 445, 'mode:CLIMB_DESCENT->STRAIGHT': 1, 'dist': 279, 'mode:STRAIGHT->TURN': 2, 'interval:TURN': 4, 'mode:TURN->STRAIGHT': 2, 'interval:STRAIGHT': 4, 'mode:CLIMB_DESCENT->APPROACH': 1, 'interval:APPROACH': 183, 'mode:APPROACH->STRAIGHT': 1, 'mode:STRAIGHT->TAXI': 1, 'last': 1}
- 固定 1Hz 对照：64.9KB（自适应 14.9KB）
- 量化误差（经纬度）：0.01m
- 分段：12 段
- 检查项：{'reduction_ge_60pct': True, 'max_gap_le_45s': True, 'deviation_le_30m': True, 'size_within_budget': True}

### track_3h
- 模式分布（落盘点）：{'TAXI': 55, 'STRAIGHT': 532, 'CLIMB_DESCENT': 495, 'TURN': 74, 'APPROACH': 186}
- 保存理由：{'first': 1, 'hdg': 152, 'interval:TAXI': 13, 'event': 17, 'mode:TAXI->STRAIGHT': 1, 'mode:STRAIGHT->CLIMB_DESCENT': 2, 'interval:CLIMB_DESCENT': 445, 'mode:CLIMB_DESCENT->STRAIGHT': 1, 'dist': 511, 'mode:STRAIGHT->TURN': 2, 'interval:TURN': 4, 'mode:TURN->STRAIGHT': 2, 'interval:STRAIGHT': 4, 'mode:CLIMB_DESCENT->APPROACH': 1, 'interval:APPROACH': 183, 'mode:APPROACH->STRAIGHT': 1, 'mode:STRAIGHT->TAXI': 1, 'last': 1}
- 固定 1Hz 对照：91.7KB（自适应 17.2KB）
- 量化误差（经纬度）：0.01m
- 分段：12 段
- 检查项：{'reduction_ge_60pct': True, 'max_gap_le_45s': True, 'deviation_le_30m': True, 'size_within_budget': True}
