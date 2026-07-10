/**
 * Fuzzy matching client-side para la búsqueda global ⌘K (v0.7 §10).
 * Sin dependencias: subsecuencia con puntuación por adyacencia y comienzo
 * de palabra. Devuelve null si `query` no es subsecuencia de `text`.
 */
export function fuzzyScore(query: string, text: string): number | null {
  const q = query.toLowerCase();
  const s = text.toLowerCase();
  if (q.length === 0) return 0;
  let score = 0;
  let si = 0;
  let prevMatch = -2;
  for (let qi = 0; qi < q.length; qi++) {
    const idx = s.indexOf(q[qi], si);
    if (idx === -1) return null;
    // Bonus: carácter consecutivo al anterior, o comienzo de palabra
    if (idx === prevMatch + 1) score += 3;
    if (idx === 0 || s[idx - 1] === " " || s[idx - 1] === "-" || s[idx - 1] === "_" || s[idx - 1] === "!") {
      score += 2;
    }
    score += 1;
    prevMatch = idx;
    si = idx + 1;
  }
  // Penalización suave por longitud: prefiere coincidencias compactas
  return score - Math.min(s.length / 20, 3);
}
