# ADR 0015 — Editor de configuración generado por metadatos (M1.4)

- Estado: Aceptado (2026-07-08)
- Complementa: ADR 0002 (aislamiento de la librería), ADR 0013 (pipeline),
  ADR 0014 (SETs verificables)

## Contexto

M1.4 exige un editor completo de configuración del nodo (todas las secciones
que soporta la librería oficial) sin escribir lógica específica por parámetro:
ni en el registro de capacidades, ni en el backend, ni en el frontend.

## Decisión

1. **Fuente única de metadatos** en el backend
   (`application/admin/config_schema.py`): introspección de
   `config_pb2.Config` y `module_config_pb2.ModuleConfig` a la carga del
   módulo. Se exponen: nombre, tipo primitivo (bool/int/float/str/enum),
   valores de enum, sección padre, grupo UI y clasificación de riesgo
   por sección (SAFE / WARNING / DANGEROUS). El backend importa
   **solo `meshtastic.protobuf`** (read-only): no abre puertos, no cambia
   ADR 0002 (el gateway sigue siendo el único que habla con dispositivos).
2. **Dos operaciones genéricas** en el registro y en el gateway:
   `config.set` y `module_config.set`, ambas con `{section, values}`
   como parámetros. El gateway construye el `AdminMessage.set_config` /
   `set_module_config` fusionando `values` **sobre la lectura previa**
   para evitar que campos no tocados se reseteen a defaults del firmware
   al enviar la sección entera (comportamiento documentado de
   `set_config`).
3. **Pipeline reutilizado** (ADR 0013/0014): cada SET pasa por
   pre-read → set → settle → verify, con veredicto en
   `result.verify` mapeado a `succeeded` / `succeeded_unconfirmed` /
   `verify_failed`. El pre-read tiene la doble función de auditar el
   valor anterior y establecer la sesión admin PKC.
4. **Endpoints REST** (`admin_config.py`):
   - `GET /api/v1/admin/config/schema` — metadatos.
   - `GET /api/v1/nodes/{id}/config` — snapshot por sección extraído
     del historial de operaciones (última GET satisfactoria por sección).
   - `POST /api/v1/nodes/{id}/config/refresh` — encola GETs (todo o subset).
   - `POST /api/v1/nodes/{id}/config/apply` — recibe `{sections: {name: {field: value}}}`,
     valida contra el esquema, encola una SET por sección en el orden:
     owner → módulos SAFE → config SAFE → WARNING → LoRa/security al final.
     Toda validación es previa: si un valor es inválido, ninguna operación
     se crea (sin efectos parciales).
5. **UI dirigida por el esquema** (`ConfigEditor.tsx`): pestañas por
   grupo UI, tabla por sección con controles generados a partir de
   `field.kind`, resumen agregado de cambios pendientes con el riesgo
   más alto de las secciones tocadas y confirmación reforzada por
   teclear el node_id (misma UX que M1.3). Cero lógica por parámetro.

## Consecuencias

- Añadir un campo al firmware/librería no requiere cambios en el NOC:
  aparece automáticamente en el esquema, en el editor y en la
  aplicación tras `pip install -U meshtastic`.
- Cambiar el riesgo de una sección requiere un solo edit en
  `SECTION_RISK` (no hay clasificaciones repetidas).
- El comparador del verify (`compare_section`) tolera diferencias
  entre `snake_case`/`camelCase` (asDict), enums numéricos vs por
  nombre, y defaults proto3 omitidos, para robustez frente a cambios
  menores de la librería.
- Se añade `meshtastic>=2.5,<3` a las dependencias del backend
  exclusivamente para introspección. No se abre ninguna conexión y no
  se importa nada fuera de `meshtastic.protobuf` desde el backend.
