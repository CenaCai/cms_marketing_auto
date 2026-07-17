// 事件中心「默认事件目录」
// 统一的事件类型定义：用于事件列表筛选、时间线渲染、Mautic 回流归一。
// eventType 存库值 / label 展示名 / color 主题色 / icon 图标。

export type EventTypeDef = {
  type: string; // 存入 DB 的 eventType
  label: string; // 展示名（用户要求的标准事件）
  color: string;
  icon: string;
};

// 7 个默认事件 + 退订/发送（来自 EDM 回流）
export const EVENT_TYPES: EventTypeDef[] = [
  { type: "REGISTER", label: "Register", color: "#0891b2", icon: "📝" },
  { type: "LOGIN", label: "Login", color: "#0891b2", icon: "🔑" },
  { type: "BROWSE", label: "Browse", color: "#7c3aed", icon: "👀" },
  { type: "OPEN_EMAIL", label: "Open Email", color: "#2563eb", icon: "📬" },
  { type: "CLICK_LINK", label: "Click Link", color: "#2563eb", icon: "🔗" },
  { type: "PURCHASE", label: "Purchase", color: "#16a34a", icon: "💰" },
  { type: "REFUND", label: "Refund", color: "#dc2626", icon: "↩️" },
  { type: "UNSUBSCRIBE", label: "Unsubscribe", color: "#d97706", icon: "🚫" },
  { type: "SENT_EMAIL", label: "Sent Email", color: "#0ea5e9", icon: "📤" },
  { type: "CUSTOM", label: "Custom", color: "#64748b", icon: "•" },
];

// Mautic / 原始 eventName → 标准 eventType
const NAME_TO_TYPE: Record<string, string> = {
  register: "REGISTER",
  login: "LOGIN",
  browse: "BROWSE",
  page_view: "BROWSE",
  email_opened: "OPEN_EMAIL",
  open_email: "OPEN_EMAIL",
  email_clicked: "CLICK_LINK",
  click_link: "CLICK_LINK",
  link_clicked: "CLICK_LINK",
  email_unsubscribed: "UNSUBSCRIBE",
  unsubscribe: "UNSUBSCRIBE",
  email_sent: "SENT_EMAIL",
  sent_email: "SENT_EMAIL",
  purchase: "PURCHASE",
  order_paid: "PURCHASE",
  refund: "REFUND",
  order_refund: "REFUND",
};

// 将任意 eventType / eventName 归一到标准 eventType
export function resolveEventType(eventType?: string, eventName?: string): string {
  if (eventType && eventType !== "CUSTOM" && EVENT_TYPES.some((e) => e.type === eventType)) {
    return eventType;
  }
  if (eventName) {
    const mapped = NAME_TO_TYPE[eventName.toLowerCase()];
    if (mapped) return mapped;
  }
  return "CUSTOM";
}

export function eventMeta(type: string): EventTypeDef {
  return EVENT_TYPES.find((e) => e.type === type) ?? EVENT_TYPES[EVENT_TYPES.length - 1];
}
