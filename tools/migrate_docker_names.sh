#!/usr/bin/env bash
# Migra el stack Docker del nombre antiguo (proyecto/red/imagen "meshtastic-noc")
# al nuevo ("meshsentinel") CONSERVANDO los datos: copia los volúmenes de
# PostgreSQL y Redis al nombre nuevo y levanta el stack. NO borra nada del
# stack antiguo: al final imprime los comandos de limpieza para que los lances tú.
#
#   tools/migrate_docker_names.sh --dry-run   # solo muestra qué haría
#   tools/migrate_docker_names.sh             # ejecuta (pide confirmación)
#
# Requisitos: Docker en marcha; haber descargado antes una copia de seguridad
# (Ajustes → Datos → Descargar copia) como red de seguridad adicional.
set -euo pipefail

OLD=meshtastic-noc
NEW=meshsentinel
VOLUMES=(postgres-data redis-data)
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.dev.yml)
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

cd "$(dirname "$0")/.."

run() { echo "+ $*"; [[ $DRY -eq 1 ]] || "$@"; }
die() { echo "ERROR: $*" >&2; exit 1; }

docker info >/dev/null 2>&1 || die "Docker no responde. Ábrelo y reintenta."

# ── Comprobaciones previas ─────────────────────────────────────────────
for v in "${VOLUMES[@]}"; do
  docker volume inspect "${OLD}_${v}" >/dev/null 2>&1 || die "No existe el volumen ${OLD}_${v}: ¿ya migraste?"
  if docker volume inspect "${NEW}_${v}" >/dev/null 2>&1; then
    die "Ya existe ${NEW}_${v}. Revísalo (docker volume inspect) antes de sobrescribir nada."
  fi
done
grep -q "^name: ${NEW}$" docker-compose.yml || die "docker-compose.yml aún no usa 'name: ${NEW}'."

if [[ $DRY -eq 0 ]]; then
  echo "Se va a PARAR el stack '${OLD}' (la app quedará caída unos minutos),"
  echo "copiar sus volúmenes a '${NEW}_*' y levantar el stack nuevo."
  echo "Los gateways nativos (USB/TCP) tendrás que relanzarlos al final."
  read -r -p "¿Hiciste ya la copia de seguridad desde Ajustes → Datos? Escribe SI para continuar: " ok
  [[ "$ok" == "SI" ]] || die "Cancelado."
fi

# ── 1. Parar el stack antiguo (por etiqueta de proyecto, no por ficheros) ───
ids=$(docker ps -q --filter "label=com.docker.compose.project=${OLD}")
if [[ -n "$ids" ]]; then
  # shellcheck disable=SC2086
  run docker stop -t 60 $ids
fi

# ── 2. Copiar volúmenes (los antiguos quedan intactos) ────────────────────
for v in "${VOLUMES[@]}"; do
  run docker volume create \
    --label "com.docker.compose.project=${NEW}" \
    --label "com.docker.compose.volume=${v}" \
    "${NEW}_${v}"
  run docker run --rm -v "${OLD}_${v}:/from:ro" -v "${NEW}_${v}:/to" alpine \
    sh -c 'cp -a /from/. /to/'
  if [[ $DRY -eq 0 ]]; then
    a=$(docker run --rm -v "${OLD}_${v}:/d:ro" alpine sh -c 'find /d | wc -l')
    b=$(docker run --rm -v "${NEW}_${v}:/d:ro" alpine sh -c 'find /d | wc -l')
    [[ "$a" == "$b" ]] || die "Copia de ${v} incompleta (${a} vs ${b} entradas). No se ha borrado nada."
    echo "  ${v}: ${a} entradas copiadas y verificadas"
  fi
done

# ── 3. Levantar el stack nuevo ────────────────────────────────────────────
run "${COMPOSE[@]}" up --build -d --remove-orphans

# ── 4. Verificación ───────────────────────────────────────────────────────
if [[ $DRY -eq 0 ]]; then
  echo -n "Esperando al backend"
  for _ in $(seq 1 60); do
    if curl -fs -m 3 localhost:8000/api/v1/health >/dev/null 2>&1; then break; fi
    echo -n "."; sleep 3
  done
  echo
  curl -fs -m 5 localhost:8000/api/v1/health || die "El backend no responde; el stack antiguo y sus volúmenes siguen intactos."
  echo
  n=$(docker exec "${NEW}-postgres-1" psql -U "${POSTGRES_USER:-noc}" -d "${POSTGRES_DB:-noc}" -Atc 'select count(*) from nodes' 2>/dev/null || echo '?')
  echo "Nodos en la BD migrada: ${n}"
fi

cat <<MSG

════════════════════════════════════════════════════════════════════
Migración hecha. Pendiente por tu parte:
  1. Relanza los gateways nativos (el Redis nuevo es otro contenedor).
  2. Comprueba la app (nodos, historial, usuarios) con calma.
  3. SOLO cuando estés conforme, limpia lo antiguo:
       docker volume rm ${OLD}_postgres-data ${OLD}_redis-data
       docker network rm ${OLD}
       docker image rm ${OLD}-backend ${OLD}-gateway-launcher ${OLD}-gateway:local
Rollback (antes de limpiar): para el stack nuevo y, con el compose anterior
(git stash / git checkout docker-compose.yml), 'docker compose up -d'.
════════════════════════════════════════════════════════════════════
MSG
