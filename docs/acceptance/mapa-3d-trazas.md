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

## Mapa base y relieve
- Selector sobre el mapa: **Oscuro** (CARTO + sombreado fuerte), **Satélite** (Sentinel-2 cloudless de
  EOX, ~10 m/px, se desenfoca por encima de z13) y **Relieve** (rampa de color por altitud).
  Los tres llevan el terreno 3D real (Mapterhorn). Se recuerda la elección.
- Exageración vertical 1× (altura real) / 1,6× / 2,5× / 4×. En zonas llanas (La Mancha) casi no hay
  relieve que ver; en sierras (Guadarrama, Sierra Nevada) se nota mucho.
- Licencias: EOX Sentinel-2 cloudless es CC BY-NC 4.0 (uso no comercial, con atribución).
- Las bases se superponen: la imagen/relieve va de fondo y encima quedan agua, ríos, límites, carreteras,
  edificios y nombres (aclarados para que se vean sobre la imagen). «+ Relieve color» superpone la rampa de
  altitud, semitransparente, al fondo elegido; «Referencias» oculta carreteras/límites y sus nombres.
- Elevación: Mapterhorn (zoom hasta 17, teselas 512 px; AWS Terrain Tiles queda como reserva en
  `map3dConfig.ts`). Exageración 1×/2×/3×/5× (2× por defecto). El modo «Relieve» usa bandas de color cada
  100 m (como curvas de nivel) para que se distinga la altura incluso en mesetas casi llanas.
