import type { PositionOut, TelemetryOut } from "../../api/client";
import { haversineMeters } from "../map/geometry";

/**
 * Resumen de "últimas 24 h" de UN nodo: función pura sobre telemetría/
 * posiciones ya cargadas (mismo criterio que `groupStats.ts`/`highlights.ts`
 * — cero SQL nuevo, se calcula en cliente sobre lo que ya trae el Inspector).
 * `node_telemetry`/`node_positions` son append-only (ADR de dominio): "lo
 * último" y "series" se resuelven siempre en la capa de lectura, nunca se
 * persiste un agregado.
 */

export type TrafficLevel = "alto" | "moderado" | "bajo";

/** Umbral pedido por el usuario: air_util_tx medio > 30 % = mucho tráfico. */
export const TRAFFIC_LEVEL_LABEL: Record<TrafficLevel, string> = {
  alto: "Tráfico alto",
  moderado: "Tráfico moderado",
  bajo: "Tráfico bajo",
};

function classifyTraffic(avgAirUtilTx: number | null): TrafficLevel | null {
  if (avgAirUtilTx == null) return null;
  if (avgAirUtilTx > 30) return "alto";
  if (avgAirUtilTx > 10) return "moderado";
  return "bajo";
}

export interface NodeStats24h {
  windowHours: number;
  deviceSamples: number;
  envSamples: number;
  positionSamples: number;
  avgAirUtilTx: number | null;
  maxAirUtilTx: number | null;
  trafficLevel: TrafficLevel | null;
  avgChannelUtil: number | null;
  maxChannelUtil: number | null;
  minBattery: number | null;
  maxBattery: number | null;
  batteryDeltaPercent: number | null; // último - primero (con signo; negativo = descargando)
  minTemperatureC: number | null;
  maxTemperatureC: number | null;
  avgTemperatureC: number | null;
  minHumidity: number | null;
  maxHumidity: number | null;
  minPressureHpa: number | null;
  maxPressureHpa: number | null;
  distanceKm: number | null;
  maxSpeedKmh: number | null;
  reboots: number;
  currentUptimeSeconds: number | null;
}

function inWindow<T extends { received_at: string | null }>(rows: T[], cutoffMs: number): T[] {
  return rows.filter((r) => r.received_at != null && new Date(r.received_at).getTime() >= cutoffMs);
}

/** Ordena ascendente por received_at (los endpoints devuelven desc). */
function ascending<T extends { received_at: string | null }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => new Date(a.received_at ?? 0).getTime() - new Date(b.received_at ?? 0).getTime());
}

function stats(values: number[]): { min: number; max: number; avg: number } | null {
  if (values.length === 0) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const avg = values.reduce((a, b) => a + b, 0) / values.length;
  return { min, max, avg: Math.round(avg * 10) / 10 };
}

export function computeNodeStats24h(
  deviceTelemetry: TelemetryOut[],
  envTelemetry: TelemetryOut[],
  positions: PositionOut[],
  windowHours = 24,
): NodeStats24h {
  const cutoff = Date.now() - windowHours * 3_600_000;
  const device = ascending(inWindow(deviceTelemetry, cutoff));
  const env = ascending(inWindow(envTelemetry, cutoff));
  const pos = ascending(inWindow(positions, cutoff));

  const airTx = stats(device.map((d) => d.air_util_tx).filter((v): v is number => v != null));
  const channelUtil = stats(device.map((d) => d.channel_utilization).filter((v): v is number => v != null));
  const battery = device.map((d) => d.battery_level).filter((v): v is number => v != null && v <= 100);
  const batteryAgg = stats(battery);
  const batteryDeltaPercent = battery.length >= 2 ? battery[battery.length - 1] - battery[0] : null;

  const temperature = stats(env.map((e) => e.temperature_c).filter((v): v is number => v != null));
  const humidity = stats(env.map((e) => e.relative_humidity).filter((v): v is number => v != null));
  const pressure = stats(env.map((e) => e.barometric_pressure_hpa).filter((v): v is number => v != null));

  // Reinicios: uptime_seconds retrocede respecto a la muestra anterior.
  let reboots = 0;
  for (let i = 1; i < device.length; i++) {
    const prev = device[i - 1].uptime_seconds;
    const cur = device[i].uptime_seconds;
    if (prev != null && cur != null && cur < prev) reboots++;
  }
  const currentUptimeSeconds = device.length > 0 ? device[device.length - 1].uptime_seconds : null;

  // Distancia recorrida + velocidad máxima entre fijos GPS consecutivos —
  // aproximación curiosa, no un dato de precisión (ruido de GPS incluido).
  let distanceMeters = 0;
  let maxSpeedKmh = 0;
  let hasPositionDelta = false;
  for (let i = 1; i < pos.length; i++) {
    const a = pos[i - 1];
    const b = pos[i];
    const dMeters = haversineMeters([a.latitude, a.longitude], [b.latitude, b.longitude]);
    distanceMeters += dMeters;
    const dtHours =
      (new Date(b.received_at ?? 0).getTime() - new Date(a.received_at ?? 0).getTime()) / 3_600_000;
    if (dtHours > 0) {
      hasPositionDelta = true;
      const speedKmh = dMeters / 1000 / dtHours;
      if (speedKmh > maxSpeedKmh) maxSpeedKmh = speedKmh;
    }
  }

  return {
    windowHours,
    deviceSamples: device.length,
    envSamples: env.length,
    positionSamples: pos.length,
    avgAirUtilTx: airTx?.avg ?? null,
    maxAirUtilTx: airTx?.max ?? null,
    trafficLevel: classifyTraffic(airTx?.avg ?? null),
    avgChannelUtil: channelUtil?.avg ?? null,
    maxChannelUtil: channelUtil?.max ?? null,
    minBattery: batteryAgg?.min ?? null,
    maxBattery: batteryAgg?.max ?? null,
    batteryDeltaPercent,
    minTemperatureC: temperature?.min ?? null,
    maxTemperatureC: temperature?.max ?? null,
    avgTemperatureC: temperature?.avg ?? null,
    minHumidity: humidity?.min ?? null,
    maxHumidity: humidity?.max ?? null,
    minPressureHpa: pressure?.min ?? null,
    maxPressureHpa: pressure?.max ?? null,
    distanceKm: pos.length >= 2 ? Math.round((distanceMeters / 1000) * 100) / 100 : null,
    maxSpeedKmh: hasPositionDelta ? Math.round(maxSpeedKmh * 10) / 10 : null,
    reboots,
    currentUptimeSeconds,
  };
}
