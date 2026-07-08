import Papa from "papaparse";
import ExcelJS from "exceljs";
import { prisma } from "@/lib/db";

// 字段映射：源列名 -> 联系人字段
export type ContactFieldMap = Record<string, "name" | "email" | "phone" | "country" | "city" | "language" | "source">;

// 解析 CSV 文本为联系人行
export function parseCsv(text: string, map: ContactFieldMap) {
  const parsed = Papa.parse<string[]>(text, { skipEmptyLines: true });
  const rows = parsed.data as string[][];
  if (rows.length < 2) return [];
  const header = rows[0];
  return rows.slice(1).map((r) => {
    const obj: Record<string, string> = {};
    header.forEach((h, i) => {
      const target = (map[h] as string) ?? "";
      if (target) obj[target] = r[i] ?? "";
    });
    return obj;
  });
}

// 解析 Excel buffer 为联系人行（依赖 exceljs）
export async function parseExcel(buffer: Buffer, map: ContactFieldMap) {
  const wb = new ExcelJS.Workbook();
  await wb.xlsx.load(buffer as any);
  const ws = wb.worksheets[0];
  if (!ws) return [];
  const header: string[] = [];
  const rows: Record<string, string>[] = [];
  ws.eachRow((row, rowNumber) => {
    const values = row.values as any[];
    if (rowNumber === 1) {
      values.slice(1).forEach((v) => header.push(String(v ?? "")));
      return;
    }
    const obj: Record<string, string> = {};
    values.slice(1).forEach((v, i) => {
      const target = (map[header[i]] as string) ?? "";
      if (target) obj[target] = String(v ?? "");
    });
    rows.push(obj);
  });
  return rows;
}

export interface ImportResult {
  total: number;
  success: number;
  failed: number;
  duplicate: number;
  errors: { row: number; reason: string }[];
}

// 将解析后的行导入联系人中心（带去重与错误报告）
export async function importContacts(
  orgId: string,
  rows: Record<string, string>[],
): Promise<ImportResult> {
  const result: ImportResult = {
    total: rows.length,
    success: 0,
    failed: 0,
    duplicate: 0,
    errors: [],
  };

  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    try {
      const email = r.email?.trim() || undefined;
      const phone = r.phone?.trim() || undefined;
      if (!email && !phone) {
        result.failed++;
        result.errors.push({ row: i + 2, reason: "邮箱与手机号均缺失" });
        continue;
      }
      const existing = await prisma.contact.findFirst({
        where: {
          organizationId: orgId,
          OR: [email ? { email } : { id: "__none__" }, phone ? { phone } : { id: "__none__" }],
        },
      });
      if (existing) {
        result.duplicate++;
        continue;
      }
      await prisma.contact.create({
        data: {
          organizationId: orgId,
          name: r.name,
          email,
          phone,
          country: r.country,
          city: r.city,
          language: r.language,
          source: r.source ?? "import",
        },
      });
      result.success++;
    } catch (e: any) {
      result.failed++;
      result.errors.push({ row: i + 2, reason: e?.message ?? "未知错误" });
    }
  }
  return result;
}
