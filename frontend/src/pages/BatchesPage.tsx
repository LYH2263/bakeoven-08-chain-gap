import { useEffect, useState } from "react";
import { api } from "../api/client";
type P = { id: number; name: string }; type O = { id: number; label: string };
type B = {
  id: number; code: string; product_name?: string; oven_label?: string;
  start_min: number; ferment_end?: number; bake_end?: number; status: string;
  chain_group?: string | null; chain_max_gap_min?: number | null;
};
type G = { id: number; name: string; max_gap_min: number; member_codes: string[] };
function fmt(m: number) { const h = Math.floor(m/60), mm = m%60; return `${String(h).padStart(2,"0")}:${String(mm).padStart(2,"0")}`; }
export default function BatchesPage() {
  const [products, setProducts] = useState<P[]>([]);
  const [ovens, setOvens] = useState<O[]>([]);
  const [groups, setGroups] = useState<G[]>([]);
  const [rows, setRows] = useState<B[]>([]);
  const [pid, setPid] = useState<number | "">(""); const [oid, setOid] = useState<number | "">("");
  const [start, setStart] = useState(11 * 60); const [msg, setMsg] = useState(""); const [err, setErr] = useState("");
  const [group, setGroup] = useState(""); const [gap, setGap] = useState(0);
  // per-row editing drafts: rowId -> {group, gap}
  const [drafts, setDrafts] = useState<Record<number, { group: string; gap: number }>>({});
  const [rowErr, setRowErr] = useState<Record<number, string>>({});
  const [rowOk, setRowOk] = useState<Record<number, boolean>>({});
  const reload = () => { api<B[]>("/batches").then(setRows); api<G[]>("/chain-groups").then(setGroups).catch(() => {}); };
  useEffect(() => {
    api<P[]>("/products").then(p => { setProducts(p); if (p[0]) setPid(p[0].id); });
    api<O[]>("/ovens").then(o => { setOvens(o); if (o[0]) setOid(o[0].id); });
    reload();
  }, []);
  // Typing an existing group's exact name adopts its registered max gap.
  useEffect(() => {
    const g = groups.find(x => x.name === group.trim());
    if (g) setGap(g.max_gap_min);
  }, [group, groups]);
  function draftOf(b: B) {
    return drafts[b.id] ?? { group: b.chain_group ?? "", gap: b.chain_max_gap_min ?? 0 };
  }
  function setDraft(b: B, patch: Partial<{ group: string; gap: number }>) {
    setDrafts(d => ({ ...d, [b.id]: { ...draftOf(b), ...patch } }));
  }
  async function create() {
    setMsg(""); setErr("");
    try {
      const body: Record<string, unknown> = { product_id: pid, oven_id: oid, start_min: start };
      if (group.trim()) { body.chain_group = group.trim(); body.chain_max_gap_min = gap; }
      const b = await api<B>("/batches", { method: "POST", body: JSON.stringify(body) });
      setMsg(`已排产 ${b.code}${body.chain_group ? `（连烤组 ${body.chain_group}）` : ""}`);
      reload();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }
  async function saveChain(b: B) {
    const d = draftOf(b);
    setRowErr(e => { const n = { ...e }; delete n[b.id]; return n; });
    setRowOk(o => { const n = { ...o }; delete n[b.id]; return n; });
    try {
      const body: Record<string, unknown> = { chain_group: d.group.trim() || null };
      if (d.group.trim()) body.chain_max_gap_min = d.gap;
      await api<B>(`/batches/${b.id}`, { method: "PATCH", body: JSON.stringify(body) });
      setRowOk(o => ({ ...o, [b.id]: true }));
      setDrafts(x => { const n = { ...x }; delete n[b.id]; return n; });
      reload();
    } catch (e) {
      setRowErr(x => ({ ...x, [b.id]: e instanceof Error ? e.message : String(e) }));
    }
  }
  return (<>
    <h2>批次</h2>
    <div className="toolbar">
      <select value={pid} onChange={e => setPid(Number(e.target.value))}>{products.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      <select value={oid} onChange={e => setOid(Number(e.target.value))}>{ovens.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}</select>
      <label>开工分钟 <input type="number" value={start} onChange={e => setStart(Number(e.target.value))} style={{ width: 90 }} /></label>
      <label>连烤组号 <input value={group} onChange={e => setGroup(e.target.value)} placeholder="留空=单批" style={{ width: 100 }} /></label>
      <label>最大空档(分) <input type="number" min={0} value={gap} onChange={e => setGap(Math.max(0, Number(e.target.value)))} style={{ width: 90 }} disabled={!group.trim()} /></label>
      <button onClick={create}>创建生产批次</button>
    </div>
    {msg && <div className="ok">{msg}</div>}
    {err && <div className="err">{err}</div>}
    <table className="table"><thead><tr><th>批次</th><th>产品</th><th>炉位</th><th>发酵</th><th>烘烤结束</th><th>连烤组号</th><th>最大空档</th><th>状态</th><th></th></tr></thead>
    <tbody>{rows.map(b => {
      const d = draftOf(b);
      return (<tr key={b.id}>
        <td className="mono">{b.code}{b.chain_group && <span className="chain-badge" title="同炉连烤组">{b.chain_group}</span>}</td>
        <td>{b.product_name}</td><td>{b.oven_label}</td>
        <td className="mono">{fmt(b.start_min)}–{fmt(b.ferment_end ?? b.start_min)}</td>
        <td className="mono">{fmt(b.bake_end ?? b.start_min)}</td>
        <td><input value={d.group} placeholder="单批" style={{ width: 80 }}
          onChange={e => setDraft(b, { group: e.target.value })} /></td>
        <td><input type="number" min={0} value={d.gap} style={{ width: 70 }} disabled={!d.group.trim()}
          onChange={e => setDraft(b, { gap: Math.max(0, Number(e.target.value)) })} /></td>
        <td>{b.status}</td>
        <td><button className="row-save" onClick={() => saveChain(b)}>保存</button>
          {rowOk[b.id] && <span className="row-ok">已存</span>}
          {rowErr[b.id] && <div className="err row-err" title={rowErr[b.id]}>{rowErr[b.id]}</div>}
        </td>
      </tr>);
    })}</tbody></table>
  </>);
}
