import { createPortal } from "react-dom";
import {
  useCallback,
  useEffect,
  useRef,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { usePersistedState } from "../../hooks/usePersistedState";
import { t } from "../../tokens";

/**
 * Ventana de trabajo flotante genérica (v0.9, "Inspector como ventana"):
 * arrastrable, redimensionable, con posición/tamaño persistidos — la base
 * de una consola profesional (Wireshark/VS Code/SCADA) en vez de cajones
 * fijos. Sin lógica de "Inspector" dentro a propósito: una fase futura de
 * multi-ventana solo tiene que instanciar esto N veces con `id`s distintos,
 * no reescribirlo. Sin dependencia nueva — Pointer Events nativos (no hay
 * precedente de drag/resize en el repo, y el caso de uso no lo justifica).
 *
 * z-index fijo (950, entre StatusBar/BatchWizard/GroupSelector [900–970] y
 * CommandPalette/Toast [990–1000]): con una sola ventana posible hoy, un
 * contador dinámico de "traer al frente" es complejidad prematura — se
 * añade cuando exista multi-ventana real sin romper esta API.
 */

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

const HANDLE_SIZE = 8;
const HEADER_VISIBLE_MIN = 40; // parte de la cabecera siempre alcanzable

function clampRect(r: Rect, minWidth: number, minHeight: number): Rect {
  const maxX = Math.max(0, window.innerWidth - HEADER_VISIBLE_MIN);
  const maxY = Math.max(0, window.innerHeight - HEADER_VISIBLE_MIN);
  return {
    x: Math.min(Math.max(r.x, -(r.w - HEADER_VISIBLE_MIN)), maxX),
    y: Math.min(Math.max(r.y, 0), maxY),
    w: Math.max(minWidth, Math.min(r.w, window.innerWidth - 8)),
    h: Math.max(minHeight, Math.min(r.h, window.innerHeight - 8)),
  };
}

export function FloatingWindow({
  id,
  title,
  icon,
  defaultPos,
  defaultSize,
  minWidth = 360,
  minHeight = 320,
  onClose,
  headerActions,
  children,
  zIndex = 950,
}: {
  id: string;
  title: ReactNode;
  icon?: string;
  defaultPos: { x: number; y: number };
  defaultSize: { w: number; h: number };
  minWidth?: number;
  minHeight?: number;
  onClose: () => void;
  headerActions?: ReactNode;
  children: ReactNode;
  zIndex?: number;
}) {
  const [rect, setRect] = usePersistedState<Rect>(`window.${id}.rect`, {
    x: defaultPos.x,
    y: defaultPos.y,
    w: defaultSize.w,
    h: defaultSize.h,
  });
  const rectRef = useRef(rect);
  rectRef.current = rect;

  // Re-clamp si la ventana quedó fuera del viewport (p. ej. tras cambiar de
  // pantalla): solo al montar, nunca durante el uso normal.
  useEffect(() => {
    const clamped = clampRect(rectRef.current, minWidth, minHeight);
    if (clamped.x !== rectRef.current.x || clamped.y !== rectRef.current.y || clamped.w !== rectRef.current.w || clamped.h !== rectRef.current.h) {
      setRect(clamped);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dragState = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);
  const resizeState = useRef<{ startX: number; startY: number; origW: number; origH: number; edge: "e" | "s" | "se" } | null>(null);

  const onHeaderPointerDown = useCallback((e: ReactPointerEvent) => {
    if ((e.target as HTMLElement).closest("button")) return;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    dragState.current = { startX: e.clientX, startY: e.clientY, origX: rectRef.current.x, origY: rectRef.current.y };
  }, []);

  const onHeaderPointerMove = useCallback(
    (e: ReactPointerEvent) => {
      if (!dragState.current) return;
      const { startX, startY, origX, origY } = dragState.current;
      const next = clampRect(
        { ...rectRef.current, x: origX + (e.clientX - startX), y: origY + (e.clientY - startY) },
        minWidth,
        minHeight,
      );
      setRect(next);
    },
    [minWidth, minHeight, setRect],
  );

  const onHeaderPointerUp = useCallback((e: ReactPointerEvent) => {
    dragState.current = null;
    (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
  }, []);

  const startResize = useCallback(
    (edge: "e" | "s" | "se") => (e: ReactPointerEvent) => {
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      resizeState.current = { startX: e.clientX, startY: e.clientY, origW: rectRef.current.w, origH: rectRef.current.h, edge };
      e.stopPropagation();
    },
    [],
  );

  const onResizePointerMove = useCallback(
    (e: ReactPointerEvent) => {
      if (!resizeState.current) return;
      const { startX, startY, origW, origH, edge } = resizeState.current;
      const dw = edge === "s" ? 0 : e.clientX - startX;
      const dh = edge === "e" ? 0 : e.clientY - startY;
      const next = clampRect({ ...rectRef.current, w: origW + dw, h: origH + dh }, minWidth, minHeight);
      setRect(next);
      e.stopPropagation();
    },
    [minWidth, minHeight, setRect],
  );

  const onResizePointerUp = useCallback((e: ReactPointerEvent) => {
    resizeState.current = null;
    (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
    e.stopPropagation();
  }, []);

  // Re-clamp en resize del navegador (no durante drag/resize propios).
  useEffect(() => {
    const onWinResize = () => setRect(clampRect(rectRef.current, minWidth, minHeight));
    window.addEventListener("resize", onWinResize);
    return () => window.removeEventListener("resize", onWinResize);
  }, [minWidth, minHeight, setRect]);

  const windowStyle: CSSProperties = {
    position: "fixed",
    left: rect.x,
    top: rect.y,
    width: rect.w,
    height: rect.h,
    zIndex,
    boxShadow: "0 12px 40px rgba(0, 0, 0, 0.55)",
    borderRadius: 6,
    overflow: "hidden",
  };

  const handleStyle = (edge: "e" | "s" | "se"): CSSProperties => ({
    position: "absolute",
    right: 0,
    bottom: 0,
    width: edge === "s" ? "100%" : HANDLE_SIZE,
    height: edge === "e" ? "100%" : HANDLE_SIZE,
    cursor: edge === "e" ? "ew-resize" : edge === "s" ? "ns-resize" : "nwse-resize",
    touchAction: "none",
  });

  // Velo de fondo (solo visual, NUNCA modal): la ventana sigue sin bloquear
  // el mapa/resto de la UI — `pointer-events: none` deja pasar todos los
  // clics/drags al contenido de detrás. Solo sube el contraste del panel.
  const backdropStyle: CSSProperties = {
    position: "fixed",
    inset: 0,
    zIndex: zIndex - 1,
    background: "rgba(0, 0, 0, 0.4)",
    pointerEvents: "none",
  };

  return createPortal(
    <>
      <div style={backdropStyle} />
      <div className="panel" style={windowStyle}>
      <div
        className="panel-head"
        style={{ cursor: "grab", touchAction: "none" }}
        onPointerDown={onHeaderPointerDown}
        onPointerMove={onHeaderPointerMove}
        onPointerUp={onHeaderPointerUp}
      >
        {icon && <span style={{ fontSize: 12 }}>{icon}</span>}
        <span className="panel-title" style={{ textTransform: "none", letterSpacing: 0, fontSize: 12, color: t.text }}>
          {title}
        </span>
        <span style={{ marginLeft: "auto", display: "inline-flex", gap: 4, alignItems: "center" }}>
          {headerActions}
          <button
            style={{ background: "transparent", border: "none", color: t.textFaint, cursor: "pointer", fontSize: 14, padding: "0.1rem 0.3rem" }}
            title="Cerrar (Esc)"
            onClick={onClose}
          >
            ✕
          </button>
        </span>
      </div>
      <div className="panel-body flush" style={{ position: "relative", display: "flex", flexDirection: "column" }}>
        {children}
      </div>
      <div style={handleStyle("e")} onPointerDown={startResize("e")} onPointerMove={onResizePointerMove} onPointerUp={onResizePointerUp} />
      <div style={handleStyle("s")} onPointerDown={startResize("s")} onPointerMove={onResizePointerMove} onPointerUp={onResizePointerUp} />
      <div
        style={{ position: "absolute", right: 0, bottom: 0, width: 14, height: 14, cursor: "nwse-resize", touchAction: "none" }}
        onPointerDown={startResize("se")}
        onPointerMove={onResizePointerMove}
        onPointerUp={onResizePointerUp}
      />
      </div>
    </>,
    document.body,
  );
}
