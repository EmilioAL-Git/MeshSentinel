import * as echarts from "echarts";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { t } from "../../tokens";

/**
 * Mini-gráfica histórica del Inspector (Fase C.2, v0.9): wrapper mínimo
 * sobre ECharts (sin `echarts-for-react`, para no añadir una segunda
 * dependencia solo para el ciclo de vida de un `<div>`). Primera vez que
 * se usa ECharts en el frontend — designada en CLAUDE.md como librería de
 * gráficas del proyecto.
 *
 * El montaje usa un ref CALLBACK (no `useEffect` con `useRef`, ver commit
 * de esta fase): con React 18 StrictMode, un `useEffect(() => {init...;
 * return () => dispose()}, [])` deja el gráfico vacío en desarrollo — el
 * doble montaje simulado dispara el `dispose()` del primer paso después de
 * que el segundo `useEffect` (el `setOption`) ya haya corrido, y el efecto
 * de `setOption` no se re-ejecuta en el remontaje porque sus dependencias
 * no cambiaron. Un ref callback solo se invoca en el montaje/desmontaje
 * REAL del nodo DOM, no en la simulación de StrictMode, así que el ciclo
 * de vida de la instancia de ECharts queda atado 1:1 al `<div>`.
 */

export interface HistoryPoint {
  time: string; // ISO
  value: number;
}

export function HistoryChart({
  points,
  unit,
  color = t.accent,
  height = 90,
}: {
  points: HistoryPoint[];
  unit: string;
  color?: string;
  height?: number;
}) {
  const chart = useRef<echarts.ECharts | null>(null);
  const observer = useRef<ResizeObserver | null>(null);

  const containerRef = useCallback((node: HTMLDivElement | null) => {
    if (node) {
      chart.current = echarts.init(node, undefined, { renderer: "canvas" });
      observer.current = new ResizeObserver(() => chart.current?.resize());
      observer.current.observe(node);
    } else {
      observer.current?.disconnect();
      observer.current = null;
      chart.current?.dispose();
      chart.current = null;
    }
  }, []);

  const sorted = useMemo(() => [...points].sort((a, b) => a.time.localeCompare(b.time)), [points]);

  useEffect(() => {
    if (!chart.current) return;
    chart.current.setOption({
      grid: { left: 4, right: 4, top: 8, bottom: 4, containLabel: false },
      xAxis: { type: "time", show: false },
      yAxis: { type: "value", show: false, scale: true },
      tooltip: {
        trigger: "axis",
        valueFormatter: (v: unknown) => `${v} ${unit}`,
        textStyle: { fontSize: 11 },
      },
      series: [
        {
          type: "line",
          data: sorted.map((p) => [p.time, p.value]),
          showSymbol: false,
          smooth: true,
          lineStyle: { color, width: 1.5 },
          areaStyle: { color, opacity: 0.12 },
        },
      ],
    });
  }, [sorted, unit, color]);

  if (points.length === 0) {
    return (
      <div style={{ color: t.textFaint, fontSize: 11.5, padding: "0.3rem 0" }}>Sin datos históricos aún.</div>
    );
  }
  return <div ref={containerRef} style={{ width: "100%", height }} />;
}
