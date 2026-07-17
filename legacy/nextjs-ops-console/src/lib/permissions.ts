// 权限矩阵使用的「模块」与「操作」定义。
// module: 对应后台各目录；action: 增删改查（view/create/edit/delete）。
export const MODULES = [
  { key: "contacts", label: "客户名单" },
  { key: "tags", label: "标签" },
  { key: "segments", label: "分群/分组" },
  { key: "templates", label: "邮件模板" },
  { key: "campaigns", label: "营销活动" },
  { key: "settings", label: "系统设置" },
  { key: "users", label: "账号管理" },
  { key: "reports", label: "报表" },
  { key: "ai", label: "AI 助手" },
] as const;

export const ACTIONS = [
  { key: "view", label: "查看" },
  { key: "create", label: "新增" },
  { key: "edit", label: "编辑" },
  { key: "delete", label: "删除" },
] as const;

export type ModuleKey = (typeof MODULES)[number]["key"];
export type ActionKey = (typeof ACTIONS)[number]["key"];

// 权限矩阵类型：module -> action -> 是否允许
export type PermissionMap = Record<string, Record<string, boolean>>;
