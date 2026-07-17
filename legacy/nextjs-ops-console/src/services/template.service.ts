import Handlebars from "handlebars";
import { prisma } from "@/lib/db";
type TemplateType = string;

export async function listTemplates(orgId: string, type?: TemplateType) {
  return prisma.template.findMany({
    where: { organizationId: orgId, ...(type ? { type } : {}) },
    orderBy: { createdAt: "desc" },
  });
}

export async function createTemplate(
  orgId: string,
  data: {
    type: TemplateType;
    name: string;
    subject?: string;
    body: string;
    variables?: string[];
  },
) {
  return prisma.template.create({
    data: {
      organizationId: orgId,
      ...data,
      // SQLite 不支持数组列：variables 以 JSON 字符串存储
      variables: data.variables ? JSON.stringify(data.variables) : undefined,
    },
  });
}

export async function updateTemplate(
  orgId: string,
  id: string,
  data: { name?: string; subject?: string; body?: string; variables?: string[] },
) {
  const { variables, ...rest } = data;
  return prisma.template.update({
    where: { id },
    data: { ...rest, ...(variables ? { variables: JSON.stringify(variables) } : {}) },
  });
}

export async function getTemplate(orgId: string, id: string) {
  return prisma.template.findFirst({ where: { organizationId: orgId, id } });
}

// 用联系人字段 + 自定义变量渲染模板（EDM 的 {{first_name}}、SMS 等）
export function renderTemplate(
  body: string,
  vars: Record<string, string | undefined>,
): string {
  try {
    const tpl = Handlebars.compile(body);
    return tpl(vars ?? {});
  } catch (e) {
    console.error("[template:render] error", e);
    return body;
  }
}
