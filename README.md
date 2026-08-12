# ¿Dónde estacioné?

Bot de Telegram que recuerda dónde dejaste el auto sin almacenar tu información. La conversación y una tarjeta fijada funcionan como memoria temporal.

## Funcionalidades

- Guarda una ubicación compartida desde Telegram.
- Fija una tarjeta para representar el estacionamiento activo.
- Recupera la ubicación desde el menú permanente.
- Permite asociar fotos, notas, mensajes de voz y archivos de audio.
- Cambia el menú según exista o no un estacionamiento activo.
- Permite reemplazar o cerrar el estacionamiento.
- No guarda ubicaciones, archivos ni identificadores en una base propia.

## Cómo funciona

1. El usuario toca **🚗 Estacioné** y comparte su ubicación.
2. El bot crea una tarjeta con la ubicación codificada en sus botones y la fija.
3. **📍 ¿Dónde está mi auto?** lee la tarjeta y vuelve a enviar la ubicación.
4. Las referencias se agregan respondiendo directamente a la tarjeta.
5. **✅ Encontré el auto** elimina los botones y desfija el recordatorio.

La [política de privacidad](PRIVACY.md) explica con mayor detalle qué datos
intervienen en el funcionamiento.

## Menú contextual

Sin estacionamiento activo:

- 🚗 Estacioné
- ❓ Ayuda

Con estacionamiento activo:

- 📍 ¿Dónde está mi auto?
- ✅ Encontré el auto
- 🔄 Reemplazar ubicación
- ❓ Ayuda

## Requisitos

- Python 3.10 o posterior.
- Un bot creado mediante [BotFather](https://t.me/BotFather).

## Uso local

1. Crear y activar un entorno virtual.
2. Instalar las dependencias:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Copiar `.env.example` como `.env` y completar el token:

   ```env
   TELEGRAM_BOT_TOKEN=token_entregado_por_BotFather
   ALLOWED_TELEGRAM_USER_ID=
   ```

   `ALLOWED_TELEGRAM_USER_ID` vacío permite el uso público. Durante las
   pruebas puede contener uno o varios IDs separados por comas.

4. Iniciar el bot:

   ```powershell
   python bot.py
   ```

Solo debe ejecutarse una instancia con el mismo token.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```

## Docker

El proyecto incluye un `Dockerfile` preparado para ejecutar el bot como un
usuario sin privilegios:

```bash
docker build -t donde-estacione-bot .
docker run --env-file .env donde-estacione-bot
```

## Licencia

Distribuido bajo la [licencia MIT](LICENSE).
