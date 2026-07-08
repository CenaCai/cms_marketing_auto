import Placeholder from "@/components/Placeholder";

export default function TagsPage() {
  return (
    <Placeholder
      title="Tags"
      desc="标签管理：新建/编辑/删除标签，单联系人多标签，支持批量打标签与复合筛选（包含任一 / 包含全部 / 不包含指定）。后端 API：GET/POST /api/tags、PATCH/DELETE /api/tags/[id]、POST /api/tags/filter。"
    />
  );
}
