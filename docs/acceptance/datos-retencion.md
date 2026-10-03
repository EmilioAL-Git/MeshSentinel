# Guía de aceptación — Datos: retención, almacenamiento, copia y resumen

Ajustes → **Datos** (solo administradores).

1. **Plazos**: cada tipo (telemetría, posiciones, vecinos, chat, alertas resueltas,
   operaciones admin, Nexus, accesos, nodos sin actividad) tiene su plazo. «Siempre»
   desactiva la poda de ese tipo. Cambia uno → «Datos» refleja el plazo en la tabla
   «Almacenamiento por tipo de dato» sin reiniciar.
2. **Aplicar ahora**: borra lo que supere los plazos. Toast con filas eliminadas; el KPI
   «Última poda» se actualiza. Con todos en «Siempre» → «Nada que podar».
3. **Nada vivo se borra**: alertas activas/reconocidas, operaciones en cola/en curso y
   lotes en marcha sobreviven aunque sean más antiguos que el plazo.
4. **Nodos sin actividad** (0 por defecto): con 30 d, un nodo sin oírse 30 d desaparece con
   su historia; favoritos y nodos locales de pasarela se conservan.
5. **Almacenamiento**: tamaño de BD, filas, tamaño y fecha más antigua por tipo;
   «Todas las tablas» desplegable.
6. **Resumen periódico**: configura periodicidad/hora (UTC) y pulsa «Enviar ahora»; llega a
   todas las integraciones habilitadas (Alertas → Integraciones). Sin integraciones → error
   claro. El último envío queda registrado (un reinicio no duplica).
7. **Copia de seguridad**: «Descargar copia» baja un `.jsonl.gz`. Restauración (BD vacía y
   migrada): `docker compose exec backend python -m noc.restore_backup /ruta/copia.jsonl.gz`.
8. **Salud del proceso**: pestañas conectadas, cola del Registro (descartes en ámbar),
   latencia del bucle de eventos.
9. **WebSocket**: un cliente colgado se expulsa a los 5 s (contador «expulsadas») y ya no
   retrasa la ingesta ni a las demás pestañas.
10. **Exportar**: Flota (⤓ exportar → CSV/GeoJSON de la lista filtrada), Registro (⤓ CSV de
    lo filtrado) y cada ranking de Estadísticas.
