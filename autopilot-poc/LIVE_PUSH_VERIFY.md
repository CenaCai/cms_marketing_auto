# Mautic 7 活推送连线验证报告（campaign #66）

- 环境：`http://localhost:8080`（用户本机 Mautic 7.1.3）
- 创建结果：`POST /api/campaigns/new` → **HTTP 201**, campaign_id=**66**
- isPublished：False（默认下线，审批后上线）

## 事件表（11 个，parent 全部正确）

| id | type | eventType | parent | decisionPath | name |
|----|------|-----------|--------|--------------|------|
| 90316 | lead.field_value | condition | None | None | decision.segment（治理/观测） |
| 90317 | lead.field_value | condition | 90316 | None | guardrail（治理/观测） |
| 90318 | lead.field_value | condition | 90317 | None | anchor_arbitration（治理/观测） |
| 90319 | email.send | action | 90318 | None | 发送邮件：OAuth2 活推送连线验证 |
| 90320 | email.click | decision | 90319 | None | 决策：是否点击 |
| 90321 | lead.field_value | condition | 90320 | yes | page.hit（治理/观测） |
| 90324 | email.send | action | 90320 | no | 发送邮件：提醒：OAuth2 活推送连线验证测试 2026 |
| 90322 | lead.changetags | action | 90321 | None | 打标签：['oauth_live_test'] |
| 90325 | lead.changetags | action | 90324 | None | 打标签：['oauth_live_test'] |
| 90323 | lead.field_value | condition | 90322 | None | log_channel_send（治理/观测） |
| 90326 | lead.field_value | condition | 90325 | None | log_channel_send（治理/观测） |

## 画布连线（11 条，anchors.source 全部非空）

```
90316 --[bottom->top]--> 90317
90317 --[bottom->top]--> 90318
90318 --[bottom->top]--> 90319
90319 --[bottom->top]--> 90320
90320 --[yes->top]--> 90321
90321 --[bottom->top]--> 90322
90322 --[bottom->top]--> 90323
90320 --[no->top]--> 90324
90324 --[bottom->top]--> 90325
90325 --[bottom->top]--> 90326
lists --[leadsource->top]--> 90316
```

## 断言

- 根事件数=1（应为 1，leadsource 来源接入）
- 非根事件=10，缺失 parent 的事件=无
- anchors.source 为 null 的连线=无
- guardrail 持久化为只读条件 `lead.field_value`：是

**结果：PASS — 连线真实持久化，两个根因（anchors.source=null / lead.dnc）均已修复**
