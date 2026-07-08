import Placeholder from "@/components/Placeholder";

export default function TemplatesPage() {
  return (
    <Placeholder
      title="Templates"
      desc="EDM（HTML + 变量 {{first_name}} 等）/ SMS（纯文本）模板，支持预览与测试发送。变量渲染使用 Handlebars。后端 API：GET/POST /api/templates、PATCH /api/templates/[id]。"
    />
  );
}
