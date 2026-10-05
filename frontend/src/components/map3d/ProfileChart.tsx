import { useState } from "react";
import type { LosResult } from "./elevation";
import { t } from "../../tokens";

const W = 800;
const H = 190;
const PAD = { l: 44, r: 10, t: 10, b: 22 };

const fmtKm = (m: number) => (m >= 1000 ? `${(m / 1000).toFixed(m >= 10_000 ? 0 : 1)} km` : `${Math.round(m)} m`);

/**
 * Perfil topográfico: terreno (área), línea de visión (recta entre antenas) y banda del
 * 60 % de la 1.ª zona de Fresnel. Al pasar el ratón se informa de la posición
 * (`onProbe` permite marcarla en el mapa).
 */
export function ProfileChart({
  los,
  nameA,
  nameB,
  onProbe,
}: {
  los: LosResult;
  nameA: string;
  nameB: string;
  onProbe: (d: number | null) => void;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const pts = los.points;
  const D = los.distanceM;
  const lo = Math.min(...pts.map((p) => p.terrain), los.heightA, los.heightB);
  const hi = Math.max(...pts.map((p) => p.terrain), los.heightA, los.heightB);
  const span = Math.max(20, hi - lo);
  const yMin = lo - span * 0.08;
  const yMax = hi + span * 0.12;
  const x = (d: number) => PAD.l + (d / D) * (W - PAD.l - PAD.r);
  const y = (e: number) => PAD.t + (1 - (e - yMin) / (yMax - yMin)) * (H - PAD.t - PAD.b);

  const ground = `M${x(pts[0].d)},${y(yMin)} ` + pts.map((p) => `L${x(p.d)},${y(p.terrain)}`).join(" ") + ` L${x(pts[pts.length - 1].d)},${y(yMin)} Z`;
  const losLine = `M${x(0)},${y(los.heightA)} L${x(D)},${y(los.heightB)}`;
  const fresnel =
    pts.map((p, i) => `${i ? "L" : "M"}${x(p.d)},${y(p.los + 0.6 * p.fresnel)}`).join(" ") +
    " " +
    [...pts].reverse().map((p) => `L${x(p.d)},${y(p.los - 0.6 * p.fresnel)}`).join(" ") +
    " Z";
  const color = los.clear ? (los.fresnelClear ? t.ok : t.warn) : t.crit;

  const nearest = (d: number) => pts.reduce((m, p) => (Math.abs(p.d - d) < Math.abs(m.d - d) ? p : m), pts[0]);
  const hp = hover != null ? nearest(hover) : null;
  const ticks = [yMin + (yMax - yMin) * 0.1, (yMin + yMax) / 2, yMax - (yMax - yMin) * 0.1];

  return (
    <div style={{ position: "relative" }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", height: 190, display: "block" }}
        preserveAspectRatio="none"
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const px = ((e.clientX - r.left) / r.width) * W;
          const d = Math.min(D, Math.max(0, ((px - PAD.l) / (W - PAD.l - PAD.r)) * D));
          setHover(d);
          onProbe(nearest(d).d);
        }}
        onMouseLeave={() => {
          setHover(null);
          onProbe(null);
        }}
      >
        {ticks.map((e) => (
          <line key={e} x1={PAD.l} x2={W - PAD.r} y1={y(e)} y2={y(e)} stroke={t.border} strokeWidth={1} strokeDasharray="3 4" />
        ))}
        <path d={fresnel} fill={color} opacity={0.14} />
        <path d={ground} fill={t.textFaint} opacity={0.55} stroke={t.textDim} strokeWidth={1.2} />
        <path d={losLine} stroke={color} strokeWidth={2} fill="none" />
        {!los.clear && (
          <circle cx={x(los.worst.d)} cy={y(los.worst.terrain)} r={5} fill={t.crit} stroke="#fff" strokeWidth={1} />
        )}
        {[0, D].map((d, i) => (
          <line key={i} x1={x(d)} x2={x(d)} y1={y(i ? los.heightB : los.heightA)} y2={y(yMin)} stroke={t.accent} strokeWidth={2} />
        ))}
        {hp && <line x1={x(hp.d)} x2={x(hp.d)} y1={PAD.t} y2={H - PAD.b} stroke={t.text} strokeWidth={1} opacity={0.6} />}
      </svg>
      {ticks.map((e) => (
        <span key={e} className="mono" style={{ position: "absolute", left: 2, top: `${(y(e) / H) * 100}%`, transform: "translateY(-50%)", fontSize: 10, color: t.textDim }}>
          {Math.round(e)} m
        </span>
      ))}
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10.5, color: t.textDim, padding: `0 ${PAD.r}px 0 ${(PAD.l / W) * 100}%` }}>
        <span>{nameA}</span>
        <span className="mono">{hp ? `${fmtKm(hp.d)} · terreno ${Math.round(hp.terrain)} m · holgura ${Math.round(hp.clearance)} m` : fmtKm(D)}</span>
        <span>{nameB}</span>
      </div>
    </div>
  );
}
