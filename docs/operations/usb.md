# Acceso USB serie desde Docker

Para conectar el gateway a un nodo Meshtastic por USB (`GATEWAY_TRANSPORT=usb`):

1. Identifica el dispositivo en el host:

   ```bash
   ls -l /dev/serial/by-id/
   dmesg | tail            # tras enchufar: suele aparecer como ttyACM0 o ttyUSB0
   ```

2. Crea una regla udev con symlink estable (evita que `/dev/ttyACM0` cambie a
   `ttyACM1` tras una reconexión):

   ```
   # /etc/udev/rules.d/99-meshtastic.rules
   SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", SYMLINK+="meshtastic0"
   ```

   (Ajusta idVendor/idProduct con `udevadm info -a -n /dev/ttyACM0 | grep -i 'idvendor\|idproduct'`.)
   Recarga: `sudo udevadm control --reload && sudo udevadm trigger`.

3. En `docker-compose.yml`, descomenta en el servicio `gateway`:

   ```yaml
   devices:
     - "/dev/meshtastic0:/dev/ttyACM0"
   ```

4. En `.env`:

   ```env
   GATEWAY_TRANSPORT=usb
   MESHTASTIC_USB_DEVICE=/dev/ttyACM0
   ```

   Dentro del contenedor solo es visible el dispositivo mapeado, por lo que la
   autodetección (`MESHTASTIC_USB_DEVICE=` vacío) también funciona y es la
   opción recomendada si solo hay un nodo.

Notas:

- **No usar `privileged: true`**: mapear el dispositivo concreto basta y
  privilegiar el contenedor expondría todo `/dev` (ADR 0010).
- El contenedor ya añade el usuario al grupo `dialout`. Si el host usa un gid
  distinto para el dispositivo, usa `group_add: ["<gid>"]` en el servicio.
- Sin baudrate ni parámetros serie: los gestiona la librería oficial.
- Si tras desenchufar/enchufar el gateway no recupera (el nodo de dispositivo
  puede no reaparecer dentro del contenedor según el host), `docker compose
  restart gateway` lo soluciona; `restart: unless-stopped` cubre los fallos.
