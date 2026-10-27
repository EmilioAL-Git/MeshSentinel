# ADR 0036 — Sidecar de Tailscale para los gateways

- Estado: Aceptado (2026-10-26)
- Complementa: ADR 0023 (transporte TCP), ADR 0028 (lanzador de gateways).

## Contexto

En despliegues sobre un VPS gestionado (Coolify) no se puede instalar
Tailscale en el host, pero los nodos Meshtastic están en la tailnet (IPs
`100.x`). Solo los gateways necesitan alcanzarlos.

## Decisión

Un contenedor `tailscale` (modo TUN, `NET_ADMIN`, estado persistente en el
volumen `tailscale-state`, sin exit node ni `--accept-routes`) actúa de
sidecar. Los gateways comparten su pila de red:

- `gateway` (compose): `network_mode: service:tailscale`.
- Gateways creados por el lanzador: `LAUNCHER_GATEWAY_NETWORK_MODE=
  service:tailscale` (se resuelve al contenedor en marcha por la etiqueta
  `com.docker.compose.service`, acotada al proyecto del lanzador, porque
  Coolify renombra los contenedores; también acepta `container:<nombre>`). Si está definida, se crean con ese
  `network_mode` y no se adjuntan a `LAUNCHER_DOCKER_NETWORK` (excluyentes en
  Docker). Vacía = comportamiento anterior.

El resto (backend, postgres, redis) sigue por la red normal. Los gateways
alcanzan `redis` por DNS porque el sidecar está en la red `noc`.

- `TS_USERSPACE=false` es obligatorio: la imagen arranca por defecto en
  `userspace-networking`, sin interfaz `tailscale0` en el kernel, y el tráfico
  TCP de los gateways no llega a la tailnet (aunque `tailscale ping` funcione).

## Consecuencias

- Docker no permite publicar puertos en `network_mode: container:`: con este
  modo el lanzador no publica el puerto del nodo virtual (ADR 0033); habría
  que publicarlo en el contenedor `tailscale`.
- Todos los gateways comparten IP y espacio de puertos (colisión posible en
  el puerto del nodo virtual).
- Si el sidecar se recrea, los gateways con `container:` deben recrearse.
- `TS_AUTHKEY` es un secreto: solo como variable de Coolify, nunca en el repo.
  `tag:sentinel` debe existir en `tagOwners` de las ACLs de la tailnet.

## Verificación

`docker exec meshsentinel-tailscale tailscale status`
