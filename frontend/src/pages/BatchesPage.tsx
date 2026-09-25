import { useEffect, useState } from "react";
import { api } from "../api/client";
type P = { id: number; name: string }; type O = { id: number; label: string };
type B = { id: number; code: string; product_name?: string; oven_label?: string; start_min: number; ferment_end?: number; bake_end?: number; status: string; chain_group?: string | null; chain_max_gap_min?: number | null };
type Draft = { group: string; gap: number };
function fmt(m: number) { const h = Math.floor(m/60), mm = m%60; return `${String(h).padStart(2,"0")}:${String(mm).padStart(2,"0")}`; }
export default function BatchesPage() {
  const [products, setProducts] = useState<P[]>([]);
  const [ovens, setOvens] = useState<O[]>([]);
  const [rows, setRows] = useState<B[]>([]);
  const [pid, setPid] = useState<number | "">(""); const [oid, setOid] = useState<number | "">("");
  const [start, setStart] = useState(11 * 60);
  const [group, setGroup] = useState(""); const [gap, setGap] = useState(0);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [msg, setMsg] = useState(""); const [err, setErr] = useState("");
  const reload = () => api<B[]>("/batches").then(setRows);
  useEffect(() => {
    api<P[]>("/products").then(p => { setProducts(p); if (p[0]) setPid(p[0].id); });
    api<O[]>("/ovens").then(o => { setOvens(o); if (o[0]) setOid(o[0].id); });
    reload();
  }, []);
  useEffect(() => {
    const d: Record<number, Draft> = {};
    for (const b of rows) d[b.id] = { group: b.chain_group ?? "", gap: b.chain_max_gap_min ?? 0 };
    setDrafts(d);
  }, [rows]);
  async function create() {
    setMsg(""); setErr("");
    const g = group.trim();
    try {
      const b = await api<B>("/batches", { method: "POST", body: JSON.stringify({
        product_id: pid, oven_id: oid, start_min: start,
        chain_group: g || null, chain_max_gap_min: g ? gap : null,
      }) });
      setMsg(`已排产 ${b.code}`);
      reload();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }
  async function saveChain(b: B) {
    setMsg(""); setErr("");
    const d = drafts[b.id]; if (!d) return;
    const g = d.group.trim();
    try {
      await api<B>(`/batches/${b.id}`, { method: "PATCH", body: JSON.stringify({
        chain_group: g || null, chain_max_gap_min: g ? d.gap : null,
      }) });
      setMsg(`已更新 ${b.code} 连烤设置`);
      reload();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }
  function setDraft(id: number, patch: Partial<Draft>) {
    setDrafts(d => {
      const cur = d[id] ?? { group: "", gap: 0 };
      return { ...d, [id]: { ...cur, ...patch } };
    });
  }
  return (<>
    <h2>批次</h2>
    <div className="toolbar">
      <select value={pid} onChange={e => setPid(Number(e.target.value))}>{products.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      <select value={oid} onChange={e => setOid(Number(e.target.value))}>{ovens.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}</select>
      <label>开工分钟 <input type="number" value={start} onChange={e => setStart(Number(e.target.value))} style={{ width: 90 }} /></label>
      <label>连烤组号 <input className="chain-input" value={group} placeholder="不填=单批" onChange={e => setGroup(e.target.value)} /></label>
      <label>最大空档(分) <input className="chain-gap" type="number" min={0} value={gap} disabled={!group.trim()} onChange={e => setGap(Number(e.target.value))} /></label>
      <button onClick={create}>创建生产批次</button>
    </div>
    {msg && <div className="ok">{msg}</div>}
    {err && <div className="err">{err}</div>}
    <table className="table"><thead><tr><th>批次</th><th>产品</th><th>炉位</th><th>发酵</th><th>烘烤结束</th><th>连烤组号</th><th>最大空档</th><th>状态</th><th></th></tr></thead>
    <tbody>{rows.map(b => {
      const d = drafts[b.id] ?? { group: "", gap: 0 };
      return <tr key={b.id}><td className="mono">{b.code}</td><td>{b.product_name}</td><td>{b.oven_label}</td>
        <td className="mono">{fmt(b.start_min)}–{fmt(b.ferment_end ?? b.start_min)}</td>
        <td className="mono">{fmt(b.bake_end ?? b.start_min)}</td>
        <td><input className="chain-input" value={d.group} placeholder="不连烤" onChange={e => setDraft(b.id, { group: e.target.value })} /></td>
        <td><input className="chain-gap" type="number" min={0} value={d.gap} disabled={!d.group.trim()} onChange={e => setDraft(b.id, { gap: Number(e.target.value) })} /></td>
        <td>{b.status}</td>
        <td><button className="chain-save" onClick={() => saveChain(b)}>保存</button></td></tr>;
    })}</tbody></table>
  </>);
}
