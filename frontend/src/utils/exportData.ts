/**
 * Exportación a CSV / GeoJSON de lo que el operador ya tiene en pantalla.
 * Todo en cliente: se exporta exactamente la lista filtrada visible, sin
 * endpoints nuevos. CSV con BOM UTF-8 para que Excel respete acentos.
 */
import type { NodeSummaryOut } from "../api/client";
import type { ActivityEntry } from "../activity";

type Cell = string | number | boolean | null | undefined;

function csvCell(v: Cell): string {
  if (v == null) return "";
  const s = String(v);
  // Neutraliza inyección de fórmulas en hojas de cálculo (=, +, -, @ al inicio)
  const safe = /^[=+\-@]/.test(s) && Number.isNaN(Number(s)) ? `'${s}` : s;
  return /[",\n\r;]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function toCsv(header: string[], rows: Cell[][]): string {
  return [header, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n");
}

export function downloadText(filename: string, mime: string, content: string, bom = false): void {
  const blob = new Blob([bom ? "﻿" : "", content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Sello para nombres de fichero: 20261003-1530 (hora local). */
export function stamp(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`;
}

export function fleetCsv(summaries: NodeSummaryOut[]): string {
  const header = [
    "node_id", "short_name", "long_name", "hw_model", "role", "firmware", "online", "last_seen_at",
    "first_seen_at", "battery_level", "voltage", "channel_utilization", "air_util_tx", "snr", "rssi",
    "hops_away", "gateway_id", "gateways_heard", "latitude", "longitude", "altitude_m", "tags",
    "favorite", "ignored", "nexus",
  ];
  const rows = summaries.map((s) => {
    const n = s.node;
    const tel = s.last_device_telemetry;
    const pos = s.last_position;
    return [
      n.node_id, n.short_name, n.long_name, n.hw_model, n.role, n.firmware_version, n.online,
      n.last_seen_at, n.first_seen_at, tel?.battery_level, tel?.voltage, tel?.channel_utilization,
      tel?.air_util_tx, n.snr, n.rssi, n.hops_away, n.gateway_id,
      s.gateway_links.filter((l) => l.active).length, pos?.latitude, pos?.longitude, pos?.altitude_m,
      s.tags.map((t) => t.name).join("|"), n.is_favorite, n.is_ignored, n.is_nexus,
    ] as Cell[];
  });
  return toCsv(header, rows);
}

/** FeatureCollection de puntos; los nodos sin posición se omiten. */
export function fleetGeoJson(summaries: NodeSummaryOut[]): string {
  const features = summaries
    .filter((s) => s.last_position != null)
    .map((s) => {
      const p = s.last_position!;
      return {
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: p.altitude_m != null ? [p.longitude, p.latitude, p.altitude_m] : [p.longitude, p.latitude],
        },
        properties: {
          node_id: s.node.node_id,
          short_name: s.node.short_name,
          long_name: s.node.long_name,
          hw_model: s.node.hw_model,
          online: s.node.online,
          last_seen_at: s.node.last_seen_at,
          battery_level: s.last_device_telemetry?.battery_level ?? null,
          tags: s.tags.map((t) => t.name),
        },
      };
    });
  return JSON.stringify({ type: "FeatureCollection", features }, null, 2);
}

export function activityCsv(entries: ActivityEntry[]): string {
  const header = [
    "hora", "timestamp_ms", "categoria", "severidad", "tipo_paquete", "nodo_id", "nodo", "pasarela",
    "texto", "detalles", "rssi", "snr",
  ];
  const rows = entries.map((e) => [
    e.time, e.receivedAtMs, e.category, e.severity, e.packetType, e.nodeId, e.nodeLabel, e.gatewayId,
    e.text, (e.details ?? []).map(([k, v]) => `${k}: ${v}`).join(" · "), e.rssi, e.snr,
  ] as Cell[]);
  return toCsv(header, rows);
}
