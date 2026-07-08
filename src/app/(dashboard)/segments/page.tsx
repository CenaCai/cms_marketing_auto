import Placeholder from "@/components/Placeholder";

export default function SegmentsPage() {
  return (
    <Placeholder
      title="Segments"
      desc="静态 / 动态分群。动态分群基于 rules JSON（国家/标签/活跃度/是否购买等），发送与 Workflow 触发时即时求值。后端 API：GET/POST /api/segments、成员管理 /api/segments/[id]/members、求值 /api/segments/[id]/evaluate。"
    />
  );
}
