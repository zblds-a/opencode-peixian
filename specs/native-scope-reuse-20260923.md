# 已确认范围复用与字段级预检反馈

## 状态

四项改动已在非评分候选源码实现，独立容器定向回归39 passed / 2 warnings。未部署、未修改线上提示词或评分逻辑、未调用真实资料或模型，不能记为生产或浏览器验收。候选基线为 efe5cdbbba1e0b595fadb85db0afd38d4207333d。

## 行为

1. 原生工具可省略当前任务已确认的人员及适用起止时间，由服务端在冻结调用前补齐；仍绑定当前账号、会话、任务和范围版本。选定来源时继续从受控来源派生对象，不以模型参数覆盖。抓拍只补齐本轮独立确认条件，不沿用轨迹范围。
2. 精确到秒的日期时间只统一空格/T分隔，不猜测日期、时区或缺失秒；整数参数允许纯数字字符串，拒绝布尔和小数；经纬度、半径采用十进制等价表示，不改变单位和实际值。最终合同上下限检查保留。
3. page=1、page_size=20仅在该字段没有已确认用户值时作为合同默认值接受。不得覆盖用户指定分页，也不允许自动翻页。
4. scope_unconfirmed、scope_missing、scope_parameter_invalid返回field_errors。网关仅传递白名单字段中文标签，不回显身份证或上游任意正文；模型上下文明确这些不是授权错误，要求只询问对应字段、不得自行改换参数重试。

不新增固定业务步骤，不取消授权、来源归属、配置版本、取消状态、独立意图核对和出口检查。不改变原始模型参数摘要：同一call_id换参数仍冲突，补齐后的规范化参数进入冻结计划及独立核对。

## 代码位置与调用顺序

| 层次 | 文件与入口 | 职责 |
|---|---|---|
| 参数补齐与范围 | services/peixian-control/control/native_tool_scope.py：resolve_arguments / arguments | 补齐确认值、格式规范化、范围比较、缺项及用途检查；scope_unconfirmed出自这里 |
| 执行准入 | services/peixian-control/control/native_tool_gate.py：prepare / approve | 账号授权、Run状态、配置版本、调用去重和核对结论绑定 |
| 网关反馈 | services/peixian-control/gateway/facts_execution.py | 空参数仍走原生调用身份核对；缺项字段安全传给模型 |
| 独立意图核对 | gateway/theft_provider_execution.py、shared/native_intent_review.py | 判断拟调用是否服务于用户目标；不是参数格式校验 |
| 插件出口 | provider_contracts 与资料出口 | 固定能力合同、地址、方法、边界与响应限制 |

提示词没有被上述代码禁用：模型提出工具调用后才经过这些执行边界。不能由提示词把不一致的参数变成已确认条件。

## 测试与限制

覆盖同任务复用、等价时间/整数、默认分页、缺项字段、拒绝范围扩大、拒绝猜日期或时区、拒绝抓拍继承轨迹时间、拒绝非默认分页、原生空参数身份校验、字段脱敏、撤权及未知调用不重放。

第一次测试包漏带jsonl夹具，收集失败；补齐后37项通过。补充网关测试时Mock响应漏设request，1项失败；修正测试夹具后最终39项全部通过。没有通过放宽产品校验消除失败。

运行命令（services/peixian-control目录）：

```text
python -m pytest -p no:cacheprovider tests/test_native_scope_repair.py tests/test_native_tool_execution.py tests/test_native_scope_gateway.py -q
```

服务器测试目录：/srv/peixian-scope-candidate-20260923。测试容器无网络，源码只读挂载，无生产数据卷。前端未改动。提示词可指导不猜授权、不重试，但本轮未以真实模型对话证明其绝不偏离。
