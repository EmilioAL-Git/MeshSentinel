# Diario de operador — MeshSentinel

No es documentación técnica: es el diario de uso real del NOC. Registra
fricciones, descubrimientos y cómo evoluciona la UX con el uso (v0.7,
principio 8). Cada entrada incluye, cuando tiene sentido: **fecha,
contexto, qué intentaba hacer, fricción, impacto, idea de mejora y estado**
(pendiente / diseñado / implementado / mitigado / descartado). Los
descubrimientos que no son problemas ("siempre acabo usando el mapa antes
que la lista") valen tanto como los bugs de UX.

---

## 2026-07-10 · v0.7.3 — la consola viva

### Decisión: selección ≠ Focus (sin estados ambiguos)
- **Contexto**: la petición hablaba de "al seleccionar un nodo… atenuar el
  resto", pero el diseño (§7.4) separa consulta (Inspector) de Focus
  (contexto deliberado) exactamente para evitar ambigüedad.
- **Decisión**: seleccionar = sincronía visual (anillo, filas resaltadas en
  tabla/actividad); **Focus = ◎ explícito** (Inspector) con atenuado del
  mapa, secciones priorizadas, chip permanente con minutos y ✕. Las
  alertas nunca se atenúan ni se reordenan por debajo.
- **Estado**: implementado; si en el uso real se echa en falta que la
  selección atenúe, se revisa (es un flag).

### Descubrimiento: el ◎ solo se descubre desde el Inspector
- **Observación**: Focus se activa únicamente con el botón ◎ de la
  cabecera del Inspector. Quien no lo pulse nunca sabrá que existe.
- **Mejora**: acción "Enfocar" en ⌘K y en el futuro menú contextual;
  quizá un hint la primera vez que se abre el Inspector 3 veces seguidas
  con el mismo nodo.
- **Estado**: pendiente.

### Descubrimiento: los pulsos convierten el silencio en información
- **Observación**: con dos gateways simulados, ver pulsos ámbar/verde
  aparecer donde está pasando algo cambia la relación con el mapa — y su
  AUSENCIA también informa (malla muda). El límite anti-tormenta (8 por
  lote de 1 s, máx. 20 vivos) evita el árbol de Navidad con mallas grandes.
- **Estado**: implementado; vigilar en malla real si la tasa de malla
  (node.seen/telemetry) resulta ruidosa y conviene filtrar por categoría.

### Limitación: los clústeres no se atenúan con Focus
- **Contexto**: el atenuado de Focus se aplica por marcador (opacity);
  los iconos de clúster de Leaflet no cambian.
- **Impacto**: con zoom lejano, el efecto de Focus se percibe menos.
- **Estado**: aceptado por ahora (tocar los iconos de clúster es frágil
  con react-leaflet-cluster@2.1.0 fijado).

---

## 2026-07-10 · v0.7.2 — el Inspector

### El toast confirma el encolado, no el resultado
- **Contexto**: acciones rápidas del Inspector ("Pedir metadata", "Leer
  configuración") con toast de confirmación.
- **Qué intentaba**: pedir metadata y saber si el nodo respondió.
- **Fricción**: el toast dice "añadida a la cola"; para saber si TERMINÓ hay
  que mirar la sección Operaciones del Inspector o la consola de Actividad.
  El ciclo mental queda abierto.
- **Impacto**: leve, pero es la acción que más invita a repetir clics
  ("¿habrá llegado?").
- **Mejora**: toast de cierre cuando una operación lanzada EN ESTA SESIÓN
  llega a estado terminal (el evento admin.operation ya llega por WS con
  operation_id — es solo correlar client-side).
- **Estado**: **implementado en v0.7.3** (opTracker.ts: registro de sesión
  + correlación del WS → toast con el resultado real).

### Esc cierra el Inspector aunque estés escribiendo en un input
- **Contexto**: crear una etiqueta desde Organización y pulsar Esc para
  "cancelar el texto".
- **Fricción**: se cierra el cajón entero, no el input.
- **Mejora**: ignorar Esc global cuando el foco está en un input/textarea.
- **Estado**: **implementado en v0.7.3**.

### Descubrimiento: el anillo de selección + ⌖ cambian la sensación de producto
- **Observación**: ver el marcador resaltado al abrir el Inspector y el
  flyTo al pulsar ⌖ es lo que más "consola de operaciones" transmite de
  toda la fase — más que cualquier panel. La conexión visual
  inspector↔mapa es identidad. Siguiente paso natural: resaltar también la
  fila de la tabla y la entrada de actividad del nodo inspeccionado.
- **Estado**: **seguido en v0.7.3** (sincronía selección/Focus en tabla,
  actividad, trabajos y alertas).

### Descubrimiento: la vista Nodos queda para comparar y seleccionar
- **Observación**: con el Inspector global, ya no se entra en Nodos "a ver
  un nodo" — se entra a filtrar, comparar columnas y montar selecciones
  para lotes. Confirma el reparto del diseño (§13: tabla = masivo,
  inspector = individual). La tabla debería evolucionar hacia eso
  (columnas configurables, orden) y no hacia el detalle.
- **Estado**: anotado.

---

## 2026-07-10 · v0.7.1 — construyendo el Centro de Operaciones

### El popup del mapa se ha quedado viejo el mismo día
- **Contexto**: cablear el clic de marcador para abrir el cajón de detalle.
- **Qué intentaba**: mapa → nodo → detalle en 1 clic (presupuesto del diseño §8.4).
- **Fricción**: el popup de Leaflet sigue en medio: clic → popup → "Ver
  detalle" → cajón (2 clics y un popup que tapa el mapa). El diseño ya lo
  resolvía (hover = tooltip, clic = inspector directo) pero eso es v0.7.2.
- **Impacto**: la interacción más frecuente del Centro gasta un clic de más.
- **Mejora**: marcador → cajón directo; el popup se degrada a tooltip.
- **Estado**: **implementado en v0.7.2** (popup eliminado, tooltip de hover,
  clic = Inspector, marcador seleccionado con anillo).

### NodeDetail dentro del cajón funciona, pero se nota "prestado"
- **Contexto**: el cajón de 420 px reutiliza NodeDetail tal cual (decisión
  correcta: cero reescritura).
- **Fricción**: NodeDetail fue diseñado como columna de página — tablas
  anchas, secciones largas, todo abierto a la vez. En el cajón exige mucho
  scroll para llegar a favoritos remotos u organización.
- **Impacto**: consultar algo concreto de un nodo es más lento de lo que
  el cajón promete.
- **Mejora**: la reorganización prevista (cabecera fija de estado +
  secciones plegables) — es exactamente v0.7.2.
- **Estado**: **implementado en v0.7.2** (Inspector definitivo: cabecera
  vital fija, acciones rápidas, secciones plegables persistidas, global en
  toda la app; NodeDetail eliminado).

### Descubrimiento: el semáforo con motivos expandidos funciona
- **Contexto**: primer arranque del Centro con la red degradada del stack dev.
- **Observación**: leer "RED DEGRADADA › 1 pasarela(s) sin conexión" sin
  ningún clic responde la pregunta antes de formularla. Patrón a repetir:
  cualquier estado anómalo debería llevar su porqué al lado, no detrás de
  un clic.
- **Estado**: implementado; extender el patrón donde aparezcan estados.

### Descubrimiento: con el panel Trabajos abierto, la actividad desaparece
- **Contexto**: monitorizar un lote mientras llegaba telemetría.
- **Observación**: el riel muestra UN panel a la vez; en Trabajos, los
  eventos solo se perciben por el badge y el bloque de alertas. No es
  grave (la barra inferior cubre lo vital) pero en pantallas anchas se
  echa de menos ver Actividad ∥ Trabajos a la vez.
- **Mejora**: el anclaje de segundo panel en ultrawide ya está en el
  diseño (§2.3 y §6.1).
- **Estado**: diseñado, sin fase asignada — candidato si sobra tiempo en v0.7.2/3.

### El Dashboard clásico ya estorba
- **Contexto**: tras hacer el Centro la vista por defecto.
- **Observación**: todo lo que enseña el Dashboard clásico está ya en el
  Centro, mejor colocado. Mantener ambos confunde ("¿cuál es la verdad?").
  La red de seguridad tiene sentido unos días, no meses.
- **Estado**: retirada prevista en cuanto el usuario valide el Centro con
  hardware real.

### "Ver historial →" del panel Trabajos aterriza en un sitio partido en dos
- **Contexto**: el panel Trabajos enlaza al historial completo.
- **Fricción**: el historial real está partido entre las vistas
  Operaciones y Batches; el panel unificado hace más evidente que esa
  separación es artificial (un lote ES un conjunto de operaciones).
- **Impacto**: la auditoría de "qué pasó anoche" sigue exigiendo dos vistas.
- **Mejora**: la fusión en la vista Trabajos (§13) sube de prioridad tras
  probar el panel.
- **Estado**: diseñado, previsto para la fase de vistas especializadas.

---

## 2026-07-10 · v0.7.0 — fundaciones

### Operaciones y Batches obligan a saltar entre pestañas
- **Fricción**: seguir una misma acción (lote → sus operaciones) exige dos vistas.
- **Estado**: **mitigado** en v0.7.1 (panel Trabajos del Centro: en curso +
  cola + recientes en un sitio); la fusión completa con historial sigue
  pendiente (§13).

### `succeeded_unconfirmed` como texto de chip es jerga de contrato
- **Fricción**: el operador necesita conocer ADR 0019 para interpretar el
  literal; el tooltip ayuda pero el crudo asusta.
- **Mejora**: vocabulario de operador también en la vista general
  ("confirmada por lectura" / "aceptada sin verificar") conservando el
  estado técnico en el detalle.
- **Estado**: pendiente.

### El HUD muestra "…" hasta que cargan las queries (2-3 s en frío)
- **Impacto**: los primeros segundos del turno el shell no responde a "¿la
  red está bien?".
- **Mejora**: cachear el último resumen en localStorage y pintarlo
  atenuado ("dato de la última sesión") hasta que llegue el fresco.
- **Estado**: pendiente.

### La cola (⧗) cuenta sobre las últimas 200 operaciones
- **Fricción**: con una cola real >200 el número se quedaría corto. Hoy
  imposible en la práctica (rate limit 60/min).
- **Mejora**: endpoint de conteos agregados cuando exista la vista Trabajos.
- **Estado**: pendiente (requiere backend; fuera de v0.7).

### El aviso de reconexión WS no distingue "backend caído" de "solo WS caído"
- **Estado**: pendiente; la barra inferior sí los distingue vía /health —
  coordinar el texto del banner cuando ambos fallan.

### El reloj de la barra muestra HH:MM sin segundos
- **Fricción**: para correlar con logs los segundos ayudarían; se evitó un
  tick por segundo.
- **Estado**: pendiente de ver si algún flujo real los echa de menos.
