# M4.1 — Favoritos e ignorados remotos

> **Histórico**: "abre el detalle de un nodo" se refiere a la página
> NodeDetail, **eliminada** en v0.7.2 y sustituida por el **Inspector**
> global (mismo contenido, cajón en vez de página); "pestaña Batches/
> Operaciones" corresponde a vistas ya fusionadas en **Trabajos** (ver
> `docs/glossary.md`). La lógica de favoritos/ignorados remotos no cambió.

Valida con el simulador primero y después con hardware real. Necesitas al
menos dos nodos conocidos por el NOC (target y sujeto).

## Conceptos clave a verificar

- **"Confirmado" ≠ "verificado"**: el firmware no expone ninguna forma de leer
  la lista de favoritos/ignorados de vuelta. "Confirmado" solo significa que
  el nodo destino aceptó el AdminMessage (ACK). El badge de estado debe
  mostrar exactamente `Pendiente / Enviado / Confirmado / Error` — nunca
  "succeeded_unconfirmed" ni "verificado" en esta sección concreta (si
  aparece en la pestaña Operaciones/Batches general, es esperado: ahí sigue
  el vocabulario existente de M1.3).
- El ★/ojo de la cabecera del detalle de nodo (favorito/ignorado **local**,
  M1.2) es un concepto totalmente distinto y no debe cambiar al operar la
  sección "Favoritos / ignorados remotos".
- **`contact.add` (SharedContact/add_contact) ≠ NodeInfo**: son dos mecanismos
  distintos del protocolo (ADR 0019 §4). Si en algún punto del código, los
  logs o la UI aparece la operación llamada "NodeInfo" en vez de
  `contact.add`, es una regresión de nomenclatura a corregir.

## A. Marcar y quitar favorito/ignorado

1. Abre el detalle de un nodo (target). En "Favoritos / ignorados remotos",
   elige otro nodo en el selector "— nodo sujeto —" y pulsa **Marcar** en
   "Favorito remoto".
2. Debe aparecer un lote nuevo en la pestaña **Batches** (1 nodo, 1
   operación `favorite.set`) y una entrada en **Actividad**. El badge pasa
   Pendiente → Enviado → Confirmado en unos segundos (simulador) o al cabo
   de un ciclo de administración con hardware.
3. Pulsa **Quitar**: nuevo lote con `favorite.remove`; el badge refleja el
   último estado conocido (ahora "quitar" en vez de "marcar" — compruébalo
   por el tipo de operación en Batches/Actividad, el badge no distingue
   set/remove visualmente más que por el histórico).
4. Repite para "Ignorado remoto".
5. Con el simulador: fuerza varias veces (el simulador pierde ~10% de
   paquetes) hasta ver algún "Error" — confirma que pasa a `failed` y que un
   reintento manual desde Operaciones lo reencola.

## B. Ficha de contacto previa

1. Marca la casilla "Enviar antes una ficha de contacto del nodo sujeto" y
   pulsa **Marcar** en favorito.
2. El lote creado debe tener **2 operaciones** (orden: `contact.add` primero,
   luego `favorite.set`), ambas auditadas por separado en Actividad/Batches.
3. Con hardware: confirma que el nodo destino no rechaza el favorito aunque
   antes no conociera al sujeto (si tienes forma de comprobar su NodeDB por
   la app oficial de Meshtastic).
4. La casilla debe quedar desmarcada por defecto cada vez que abres el
   detalle de un nodo distinto (nunca activada automáticamente).

## C. Casos límite

1. Seleccionar como sujeto el propio nodo abierto no debe ser posible desde
   el selector (se excluye de la lista); si se fuerza por API, debe devolver
   422.
2. Un nodo destino sin `gateway_id` conocido (nunca visto por ninguna
   pasarela) debe devolver 409 al intentar encolar.
3. Reinicia el backend a mitad de un lote en curso: el estado debe
   sobrevivir (vive en BD, como el resto del pipeline) y el badge seguir
   reflejando la última operación al recargar.

## D. Regresión

1. El ★/ojo local (M1.2) y sus filtros/Dashboard siguen funcionando igual
   (no deben verse afectados por esta fase).
2. La pestaña Operaciones general sigue permitiendo crear `favorite.set` /
   `ignored.set` / `contact.add` manualmente (aparecen en el selector de
   operación) con su propio texto de confirmación ("se comprobará el
   ACK/NAK del firmware", no "lectura de verificación automática").
