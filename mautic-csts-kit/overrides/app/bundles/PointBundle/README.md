# PointBundle 核心修复（TriggerModel::invokeCallback）

本目录下的 `Model/TriggerModel.php` 是 Mautic 7 核心文件 `PointBundle/Model/TriggerModel.php` 的**修复版**，需覆盖到运行实例的对应核心文件才能生效。

## 修复内容
`TriggerModel::invokeCallback()` 原代码用 `$this` 调用其它类的实例方法回调（如积分触发器 `email.send` → `PointEventHelper::sendEmail`），会抛 `ReflectionException: Given object is not an instance of the class`，导致「打标签 + 发邮件」类积分触发器事件无法执行。修复后改用回调真实实例 `$callback[0]` 作为 invoker。

## 适用本 CSTS 定制版 Mautic（核心 bundle 位于 app/bundles）
复制本文件覆盖运行时核心文件：
```
cp mautic-csts-kit/overrides/app/bundles/PointBundle/Model/TriggerModel.php \
   <mautic根目录>/app/bundles/PointBundle/Model/TriggerModel.php
```
然后重建缓存（避免 SMTP 预热卡死，用惰性重建）：
```
rm -rf <mautic根目录>/var/cache/prod
```

## 适用标准版 Mautic（composer 管理，核心在 vendor）
文件位于 `vendor/mautic/point-bundle/Model/TriggerModel.php`，复制到此处同样生效；注意 `composer update` 会覆盖，建议用 patch 管理（见下方 diff 思路：仅改 `invokeCallback()` 中 `$reflection->invokeArgs($this, $pass)` 为 `$reflection->invokeArgs($invoker, $pass)`，其中 `$invoker = is_array($callback) ? $callback[0] : null`）。

## 是否必须
- 新漏斗（Campaign#8 潜客工作流 / Campaign#9 意向客转化）的邮件发送走 campaign 执行引擎，**不经过** `TriggerModel`，因此不依赖此修复。
- 仅当需要使用「积分触发器(TRIG#1/#2)直接发送营销邮件(#4/#5)」时才必须应用本修复。
