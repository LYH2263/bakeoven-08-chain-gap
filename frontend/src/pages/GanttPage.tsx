import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { api } from "../api/client";
type Block = { batch_id: number; code: string; oven_id: number; oven_label: string; phase: string; start_min: number; end_min: number; chain_group?: string | null };
const DAY_START = 8 * 60, DAY_END = 18 * 60, SPAN = DAY_END - DAY_START;
function pct(m: number) { return ((m - DAY_START) / SPAN) * 100; }
// Stable, distinct markers per chain group (same group name -> same swatch).
const CHAIN_COLORS = ["#7ee0c0", "#8ab4ff", "#e0a0ff", "#ffd166", "#ff8fa3", "#9be15d", "#5ce1e6", "#f4a261"];
function hashName(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}
export default function GanttPage() {
  const [blocks, setBlocks] = useState<Block[]>([]);
  useEffect(() => { api<Block[]>("/gantt").then(setBlocks); }, []);
  const rows = useMemo(() => {
    const map = new Map<number, { label: string; blocks: Block[] }>();
    for (const b of blocks) {
      if (!map.has(b.oven_id)) map.set(b.oven_id, { label: b.oven_label, blocks: [] });
      map.get(b.oven_id)!.blocks.push(b);
    }
    return [...map.entries()];
  }, [blocks]);
  const groups = useMemo(() => {
    const names = [...new Set(blocks.map(b => b.chain_group).filter((g): g is string => !!g))].sort();
    return names.map(name => ({ name, color: CHAIN_COLORS[hashName(name) % CHAIN_COLORS.length] }));
  }, [blocks]);
  const colorOf = (g?: string | null) => groups.find(x => x.name === g)?.color;
  return (<>
    <h2>甘特（生产占炉）</h2>
    <div className="axis"><div /><div className="axis-scale"><span>08:00</span><span>12:00</span><span>18:00</span></div></div>
    <div className="gantt">
      {rows.map(([oid, row]) => (
        <div className="gantt-row" key={oid}>
          <div>{row.label}</div>
          <div className="gantt-track">
            {row.blocks.map((b, i) => {
              const style: CSSProperties = {
                left: `${pct(b.start_min)}%`,
                width: `${((b.end_min - b.start_min) / SPAN) * 100}%`,
              };
              if (b.chain_group) (style as Record<string, string>)["--chain-color"] = colorOf(b.chain_group) ?? "";
              return (
                <div key={i} className={`gantt-block ${b.phase}${b.chain_group ? " chain" : ""}`}
                  style={style}
                  title={b.chain_group ? `${b.code} ${b.phase}｜连烤组 ${b.chain_group}` : `${b.code} ${b.phase}`}>
                  {b.chain_group && <span className="chain-tag">{b.chain_group}</span>}
                  {b.code}/{b.phase === "ferment" ? "酵" : "烤"}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
    {groups.length > 0 && (
      <div className="chain-legend">
        <span className="chain-legend-title">同炉连烤组（同色同标记）</span>
        {groups.map(g => (
          <span key={g.name} className="chain-legend-item">
            <span className="chain-swatch" style={{ background: g.color }} />{g.name}
          </span>
        ))}
      </div>
    )}
  </>);
}
