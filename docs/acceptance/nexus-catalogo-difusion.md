# Guía de aceptación — JenTastic-Nexus: catálogo explorable, difusión con respuestas por nodo y ocultación de admin nativa superada

Cierra el encargo del usuario: "que en su pestaña tenga todos los comandos
disponibles agrupados", "poder lanzarlos en grupo a las flotas" y que el
modo Nexus se convierta en el método principal para lo que ya cubre
(ADR 0027 §11/§12).

## Qué se puede probar

1. **Explorador de catálogo** (Ajustes → JenTastic-Nexus → Operaciones, y
   en la pestaña JenTastic-Nexus del Inspector de cualquier nodo marcado):
   botón "Explorar catálogo (186)" despliega los comandos agrupados por
   categoría (Sistema, Estadísticas, Escaneo, Base de nodos, Cortafuegos,
   Sigilo, Inyección, Configuración, Sensores, Almacenamiento, Alertas,
   Ping periódico, Seguridad, Crítico). El filtro busca por nombre o
   alias. Cada fila muestra si consulta o muta, si es destructivo (⚠) y
   si deja el nodo ocupado (segundos). Elegir uno solo rellena el campo
   COMANDO — no envía nada por sí mismo, sigue habiendo que previsualizar
   y encolar.

2. **Difusión con respuesta por nodo** (Ajustes → Operaciones, tipo de
   destino "Difusión"): mandar por ejemplo `VERSION` en difusión — la fila
   del historial, en vez de un texto de respuesta único, muestra "ver
   respuestas por nodo →". Al hacer clic se despliega la lista de nodos
   que han respondido (id + texto + datos estructurados si el parser los
   reconoce), actualizándose cada 3 s mientras esté abierta. La operación
   se queda "Enviado" hasta que se cumple la ventana (30 s + ocupación);
   al cerrarse pasa a "Confirmado" si respondió al menos un nodo, o "Sin
   respuesta" si ninguno. El mismo comportamiento aplica al tipo de
   destino "Grupo Nexus" (grupo de radio del propio firmware, distinto de
   los grupos de MeshSentinel).

3. **Destino dirigido sin cambios** (nodo/MAC/local): sigue funcionando
   exactamente igual que antes — una sola respuesta, terminal en cuanto
   llega, sin la lista de "por nodo".

4. **Ocultación de administración nativa superada** (Trabajos → Nueva
   operación, o desde el Inspector → pestaña Operaciones): con el modo
   Nexus activado y un nodo marcado como Nexus seleccionado, el selector
   de tipo de operación YA NO ofrece "Cambiar nombre corto y/o largo del
   nodo" (`owner.set`) ni "Fijar posición del nodo" (`position.set_fixed`)
   — aparece un aviso explicando que esas acciones se hacen ahora desde la
   pestaña JenTastic-Nexus de ese nodo. El resto de operaciones nativas
   (config.get/set, module_config.get/set, metadata.get, nodeinfo.get,
   favoritos/ignorados remotos, ficha de contacto) siguen disponibles tal
   cual — Nexus no las cubre al completo.
   - Con un nodo SIN marcar, o con el modo global apagado, el selector
     muestra las operaciones nativas completas, sin nada oculto.

## Fuera de alcance de esta fase (con motivo)

- No se ha creado un concepto de "lote Nexus" equivalente al Batch Engine
  (M2, con pantalla de progreso/pausa/cancelación) — decisión explícita
  del usuario: la propia difusión de Nexus ya llega a toda la flota del
  canal de una sola vez, y el seguimiento por nodo (punto 2 de esta guía)
  cubre lo que se pedía sin replicar esa maquinaria para un pipeline que
  no tiene ACK del gateway.
- No hay forma de dirigir un comando Nexus a un grupo/flota concreto de
  MeshSentinel (solo al grupo de radio nativo del firmware o a difusión
  total) — no se pidió explícitamente esa segmentación.
