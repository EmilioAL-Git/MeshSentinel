# Guía de aceptación — Mapa 3D de trazas

1. Inspector de un nodo → **⌁ Traceroute**. Al terminar con éxito se abre la ventana de
   resultado con un botón nuevo **◈ Ver en mapa 3D**.
2. Se abre la pestaña **Mapa 3D** (riel: ◈) con SOLO los nodos de esa traza: pilares
   (azul = origen, verde = destino, gris = saltos), arcos elevados coloreados por SNR
   (verde ≥ 0 dB … rojo < −7 dB) y un pulso blanco que recorre primero la ida y luego la vuelta.
   La lista de la izquierda resalta el salto en curso.
3. Controles: ▶/⏸/↻, barra de progreso, velocidad 0,5×–4×, «Seguir» (la cámara acompaña
   al pulso), «Relieve» (terreno 3D con exageración ×1,6).
4. El selector «Traza» lista las últimas 40 trazas con resultado (activas y oídas en la
   malla): sirve para revisar cualquiera sin lanzar otro traceroute. URL compartible:
   `/map3d?m3d.op=<id operación>` o `?m3d.trace=<id traza>`.
5. Nodos sin posición GPS no se dibujan y se avisan en el panel; tramos con un extremo sin
   posición se atenúan en la lista.
6. Sin internet: aviso amarillo, fondo plano y sin relieve; el dibujo sigue funcionando.

Fuentes (gratuitas, sin clave; configurables en `components/map3d/map3dConfig.ts`):
estilo CARTO Dark Matter (© OpenStreetMap, © CARTO; uso no comercial con atribución) y
relieve AWS Terrain Tiles (Terrarium). Autoalojar = cambiar esas dos URLs.
La altura de los arcos es ilustrativa, no la trayectoria de radio real.

## Herramientas (hub) e Historial de trazas
- El riel tiene una entrada **Herramientas** (⚒) con tarjetas: Historial de trazas, Mapa 3D y
  Administración remota (que ya no está suelta en el riel; sigue en ⌘K y en sus enlaces).
  Dentro de cada herramienta, migas «← Herramientas / …».
- **Historial de trazas**: tabla con filtros (nodo, periodo, pasarela, con/sin respuesta,
  activa/oída). Por fila: **◈ 3D** (abre esa traza en el mapa 3D, `?m3d.trace=<id>`),
  **↻** (repite el traceroute al destino; requiere permiso de operar) y clic en un nodo
  abre el Inspector.
- **⟲ Rescatar antiguos** (gestores/admin): importa UNA vez los traceroutes que solo
  existían en el Registro. Recupera la ida y su SNR; la vuelta no se guardaba. Es
  idempotente (repetirlo no duplica) y omite los ya registrados en vivo.
- Próximamente (tarjetas atenuadas): Comparador de trazas, Perfil de elevación.
