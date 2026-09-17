# 沛警智枢结构化研判消息契约（草案 V1.0）

## 1. 目标与边界

该契约用于区分两种助手回复：

- 普通回复：继续返回 `type=text` 的消息 Part，前端按 Markdown 渲染。
- 结构化研判回复：返回 `type=analysis_result` 的消息 Part，前端按研判过程、目标对象画像、核心结论、研判依据、建议下一步操作和智能发现线索渲染。

V1.0 是前后端联调基线，不要求后端一次性填满所有数组。`subjects`、`conclusions`、`evidence`、`clues` 均允许为空数组。前端对空数组隐藏相应区块。

研判过程只能返回可审计的任务步骤、工具调用摘要、数据来源摘要和状态，不得返回模型隐藏思维链、系统提示词、密码、密钥或未脱敏的敏感原始数据。

## 2. 消息封装

结构化结果作为现有 `GET/POST /sessions/{sid}/messages` 消息中的一个 Part 返回：

```json
{
  "info": {
    "id": "msg_01",
    "role": "assistant",
    "time": { "created": 1770000000, "completed": 1770000030 }
  },
  "parts": [
    {
      "id": "part_01",
      "type": "analysis_result",
      "data": {
        "schema": "peixian.analysis-result",
        "version": "1.0",
        "run_id": "run_01",
        "generated_at": "2026-09-17T15:34:18+08:00",
        "intro": "已根据您的需求完成分析，以下是目标对象近期活动情况及关联人员研判结果。",
        "process": [],
        "subjects": [],
        "conclusions": [],
        "evidence": [],
        "next_steps": "建议进一步核验重点同行人员身份，并结合原始资料复核车辆活动轨迹。",
        "clues": []
      }
    }
  ]
}
```

判别规则必须同时满足：

1. Part 的 `type` 为 `analysis_result`。
2. `data.schema` 为 `peixian.analysis-result`。
3. `data.version` 为前端支持的版本，当前为 `1.0`。

不满足以上条件时，前端不进行特殊渲染，并显示“暂不支持的结构化消息”兜底提示。后端不要把结构化 JSON 放在 Markdown 代码块中。

## 3. 完整示例

```json
{
  "schema": "peixian.analysis-result",
  "version": "1.0",
  "run_id": "run_night_001",
  "generated_at": "2026-09-17T15:34:18+08:00",
  "intro": "已根据您的需求完成分析，以下是张某最近30天的夜间活动情况及关联人员研判结果。",
  "process": [
    { "id": "step_1", "title": "获取目标对象信息", "detail": "调取目标对象基础信息和重点人员库数据", "time": "15:32:10", "status": "completed" },
    { "id": "step_2", "title": "查询近期轨迹", "detail": "检索最近30天授权范围内的轨迹记录", "time": "15:32:28", "status": "completed" },
    { "id": "step_3", "title": "分析同行人员", "detail": "基于时空碰撞分析同行人员及关联关系", "time": "15:33:05", "status": "completed" },
    { "id": "step_4", "title": "关联车辆信息", "detail": "检索关联车辆及共同出行记录", "time": "15:33:42", "status": "completed" },
    { "id": "step_5", "title": "生成研判结果", "detail": "整合多源数据形成结构化结论", "time": "15:34:18", "status": "completed" }
  ],
  "subjects": [
    {
      "id": "person_masked_01",
      "name": "张某",
      "fields": [
        { "label": "性别", "value": "男" },
        { "label": "年龄", "value": "36岁" },
        { "label": "身份证", "value": "320322********1234" },
        { "label": "户籍地", "value": "江苏省沛县汉城街道***" },
        { "label": "现居住地", "value": "沛县经济开发区***小区" }
      ],
      "tags": ["夜间活跃", "重点关注人员", "多名同行人员", "关联车辆"]
    }
  ],
  "conclusions": [
    "最近30天夜间活动频繁，共出现42次，主要集中在22:00—02:00时段。",
    "与王某、李某等3人关联密切，共同出现12次。",
    "活动地点主要集中在沛县经济开发区及周边区域。",
    "关联车辆苏C12345多次与目标对象存在夜间同行记录。"
  ],
  "evidence": [
    { "type": "trajectory", "title": "轨迹记录", "value": 42, "unit": "条", "summary": "最近30天夜间", "items": ["活动覆盖经济开发区、工业园等区域"] },
    { "type": "companion", "title": "同行人员", "value": 6, "unit": "人", "summary": "其中重点关注3人", "items": ["与王某共同出现12次"] },
    { "type": "vehicle", "title": "关联车辆", "value": 2, "unit": "辆", "summary": "苏C12345等", "items": ["存在11次轨迹高度重合"] },
    { "type": "place", "title": "高频地点", "value": 5, "unit": "个", "summary": "主要在工业园周边", "items": ["夜间出现频次较高"] }
  ],
  "next_steps": "建议进一步核验王某、李某的身份背景及共同活动目的，并结合原始资料复核苏C12345的完整活动轨迹。",
  "clues": [
    {
      "id": "clue_person_01",
      "type": "person",
      "title": "关联人员线索",
      "headline": "王某与张某共同出现12次",
      "summary": "王某（320322********5678）与张某在最近30天内多次在夜间共同出现，行为轨迹高度重合。",
      "time": "15:33",
      "level": "高",
      "source": "人员夜间活动分析",
      "discoveries": [
        "近30天共同出现12次，时空重合度较高。",
        "主要出现在沛县经济开发区、某工业园、汉城路周边。",
        "多在22:00—02:00时段共同活动。"
      ],
      "evidence": [
        { "type": "trajectory", "label": "2026-08-15 22:18", "content": "两人在某工业园西门附近同时出现，停留约1小时20分钟。" },
        { "type": "trajectory", "label": "2026-08-21 23:06", "content": "两人同时出现在某娱乐场所，停留约2小时。" }
      ]
    }
  ]
}
```

## 4. 字段说明

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `schema` | 是 | 固定为 `peixian.analysis-result`，用于防止误判普通 JSON。 |
| `version` | 是 | 当前固定为 `1.0`；破坏性变更升级主版本。 |
| `run_id` | 否 | 与运行轨迹、证据链和调用审计关联。正式环境建议返回。 |
| `generated_at` | 否 | ISO 8601 时间。 |
| `intro` | 否 | 结构化结果上方的自然语言说明。 |
| `process` | 是 | 可审计研判步骤；状态为 `pending/running/completed/failed`。 |
| `subjects` | 是 | 0—N 个目标对象，不传人物照片；字段使用 label/value 便于演进。 |
| `conclusions` | 是 | 核心结论文本数组。 |
| `evidence` | 是 | 研判依据卡片；前端最多展示前4张。 |
| `next_steps` | 否 | 按普通文本展示，不生成按钮和链接。 |
| `clues` | 是 | 0—N 条智能发现线索；为空时右侧不显示线索栏。 |

V1.0 优先识别的依据类型为 `trajectory`、`companion`、`vehicle`、`place`。未知类型使用通用卡片渲染，不应导致整条消息失败。

V1.0 优先识别的线索类型为 `person`、`vehicle`、`place`、`trajectory`。未知类型使用通用图标和蓝色主题。

## 5. 演进规则

- 可以向对象增加新字段；前端必须忽略未知字段。
- 可以增加新的依据和线索 `type`；前端使用通用兜底样式。
- 不得改变既有字段的数据类型；需要改变时升级到 `2.0`。
- 数组无数据时返回 `[]`，不要返回 `null`。
- 文本不存在时省略可选字段，不要返回字符串 `null`。
- 所有身份证、手机号、车主信息等敏感内容应在后端脱敏后返回。
- 单条 `summary/content` 应保持精炼；完整原始记录通过受控详情接口获取，不直接塞入消息。

机器可读 JSON Schema：`specs/contracts/analysis-result.schema.json`。
