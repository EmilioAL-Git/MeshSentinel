# M4.2 — Sincronización de favoritos e ignorados

Valida con el simulador primero y después con hardware real. Necesitas al
menos un nodo destino (target) y dos o tres nodos sujeto conocidos.

## Conceptos clave a verificar

- Las listas "Favoritos conocidos" / "Ignorados conocidos" del detalle de
  nodo muestran únicamente los sujetos cuya última acción pedida sea "marcar"
  (los ya quitados desaparecen de la lista, aunque su historial siga
  auditado en Operaciones/Batches).
- **"Sincronizar" ≠ "Reenviar pendientes"**: son botones que resuelven
  problemas distintos (ADR 0020 §3).
  - **Sincronizar** compara lo deseado contra lo último confirmado y solo
    genera lo necesario — si todo ya está confirmado y coincide, el lote no
    debe crearse (`batch_id: null`, sin entrada nueva en Batches).
  - **Reenviar pendientes** solo toca lo que esté en Pendiente/Error; nunca
    reenvía algo ya Confirmado, aunque "Sincronizar" también lo dejaría
    intacto.
- El vocabulario Pendiente/Enviado/Confirmado/Error y la distinción
  `contact.add` ≠ NodeInfo siguen vigentes (ADR 0019, validado en M4.1).

## A. Alta/baja inline

1. Abre el detalle de un nodo (target). En "Favoritos conocidos", elige un
   sujeto en el selector y pulsa **Añadir**. Debe aparecer en la lista con
   badge "Pendiente" sin recargar ni navegar a otra pantalla.
2. Espera a que confirme (o revisa Batches/Actividad: 1 lote, 1 operación
   `favorite.set`).
3. Pulsa **Eliminar** en esa fila: nuevo lote con `favorite.remove`; la fila
   desaparece de la lista en cuanto `latest_action` pasa a "remove" (puede
   tardar unos segundos mientras está "Pendiente").
4. Repite para "Ignorados conocidos".

## B. Sincronizar

1. Con el simulador, añade 2-3 sujetos como favoritos y deja que fallen
   deliberadamente (reintenta hasta ver "Error" — el simulador pierde ~10%).
2. Pulsa **Sincronizar**. Debe crearse **un único lote** que incluya
   únicamente los sujetos no confirmados (los ya "Confirmado" no deben
   generar operación nueva — compruébalo contando operaciones en el lote).
3. Vuelve a pulsar **Sincronizar** con todo ya confirmado: no debe crearse
   ningún lote nuevo (verifícalo en la pestaña Batches: sin entradas
   adicionales).
4. Marca la casilla de ficha de contacto antes de sincronizar: cada `ADD`
   pendiente debe ir precedido de su propio `contact.add` en el lote (orden
   contacto→flag, igual que en alta individual).

## C. Reenviar pendientes

1. Fuerza algún sujeto a "Error" (simulador) y dejar otro ya "Confirmado".
2. Pulsa **Reenviar pendientes**: el lote resultante debe incluir solo el
   sujeto en Error (misma acción que ya tenía), nunca el Confirmado.
3. Si no hay nada pendiente/en error, no debe crearse lote.

## D. Casos límite

1. Un nodo destino sin `gateway_id` conocido debe devolver 409 al intentar
   sincronizar o reenviar (igual que en `queue`, M4.1).
2. Reinicia el backend a mitad de un lote de sincronización: el estado debe
   recuperarse igual que cualquier otro lote (ADR 0016), sin lógica especial
   para favoritos/ignorados.
3. Comprueba que "Sincronizar"/"Reenviar pendientes" en Favoritos no afectan
   en absoluto a la lista de Ignorados del mismo nodo (y viceversa).
