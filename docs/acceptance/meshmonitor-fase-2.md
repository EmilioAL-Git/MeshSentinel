# Guía de aceptación — grafo RF, posición estimada, cobertura, zonas, Apprise y tokens (ADR 0035)

Requiere rebuild del backend (migraciones 0034-0036 corren solas). Frontend: Vite lo recoge.

## 1. Reglas nuevas (Alertas → Reglas)
«Enlace asimétrico», «Clúster de routers», «Horizonte de saltos», «Router que se mueve». Las dos de
grafo estarán vacías hasta que haya NeighborInfo (activarlo en algunos routers) o trazas.

## 2. Posición estimada
Mapa → capa «◯ Estimadas»: círculos discontinuos en nodos sin GPS (tooltip con radio y nº de anclas).
Se recalcula cada hora; al informar GPS real la estimación desaparece.

## 3. Cobertura medida
Mapa → capa «▦ Cobertura medida»: celdas coloreadas por SNR medio. Se va llenando sola con las
posiciones oídas a 0 saltos; en una malla recién arrancada estará vacía unas horas.

## 4. Zonas
Alertas → Reglas → «+ Nueva» → «Zona: nodo dentro/fuera»: centro (lat/lon), radio, ámbito (mejor un
nodo o un grupo). Probar con un nodo con GPS y un radio pequeño.

## 5. Apprise
Alertas → Integraciones → «+ Nueva» → «Apprise»: URL del servidor (`caronc/apprise-api`) y clave
guardada o URLs. «Probar» envía un mensaje de test.

## 6. Tokens de API
Usuarios → «Tokens de API» (solo admin con sesión): crear, copiar el valor (solo se ve una vez) y
`curl -H "Authorization: Bearer msk_…" …/api/v1/…`. Un Bearer inválido da 401.
