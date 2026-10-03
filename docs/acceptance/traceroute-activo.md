# Guía de aceptación — Traceroute activo, WS y sondeo adaptativo

## Traceroute activo (`traceroute.run`)
1. Inspector de un nodo → **⌁ Traceroute**. Entra en la cola como una operación más
   (pasarela resuelta por la jerarquía habitual: forzada → preferida del nodo → del grupo →
   automática). También desde Trabajos → nueva operación (parámetro `hop_limit` 1-7, def. 5).
2. Al terminar sale un toast: «directo, sin saltos intermedios · SNR 5 dB», o
   «2 saltos intermedios: !a → !b», o «sin respuesta (fuera de alcance o saturado)».
3. La respuesta, al ir dirigida a la pasarela, también aparece como entrada «Traceroute» en el
   Registro y la capa **Rutas** del mapa la dibuja.
4. «Sin respuesta» NO es un fallo de la operación y **no se reintenta** (cada intento inunda la
   malla hasta `hop_limit` saltos). No admite lotes.
5. Simulador: devuelve rutas ficticias deterministas (mitad directos, mitad con un salto).

## Canal en vivo (WebSocket)
- Ajustes → General → Seguridad → «Canal en vivo»: *Abierto* (defecto) o *Exigir sesión*. Con
  modo protegido + «Exigir sesión», una pestaña sin sesión no recibe eventos; al iniciar sesión
  reconecta sola en <1 s.

## Sondeo adaptativo
- Con el WS conectado, los sondeos de seguridad del shell (nodos, alertas, contadores,
  pasarelas, dashboard) se espacian ×4; si el WS cae vuelven al ritmo normal. Las pestañas
  ocultas del navegador no sondean. Las vistas no activas están desmontadas y no sondean.

## Selección de gateway por operación
Ya estaba implementada (override del operador en el formulario/asistente, preferencia de nodo y
de grupo, ranking automático con aviso de fallback).
