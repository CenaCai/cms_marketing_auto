export default function Placeholder({
  title,
  desc,
}: {
  title: string;
  desc: string;
}) {
  return (
    <div className="card">
      <h2 style={{ fontSize: 18, marginBottom: 8 }}>{title}</h2>
      <p className="muted" style={{ fontSize: 14, lineHeight: 1.6 }}>
        {desc}
      </p>
      <div style={{ marginTop: 12, fontSize: 13 }} className="muted">
        该模块后端 API 已就绪，前端界面建设中。可直接调用对应 <code>/api/*</code> 接口。
      </div>
    </div>
  );
}
