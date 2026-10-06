# Guía de aceptación — identidad, claves, informe de problemas, entrega y copias (ADR 0034)

Requiere rebuild del backend (`docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d --no-deps backend`);
no hay migración. Frontend: Vite lo recoge solo.

## 1. Cambios de identidad
1. `curl localhost:8000/api/v1/identity` → `changes` con pares `predecessor_id → successor_id`.
2. Flota: los nodos implicados llevan ⇄ (pasa el ratón para ver el motivo) y ⚠ si hay clave duplicada/débil.
3. Abrir un nodo viejo → Resumen: aviso «Identidad antigua: sustituida por …». En el nuevo: «Sustituye a …».
4. «Fusionar historial…» (solo gestor/admin): teclear el id del viejo → se mueve el historial y se
   abre el nodo nuevo. **Irreversible**: probar con un par sin valor.
5. El nodo viejo emparejado deja de generar «Nodo sin actividad».

## 2. Claves
Alertas → regla «Seguridad de claves». Los duplicados con mismo nombre indican «posible mismo equipo
con otro número» (no es necesariamente un clon).

## 3. Informe de problemas
Alertas → Reglas: «Nodo parlanchín», «Rol obsoleto», «Posición en exceso», «Telemetría en exceso»
(botón Ajustar para cambiar umbrales). Si alguna dispara demasiado, subir el umbral o deshabilitarla.

## 4. Entrega
Chat → «ⓘ entrega» en un mensaje con `packet_id`: pasarelas que lo oyeron, SNR/RSSI/saltos con su
procedencia (R reportado · O observado · I inferido · ? desconocido).

## 5. Copias programadas
Ajustes → Datos → «Copias automáticas»: elegir periodicidad y nº de copias; «Copiar ahora»; descarga
con ⤓. Para probar el aviso de fallo: apuntar `NOC_BACKUP_DIR` a una ruta no escribible.
Restaurar: `docker compose exec backend python -m noc.restore_backup /backups/<fichero>.jsonl.gz`.
