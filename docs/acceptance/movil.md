# Guía de aceptación — uso desde móvil

Punto de corte único: `max-width: 820px` (o móvil en horizontal, `max-height: 500px` + táctil).
Vive en `frontend/src/hooks/useMediaQuery.ts` (`MOBILE_QUERY`) y en `frontend/src/mobile.css`;
deben cambiar juntos. El escritorio no se toca.

Probar con las DevTools (iPhone 12/14, 390×844) o un teléfono real contra `http://<host>:5173`.

## Chasis
- [ ] Cabecera: escudo + buscador (icono) + selector de grupo; sin HUD ni nombre de vista.
- [ ] Barra inferior: Centro · Flota · Trabajos · Alertas · **Más** (Perfiles, Admin remota,
      Registro, Gateways, Top, Ajustes). La insignia de alertas/trabajos de «Más» suma las ocultas.
- [ ] Barra de estado (WS/GW/alertas/cola…) desliza en horizontal, no recorta.
- [ ] Sin scroll horizontal de página en ninguna vista.

## Centro
- [ ] Pestañas **Mapa | Estado | Consola** (una a la vez; el mapa sigue montado al cambiar).
- [ ] Mapa: «☰ Capas» abre la hoja de capas; tocar un marcador abre el Inspector.
- [ ] Estado: semáforo, cola de atención con ACK, gateways. Consola: actividad y trabajos.

## Inspector
- [ ] Pantalla completa; cabecera con acciones (◎ ☆ ◇ 👁 ⌖ ✕) y bloque de identidad/vitales arriba.
- [ ] Pestañas deslizables y pegadas arriba al hacer scroll; contenido a ancho completo.

## Vistas
- [ ] Flota: roster compacto (☐ ★ ● nombre · batería · visto); «⚙ Filtros» despliega el resto;
      barra de selección en 2-3 filas con «Crear lote».
- [ ] Registro: «⚙ Filtros» plegable; Chat: «⚙ Canales y búsqueda» plegable.
- [ ] Alertas: bandeja, historial, reglas, integraciones y canales apilados en una columna.
- [ ] Trabajos / Gateways / Top: sin desbordes; filas de trabajos envuelven.
- [ ] Ajustes: tablas de ajustes como tarjetas apiladas; tablas de datos deslizan en horizontal.
- [ ] Campos de formulario a 16 px (iOS no hace zoom al enfocarlos).
- [ ] Avisos (toast) por encima de la barra inferior.
