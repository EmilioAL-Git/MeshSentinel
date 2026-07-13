# Guía de operador

Cómo usar MeshSentinel día a día. Para vocabulario ver `docs/glossary.md`;
para instalación ver `docs/deployment.md`.

## Primer vistazo: el Centro

Al abrir MeshSentinel llegas al **Centro** — no hay una pantalla de login ni
un dashboard aparte, es la vista por defecto y combina lo que en otras
herramientas serían pantallas separadas:

- **Panel de situación** (izquierda): un semáforo con el estado de salud de
  la malla y sus motivos, la lista de alertas activas con botón de
  reconocimiento (ACK) sin salir de la vista, y el estado de cada pasarela.
- **Mapa en vivo** (centro): siempre montado, con pulsos breves cuando llega
  actividad de un nodo y un halo permanente en los nodos con alerta crítica.
  Las capas (icono de capas) permiten activar/desactivar Gateways,
  Infraestructura, Usuarios, Fijos, Favoritos, y recolorear por Estado,
  Calidad de señal o Redundancia; la capa Enlaces dibuja las líneas
  nodo↔pasarela que el sistema ha observado realmente.
- **Consola lateral** (derecha, estilo editor de código): Actividad,
  Trabajos y Alertas en pestañas siempre montadas — cambiar de pestaña no
  pierde el scroll ni el estado de las otras.

Un HUD en la cabecera resume en dos líneas qué está pasando ahora mismo
(interpretado, no un simple contador).

## Abrir un nodo: el Inspector

Haz clic en cualquier nodo — desde el mapa, desde Flota, desde una entrada
del Registro — y se abre el **Inspector**, un cajón superpuesto que nunca te
saca de donde estabas. Incluye:

- Cabecera vital (nombre, batería, señal, última vez visto).
- Acciones rápidas de lectura a un clic (con confirmación por toast).
- Secciones plegables: configuración, favoritos/ignorados remotos,
  observaciones por pasarela (si el nodo lo ven varias), histórico con
  gráficas de telemetría y posición.
- Botón ◎ para activar **Focus** sobre ese nodo.
- Botón ⌖ para centrar el mapa en él, aunque estés en otra vista.

`Esc` cierra el Inspector (salvo que el foco esté en un campo de texto, para
no perder lo que estabas escribiendo).

## Focus

Focus fija un nodo como contexto de trabajo: el mapa atenúa todo lo demás
(excepto nodos con alerta activa), la Actividad prioriza sus eventos en una
sección fija, y Trabajos resalta sus operaciones. Solo se activa desde ◎ en
el Inspector — seleccionar un nodo en una tabla o el mapa no activa Focus por
sí solo, es una decisión deliberada para no mezclar "estoy mirando esto" con
"estoy investigando esto".

## Grupos y grupo activo

Los nodos se pueden agrupar en "sitios" (manual o por criterio). Fijar un
**grupo activo** acota el resto de la interfaz — Centro, Flota, Registro —
a esos nodos únicamente; el botón "Toda la red" en la cabecera vuelve a la
vista sin acotar en cualquier momento.

## Flota

Vista de listado para trabajar con muchos nodos a la vez: filtros
segmentados (online/offline, batería baja, etiqueta, grupo, favorito),
medidor de batería y barras de señal en vez de números sueltos. Marca
varios nodos con las casillas para que aparezca la barra de armado de lotes.

## Lanzar una operación o un lote (Trabajos)

1. Para un solo nodo: desde el Inspector, botón de acción rápida, o
   "Nueva operación" en Trabajos.
2. Para varios nodos: selecciona en Flota y arma un lote — verás una
   **previsualización sin efectos** (dry-run: nodos offline, sin ruta, ETA
   estimada) antes de que se envíe nada.
3. Las operaciones de escritura sensibles (p. ej. `owner.set`) piden
   confirmación explícita tecleando el identificador del nodo.
4. Trabajos organiza todo por pregunta: **En ejecución** (con progreso y
   reparto entre pasarelas si aplica), **En cola**, **Requieren
   intervención** (fallidas con opción de reintento), **Historial**.

## Alertas

Vista de triaje: KPIs arriba, bandeja de alertas activas con la severidad
marcada por color, ACK en línea. Las reglas (batería baja, nodo
desconectado, SNR degradado, pasarela caída) se gestionan también desde
aquí, incluyendo activarlas/desactivarlas y probar canales de notificación.

## Perfiles y Config

**Config** edita la configuración de un nodo sección a sección, generada
directamente desde los protobufs oficiales del firmware (nada de listas de
parámetros mantenidas a mano). **Perfiles** guarda plantillas de esa
configuración, las versiona, y permite comparar/sincronizar contra nodos
reales — la sincronización es, por debajo, un lote más, con su propio
dry-run y monitor en Trabajos.

## Registro

Diario cronológico de la malla: cada paquete que llega genera su propia
entrada, con cabecera en español ("Telemetría del dispositivo", "Posición
actualizada", "Información del nodo"...) y el detalle técnico plegado bajo
"Ver paquete". No es un log técnico — está pensado para leerse tal cual.

## Enlaces (gestión de pasarelas)

Alta de una pasarela nueva: **Buscar dispositivos → Seleccionar → Probar
conexión → Guardar**. Cada tarjeta muestra transporte, estado (🟢/🟡/🔴),
nodo local asociado e historial de conexión; se puede editar, reconectar,
desconectar, deshabilitar o eliminar (borrado lógico, no destructivo) sin
tocar variables de entorno ni reiniciar el proceso.

## Atajos

- `⌘K` (o `Ctrl+K`) abre la paleta de comandos: busca nodos, vistas y
  acciones sin tocar el ratón.
- Clic en un nodo, en cualquier vista, siempre abre el Inspector — nunca
  navega a otra pantalla.
