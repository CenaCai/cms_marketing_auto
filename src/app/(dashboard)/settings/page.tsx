import Placeholder from "@/components/Placeholder";

export default function SettingsPage() {
  return (
    <Placeholder
      title="Settings"
      desc="组织、成员、角色权限（RBAC）、API Keys、Webhooks、发送通道（Email/SMS provider）、系统日志。发送通道通过在 .env 配置 EMAIL_PROVIDER / SMS_PROVIDER 切换真实三方服务，详见 THIRD_PARTY_INTEGRATIONS.md。"
    />
  );
}
