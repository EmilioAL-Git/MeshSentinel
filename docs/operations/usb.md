# Acceso USB serie desde Docker

Para conectar el gateway a un nodo Meshtastic por USB:

1. Identifica el dispositivo en el host: `ls -l /dev/serial/by-id/`.
2. Crea una regla udev con symlink estable (evita el problema de que
   `/dev/ttyUSB0` cambie a `ttyUSB1` tras una reconexión):

   ```
   # /etc/udev/rules.d/99-meshtastic.rules
   SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", SYMLINK+="meshtastic0"
   ```

   (Ajusta idVendor/idProduct con `udevadm info`.) Recarga: `sudo udevadm control --reload && sudo udevadm trigger`.

3. En `docker-compose.yml`, descomenta en el servicio `gateway`:

   ```yaml
   devices:
     - "/dev/meshtastic0:/dev/ttyUSB0"
   ```

4. En `.env`: `GATEWAY_TRANSPORT=serial` y `GATEWAY_SERIAL_DEVICE=/dev/ttyUSB0`.

El contenedor ya añade el usuario al grupo `dialout`. Si el host usa un gid
distinto para el dispositivo, usa `group_add` en el servicio.
