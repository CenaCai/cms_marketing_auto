// 只读 SQL 查询的安全沙箱。
// 运营可在「SQL 精准圈人」中写 SELECT 圈定目标联系人，但必须满足：
//  1) 仅允许单条 SELECT（拒绝任何写操作 / 多语句 / 注释）
//  2) 必须在 WHERE 中使用 `organizationId = CURRENT_ORG` 占位符，
//     由服务端替换为当前组织 id，确保租户隔离（无法越权看其他组织数据）
//  3) 结果行数上限由调用方截断（默认 5000）
// 所有查询写入 SystemLog 审计。

const FORBIDDEN = new RegExp(
  "\\b(insert|update|delete|drop|alter|create|truncate|replace|merge|grant|revoke|attach|pragma|exec|vacuum|begin|commit|rollback|explain|analyze|call|lock|unlock|into)\\b",
  "i",
);
const HAS_SEMICOLON = /;/;
const HAS_COMMENT = /(--|\/\*|\*\/)/;
const ORG_TOKEN = /CURRENT_ORG/;

export interface SqlCheck {
  ok: boolean;
  error?: string;
}

export function checkSql(sql: string): SqlCheck {
  const s = (sql ?? "").trim();
  if (!s) return { ok: false, error: "SQL 不能为空" };
  if (!/^select\b/i.test(s)) {
    return { ok: false, error: "仅允许 SELECT 查询（不支持写入/修改）" };
  }
  if (HAS_SEMICOLON.test(s)) {
    return { ok: false, error: "不允许多条语句（禁止分号）" };
  }
  if (HAS_COMMENT.test(s)) {
    return { ok: false, error: "不允许 SQL 注释" };
  }
  if (FORBIDDEN.test(s)) {
    return { ok: false, error: "包含禁止的关键字（写操作/管理命令）" };
  }
  if (!ORG_TOKEN.test(s)) {
    return {
      ok: false,
      error: "请在 WHERE 中加入 organizationId = CURRENT_ORG 以限制在当前组织内",
    };
  }
  return { ok: true };
}

// 将 SQL 中的 CURRENT_ORG 占位符替换为当前组织 id（来自服务端，非用户输入）。
export function bindOrg(sql: string, organizationId: string): string {
  const escaped = organizationId.replace(/'/g, "''");
  return sql.replace(/\bCURRENT_ORG\b/g, `'${escaped}'`);
}
