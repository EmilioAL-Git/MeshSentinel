# Guía de aceptación — JenTastic-Nexus: ajustes del módulo

Cierra el pedido: "en los ajustes, al pinchar en activar Nexus, quiero
ajustes debajo" (ADR 0027 §13).

## Qué se puede probar

1. **Aparecen al activar el modo** (Ajustes → JenTastic-Nexus): justo
   debajo del interruptor, antes de "Detección de nodos JT" y de
   "Operaciones", una sección "Ajustes de JenTastic-Nexus" con todos los
   controles. Con el modo desactivado, no aparece nada (como el resto del
   módulo).

2. **Direccionar un nodo por defecto** ("Nombre corto" / "Node ID"): al
   cambiarlo, entra en la pestaña JenTastic-Nexus del Inspector de
   cualquier nodo — el texto bajo el formulario cambia de
   `-node <nombre>` a `-device <id>` (o viceversa) y las operaciones que
   mandes desde ahí (perfil, seguridad, favoritos, Zero Hop, comando
   suelto) usan ese direccionamiento. Con "Node ID" seleccionado aparece
   un aviso: el node_id puede cambiar al reflashear (firmware 2.8+).
   También aparece como opción "Nodo (-device, node_id)" en el selector
   de destino de Ajustes → Operaciones, sin más restricciones que antes.

3. **Prefijo de comando**: cambiarlo (p. ej. a `/jt`) hace que las
   siguientes operaciones se construyan como `/jt-node ...`/`/jt ...` en
   vez de `/nexus...` — pruébalo con "Previsualizar" en el formulario
   genérico.

4. **Ventana de respuesta** y **cadencia entre escaneos**: cambian el
   tiempo que una operación espera antes de "Sin respuesta" y el tiempo
   mínimo entre pulsaciones de "Buscar nodos JT" respectivamente.

5. **Destino y pasarela por defecto**: al volver a abrir el formulario de
   Ajustes → Operaciones (tras recargar), el selector de destino y de
   pasarela arrancan con lo configurado aquí — el operador puede seguir
   cambiándolos libremente, no se vuelve a aplicar el valor por defecto
   hasta la siguiente carga de la página.

6. **Ocultar comandos del explorador**: "Editar lista" despliega los 186
   comandos con checkbox; marcar uno lo saca del explorador de catálogo
   (Ajustes y pestaña Nexus del Inspector) — el comando sigue siendo
   válido si se escribe a mano o se manda por API. "Mostrar todos" limpia
   la lista de ocultos de un golpe.

7. **Nodos fijados** y **plantillas**: añadir un nodo fijado hace que
   aparezca como chip en el formulario de Ajustes → Operaciones cuando el
   destino es "Nodo (nombre corto)" — un clic rellena el campo. Añadir una
   plantilla (comando + argumentos) hace lo mismo para el par
   comando/argumentos, con un clic.

8. **Avisar cuando termine una difusión**: con la casilla activada, mandar
   un comando en difusión y esperar a que termine la ventana muestra un
   toast ("respondieron nodos" o "sin respuestas") — una sola vez por
   operación, no se repite en pollings siguientes.

## Fuera de alcance de esta fase (con motivo)

- No hay ajuste para el nombre del canal de confianza ("Nexus"/"JenT") —
  esa detección vive en el GATEWAY (proceso desacoplado, ADR 0002), que
  no tiene ningún canal de configuración en caliente desde el backend;
  cambiarlo requeriría una variable de entorno del gateway, no un ajuste
  de UI.
- Los ajustes son globales al despliegue (una fila en `system_settings`
  por clave), no por operador — cualquier administrador que los cambie
  los cambia para todos.
