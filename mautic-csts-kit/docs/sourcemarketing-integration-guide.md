# SourceMarketingBundle —— 联调与集成指南

来源营销自动化插件。对外暴露一组 **公开 HTTP 端点**（无需登录），供外部平台/脚本推送事件、查询频次闸门、读取来源日志、做时间锚点仲裁、执行去重冻结降级，以及**按联系人国家字段解析推送时区与邮件可发策略**。

所有端点共用一个 token，定义在插件 `Config/config.php` 的 `sourcemarketing_token`（默认 `sourcemarketing-dev-secret`）。token 既能在 `config/local.php` 覆盖，也走插件默认值——**放插件 config.php 可避免后台 UI 重写 local.php 时把该键悄悄丢掉**。

> 传参支持 JSON body / form / query 三种；控制器内自行 `json_decode($request->getContent())`，核心无 JSON 监听器。

---

## 1. 公开端点总览

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/sourcemarketing/event` | 接收外部平台来源事件（打标签/进分群/触发活动） |
| GET/POST | `/sourcemarketing/frequency/check` | 频次闸门预检：返回 `allowed` / `reason` / `tz_source` / `local_time` 等 |
| GET/POST | `/sourcemarketing/channel-log` | 读来源渠道发送日志 |
| GET/POST | `/sourcemarketing/arbitrate` | 时间锚点仲裁（多来源撞车时决定走哪条） |
| GET/POST | `/sourcemarketing/guard` | 去重 / 冻结 / 降级 / 黑名单闸门 |
| GET/POST | `/sourcemarketing/country-policy` | **只读**查看某国家/联系人的时区 + 邮件可发策略（调试用） |

画布节点（Campaign 里可用）：`sourcemarketing.frequency_gate`(decision) / `sourcemarketing.log_channel` / `sourcemarketing.arbitrate` / `sourcemarketing.guard`。

---

## 2. 推送时间走「国家字段」

这是本期核心能力。规则：**优先用联系人 `country` 字段自动匹配时区；country 为空则回退服务器时间（Mautic 后台「默认时区」）**。

### 2.1 三级时区解析链（`FrequencyGateService::resolveTimezone`）

按优先级取第一个可用的 IANA 时区：

1. **联系人 `timezone` 字段**（显式、最精确）——如填了 `America/Los_Angeles` 直接用。
2. **联系人 `country` 字段**（自动映射）——`CountryPolicyService` 把国家名/ISO2/ISO3/中文名解析成 IANA 时区（如 `中国`/`CN`/`CHN` → `Asia/Shanghai`，`US` → `America/New_York` 而非 `America/Adak`）。
3. **服务器默认**——`CountryPolicyService::serverTimezone()` 读 Mautic `default_timezone` 配置，再退回 PHP `date_default_timezone_get()` / `UTC`。

`resolveTimezone()` 同时返回 `tz_source`（`contact_timezone` / `country` / `server_default`），频次预检里能看到**到底是哪个时钟在作主**。

### 2.2 静默窗口（按国家）

默认全局静默 **22:00–08:00**（当地时区）。每个国家可在配置里覆盖（见 §4）。`inSilenceWindow()` 用解析出的时区判断当前当地小时是否落在窗口内（支持跨午夜）。

### 2.3 邮件可发策略（按国家 / 司法辖区）

仅对 **email 渠道** 做辖区管控（sms 等其它渠道只走静默窗口，不拦截）：

- `allow` —— 可发。
- `block` —— 国家层面禁止（如配置 `blocked: ['KP']`），返回 `country_blocked:XX`。
- `consent_required` —— 需同意，联系人有 `email_consent` 字段（1/yes/true/optin）或 `consent_optin` 标签才放行，否则 `country_consent_required:XX`。由 `consent_required_enabled` 总开关 + `EEA_CONSENT` 默认列表（GDPR/EEA + UK + CH）控制。

`FrequencyGateService::isAllowed()` 顺序：先 `checkCountryPolicy()`（仅 email），再 `inSilenceWindow()`。

### 2.4 国家字段归一化（入库即规范）

外部平台传 `country` 时，`PublicController`  ingest 会用 `CountryPolicyService::normalizeName()` 归一化成 Mautic `country` 字段期望的**英文全名**（`中国`/`CN`/`CHN` → `China`），保证和 Mautic 自带的 `Symfony\Component\Intl\Countries` 取值一致，后续筛选/报告才不会乱。

---

## 3. `/sourcemarketing/country-policy` 调试端点

只读、不建联系人，用来确认「某国家/某联系人会被怎么判」。

```
GET /sourcemarketing/country-policy?token=...&country=China
GET /sourcemarketing/country-policy?token=...&email=someone@example.com
```

返回示例：

```json
{
  "ok": true,
  "input": "China",
  "alpha2": "CN",
  "country_name": "China",
  "resolved": true,
  "timezone": "Asia/Shanghai",
  "local_time": "2026-08-04 10:49",
  "silence_window": "22:00-08:00",
  "in_silence": false,
  "email_policy": "allow",
  "email_allowed": true,
  "needs_consent": false
}
```

- 传 `country` 直接按国家解析；传 `email` 按该联系人现有时区/国家字段解析。
- 两者都不传会返回 `{"ok":false,"error":"country_or_contact_required"}`（该端点需要目标才能展示；**空 country 的服务器默认回退只在真实发送时序链里生效，不在此调试端点**）。

`frequency/check` 也会在响应里带上 `timezone` / `tz_source` / `local_time`，方便确认当前用的是哪一级时钟。

---

## 4. 配置覆盖（操作员可调，无需改代码）

插件 `Config/config.php` 的 `parameters` 块已声明默认值；要覆盖就在 `config/local.php` 写同键（local.php 优先）：

```php
'sourcemarketing_country_policy' => [
    'blocked'                => [],   // 国家层面禁发邮件的 alpha2 列表
    'consent_required_enabled'=> false, // 是否开启「需同意」管控
    'consent_required'       => [],   // 额外强制需同意的 alpha2（与 EEA_CONSENT 合并）
    'timezone'   => [],    // ['US' => 'America/Chicago'] 覆盖某国主时区
    'silence'    => [],    // ['JP' => [21, 9]] 覆盖某国静默窗口 [start, end]
],
```

- 改完清缓存（`php bin/console cache:clear --env=prod`，dev server 则删 `var/cache/prod`）后首个请求约 30s 重建容器。
- `sourcemarketing_token` 同样建议放插件 config（已放），避免后台 UI 重写 local.php 时丢失。

---

## 5. 与外部平台联调要点

1. **推事件带国家**：平台侧在 `event` 负载里带 `country`（ISO2 最稳，也接受中文/英文/ISO3）。插件入库即归一化为英文全名。
2. **发信前先查闸门**：`frequency/check` 返回 `allowed=false` 时，按 `reason` 处理——
   - `silence_window` → 当地静默时段，稍后重试；
   - `country_blocked:XX` → 该国禁发，平台侧直接放弃该联系人邮件；
   - `country_consent_required:XX` → 平台侧先走同意采集，再标记 `email_consent` 或打 `consent_optin` 标签后重试。
3. **不确定时区/策略用 `country-policy` 自查**，不建联系人，安全调试。
4. **时区来源透明**：`tz_source` 让平台知道当前判定依据的是联系人显式时区、国家映射、还是服务器默认——便于排查「为什么这个联系人半夜收到了邮件」。

---

## 6. 关键文件

| 文件 | 作用 |
|------|------|
| `Service/CountryPolicyService.php` | 国家→(时区/静默窗口/邮件策略) 解析器，自动覆盖 ~250 个 ISO 国家 |
| `Service/FrequencyGateService.php` | 频次闸门 + 三级时区链 + 辖区邮件策略拦截 |
| `Controller/PublicController.php` | 公开端点 + 国家字段归一化 + `country-policy` 调试端点 |
| `Config/config.php` | 路由 + `sourcemarketing_token` / `sourcemarketing_country_policy` 默认参数 |
| `Config/services.php` | 服务注册（含 `CountryPolicyService` 自动装配） |
