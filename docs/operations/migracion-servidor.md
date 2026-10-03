# Migración de un servidor existente a MeshSentinel (renombrado Docker + Datos + traceroute)

Ejecutar **en el servidor** (`ssh vmi2843923.contaboserver.net`), en el directorio de la
instalación. Tiempo de caída estimado: 5-10 min. Nada se borra del stack antiguo hasta el final.

## 0. Reconocimiento (solo lectura)
```bash
cd <ruta-de-la-instalacion>
git log --oneline -1 && git status --short          # ¿cambios locales sin commitear?
docker compose ls                                   # nombre del proyecto actual
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
docker volume ls | grep -E 'postgres|redis'         # volúmenes con nombre OLD_*
df -h /var/lib/docker | tail -1                     # hace falta ~2× el tamaño de la BD libre
grep -E '^(NOC_|POSTGRES_|GATEWAY_|MESHTASTIC_)' .env | sed 's/=.*/=…/'
```
Anota: el **nombre del proyecto antiguo** (`OLD`, normalmente `meshtastic-noc`; si la instalación es
anterior al `name:` fijo, el nombre del directorio) y qué gateways corren (contenedor `gateway`,
contenedores creados por el lanzador, procesos nativos).

## 1. Copia de seguridad (obligatoria)
```bash
docker exec <OLD>-postgres-1 pg_dump -U noc -d noc -Fc > ~/pre-migracion-$(date +%F).dump
cp .env ~/env-pre-migracion
# bájala a tu Mac:  scp vmi2843923.contaboserver.net:~/pre-migracion-*.dump .
```

## 2. ⚠ Antes del primer arranque: retención
Los plazos de fábrica **podan datos** a los 2 min de arrancar (telemetría/posiciones 90 d, vecinos
30 d, chat/alertas/admin/Nexus/accesos 180 d). Si no quieres perder nada todavía, añade a `.env`:
```
NOC_RETENTION_TELEMETRY_DAYS=0
NOC_RETENTION_POSITIONS_DAYS=0
NOC_RETENTION_NEIGHBORS_DAYS=0
NOC_RETENTION_CHAT_DAYS=0
NOC_RETENTION_ALERTS_DAYS=0
NOC_RETENTION_ADMIN_DAYS=0
NOC_RETENTION_NEXUS_DAYS=0
NOC_RETENTION_LOGIN_LOG_DAYS=0
```
y ajusta después con calma en Ajustes → Datos (lo guardado ahí prevalece sobre estas variables).

## 3. Traer el código y revisar `.env`
```bash
git pull                                  # master, commit 36b0861 o posterior
diff <(grep -oE '^#?[A-Z_]+=' .env.example | tr -d '#=' | sort -u) \
     <(grep -oE '^#?[A-Z_]+=' .env | tr -d '#=' | sort -u)     # variables nuevas
```
- Con HTTPS delante: `NOC_COOKIE_SECURE=true`. Con HTTP plano déjalo en false.
- **No cambies `POSTGRES_PASSWORD`** ahora: el volumen existente conserva la contraseña antigua.
- Las migraciones de BD (hasta la 0030, incluidas roles y favoritos personales) corren solas al
  arrancar el backend; el volumen **antiguo** no se toca, así que el rollback es limpio.

## 4. Migrar
Los nombres de volumen/red/imagen cambian a `meshsentinel*`. Sin override de desarrollo:
```bash
OLD=<proyecto-antiguo> tools/migrate_docker_names.sh --dry-run     # revisa el plan
OLD=<proyecto-antiguo> tools/migrate_docker_names.sh               # escribe SI para continuar
```
Variables opcionales: `COMPOSE_FILES="-f docker-compose.yml -f otro.yml"`,
`HEALTH_URL=https://tu-dominio/api/v1/health`, `SERVICES="postgres redis backend frontend"`.
El script para el stack antiguo, copia y **verifica** los volúmenes, levanta el nuevo y comprueba
salud y nº de nodos.

> Si un proxy del host (Caddy/nginx fuera de Docker) apunta al puerto publicado, no cambia nada.
> Si **está dentro de Docker** y se unía a la red `meshtastic-noc`, hay que unirlo a `meshsentinel`.

## 5. Gateways
- El servicio `gateway` del compose ahora lleva `scale: 0` (no arranca solo). Si el servidor lo usaba:
  `docker compose up -d --scale gateway=1 gateway`, **o mejor** recrea la pasarela desde
  *Enlaces → + Añadir gateway → Crear contenedor* (lo gestiona el lanzador).
- Los `gateway-2..6` de la antigua piscina desaparecen (`--remove-orphans`); sus filas fantasma se
  borran desde la UI si quedan.
- Procesos nativos: relánzalos (el Redis nuevo es otro contenedor).

## 6. Verificación
```bash
curl -s http://localhost:8080/api/v1/system/version          # app: MeshSentinel
docker exec meshsentinel-postgres-1 psql -U noc -d noc -Atc "select version_num from alembic_version; select count(*) from nodes;"
```
- La versión de Alembic debe ser `0030`; el nº de nodos, igual que antes de migrar.
- Entra en la UI: **inicia sesión** (si hubo cambio de cookie, re-login), revisa que los favoritos
  siguen (ahora son personales por usuario), Ajustes → **Datos** (tamaño, plazos), Enlaces (pasarelas
  conectadas) y lanza un **⌁ Traceroute** desde el Inspector a un nodo cercano.
- Si los plazos de retención no son los que quieres, ajústalos ahora en Ajustes → Datos y retira las
  variables `NOC_RETENTION_*` de `.env` cuando decidas.

## 7. Limpieza (días después, cuando estés conforme)
```bash
docker volume rm <OLD>_postgres-data <OLD>_redis-data
docker network rm <OLD>
docker image rm <OLD>-backend <OLD>-gateway-launcher <OLD>-gateway:local
```

## Rollback (antes de la limpieza)
```bash
docker compose down                       # para el stack nuevo (sin -v)
git checkout <commit-anterior>            # el que anotaste en el paso 0
docker compose -p <OLD> up -d             # arranca con los volúmenes antiguos intactos
```
