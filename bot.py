"""Bot de Telegram para recordar un estacionamiento sin persistencia propia."""

import hashlib
import logging
import os
import unicodedata

from dotenv import load_dotenv
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


load_dotenv()

LOGGER = logging.getLogger(__name__)

PARK_BUTTON = "🚗 Estacioné"
FIND_BUTTON = "📍 ¿Dónde está mi auto?"
CLOSE_BUTTON = "✅ Encontré el auto"
REPLACE_BUTTON = "🔄 Reemplazar ubicación"
HELP_BUTTON = "❓ Ayuda"
CANCEL_BUTTON = "❌ Cancelar"

CARD_OPEN = "🚗 Estacionamiento guardado"
CARD_CLOSED = "✅ Auto encontrado"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower().strip())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return " ".join(
        "".join(char for char in word if char.isalnum()).strip()
        for word in text.split()
    ).strip()


def allowed_user_ids() -> set[int] | None:
    allowed = os.getenv("ALLOWED_TELEGRAM_USER_ID", "").strip()
    if not allowed:
        return None
    try:
        return {
            int(value.strip()) for value in allowed.split(",") if value.strip()
        }
    except ValueError as error:
        raise RuntimeError(
            "ALLOWED_TELEGRAM_USER_ID debe contener IDs numéricos separados por comas"
        ) from error


def authorized(update: Update) -> bool:
    allowed_ids = allowed_user_ids()
    return allowed_ids is None or bool(
        update.effective_user and update.effective_user.id in allowed_ids
    )


async def reject_if_unauthorized(update: Update) -> bool:
    if authorized(update):
        return False
    if update.effective_message:
        await update.effective_message.reply_text("Este bot es privado.")
    return True


def inactive_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[PARK_BUTTON], [HELP_BUTTON]],
        resize_keyboard=True,
        input_field_placeholder="Elegí una opción",
    )


def active_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[FIND_BUTTON, CLOSE_BUTTON], [REPLACE_BUTTON], [HELP_BUTTON]],
        resize_keyboard=True,
        input_field_placeholder="Elegí una opción",
    )


def location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📍 Compartir mi ubicación", request_location=True)],
            [CANCEL_BUTTON],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def location_callback(
    action: str,
    latitude: float,
    longitude: float,
    card_message_id: int | None = None,
) -> str:
    """Codifica la ubicación en la propia tarjeta de Telegram."""
    parts = [action, f"{latitude:.6f}", f"{longitude:.6f}"]
    if card_message_id is not None:
        parts.append(str(card_message_id))
    return "|".join(parts)


def parse_location_callback(
    data: str,
) -> tuple[str | None, float | None, float | None, int | None]:
    try:
        parts = data.split("|")
        if len(parts) not in {3, 4}:
            raise ValueError
        action, latitude, longitude = parts[:3]
        card_message_id = int(parts[3]) if len(parts) == 4 else None
        return action, float(latitude), float(longitude), card_message_id
    except (AttributeError, TypeError, ValueError):
        return None, None, None, None


def card_location(message) -> tuple[float, float] | None:
    """Recupera la ubicación almacenada en los botones de una tarjeta."""
    if not message or not message.reply_markup:
        return None
    for row in message.reply_markup.inline_keyboard:
        for button in row:
            action, latitude, longitude, _ = parse_location_callback(
                button.callback_data
            )
            if action in {
                "view",
                "ask_close",
                "confirm_close",
                "cancel_close",
                "cancel_recovered_close",
            }:
                return latitude, longitude
    return None


def parking_card_keyboard(latitude: float, longitude: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📍 Ver ubicación",
                    callback_data=location_callback("view", latitude, longitude),
                ),
                InlineKeyboardButton(
                    "✅ Encontré el auto",
                    callback_data=location_callback(
                        "ask_close", latitude, longitude
                    ),
                ),
            ]
        ]
    )


def close_confirmation_keyboard(
    latitude: float, longitude: float
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Sí, cerrar",
                    callback_data=location_callback(
                        "confirm_close", latitude, longitude
                    ),
                ),
                InlineKeyboardButton(
                    "No",
                    callback_data=location_callback(
                        "cancel_close", latitude, longitude
                    ),
                ),
            ]
        ]
    )


def recovered_close_confirmation_keyboard(
    latitude: float,
    longitude: float,
    card_message_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Sí, cerrar",
                    callback_data=location_callback(
                        "confirm_close", latitude, longitude, card_message_id
                    ),
                ),
                InlineKeyboardButton(
                    "No",
                    callback_data=location_callback(
                        "cancel_recovered_close",
                        latitude,
                        longitude,
                        card_message_id,
                    ),
                ),
            ]
        ]
    )


def is_parking_card(message) -> bool:
    return bool(
        message
        and message.from_user
        and message.from_user.is_bot
        and message.text
        and (
            message.text.startswith(CARD_OPEN)
            or message.text.startswith("¿Confirmás")
        )
        and card_location(message)
    )


async def active_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = await context.bot.get_chat(update.effective_chat.id)
    card = chat.pinned_message
    return card if is_parking_card(card) else None


async def contextual_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return (
        active_keyboard()
        if await active_card(update, context)
        else inactive_keyboard()
    )


async def help_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_unauthorized(update):
        return
    name = update.effective_user.first_name or ""
    greeting = f"¡Hola, {name}! 🚗" if name else "¡Hola! 🚗"
    keyboard = await contextual_keyboard(update, context)
    await update.effective_message.reply_text(
        f"{greeting}\n\n"
        "Te ayudo a recordar dónde dejaste el auto:\n\n"
        "1. Tocá “🚗 Estacioné” y compartí tu ubicación.\n"
        "2. Te voy a dejar una tarjeta fijada en el chat: esa tarjeta es tu recordatorio.\n"
        "3. Podés responderle con una foto, un audio o una nota.\n"
        "4. Tocá “📍 ¿Dónde está mi auto?” y voy a recuperar la ubicación.\n"
        "5. Cuando vuelvas, tocá “✅ Encontré el auto”.\n\n"
        "Al cerrar el estacionamiento, la tarjeta se desfija automáticamente.",
        reply_markup=keyboard,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await help_message(update, context)


async def ask_location(update: Update):
    await update.effective_message.reply_text(
        "¿Dónde estacionaste? Tocá el botón para compartir tu ubicación 👇",
        reply_markup=location_keyboard(),
    )


async def estacionar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_unauthorized(update):
        return
    await ask_location(update)


async def receive_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_unauthorized(update):
        return

    chat = await context.bot.get_chat(update.effective_chat.id)
    previous_card = chat.pinned_message
    latitude = update.message.location.latitude
    longitude = update.message.location.longitude
    card = await update.message.reply_text(
        f"{CARD_OPEN} 📍\n\n"
        "Esta tarjeta fijada es el recordatorio de tu estacionamiento.\n"
        "Podés responderle con una foto, un audio o una nota.",
        reply_markup=parking_card_keyboard(latitude, longitude),
        reply_to_message_id=update.message.message_id,
    )
    try:
        await context.bot.pin_chat_message(
            chat_id=card.chat_id,
            message_id=card.message_id,
            disable_notification=True,
        )

        if is_parking_card(previous_card):
            try:
                await context.bot.edit_message_text(
                    chat_id=previous_card.chat_id,
                    message_id=previous_card.message_id,
                    text=(
                        f"{CARD_CLOSED} ✅\n\n"
                        "Se reemplazó por un estacionamiento nuevo."
                    ),
                )
                await context.bot.unpin_chat_message(
                    chat_id=previous_card.chat_id,
                    message_id=previous_card.message_id,
                )
            except BadRequest:
                LOGGER.info(
                    "La tarjeta anterior ya estaba modificada o desfijada."
                )

        await update.message.reply_text(
            "Listo: fijé la tarjeta. Cuando quieras volver, tocá “📍 ¿Dónde está mi auto?”.",
            reply_markup=active_keyboard(),
        )
    except BadRequest:
        await update.message.reply_text(
            "Guardé la tarjeta, pero Telegram no me permitió fijarla. "
            "Para recuperarla automáticamente necesito permiso para fijar mensajes en este chat.",
            reply_markup=inactive_keyboard(),
        )


async def receive_reference(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_unauthorized(update):
        return
    if is_parking_card(update.message.reply_to_message):
        await update.message.reply_text(
            "Referencia agregada a este estacionamiento ✅",
            reply_markup=active_keyboard(),
        )
        return

    keyboard = await contextual_keyboard(update, context)
    await update.message.reply_text(
        "Para asociar esa referencia, respondé directamente a la tarjeta del estacionamiento.",
        reply_markup=keyboard,
    )


async def find_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_unauthorized(update):
        return
    card = await active_card(update, context)
    if not card:
        await update.effective_message.reply_text(
            "No encontré un estacionamiento activo. Tocá “🚗 Estacioné” para guardar uno.",
            reply_markup=inactive_keyboard(),
        )
        return

    latitude, longitude = card_location(card)
    await context.bot.send_location(
        chat_id=card.chat_id,
        latitude=latitude,
        longitude=longitude,
        reply_markup=active_keyboard(),
    )


async def request_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_unauthorized(update):
        return

    card = await active_card(update, context)
    if not card:
        await update.effective_message.reply_text(
            "No encontré un estacionamiento activo.",
            reply_markup=inactive_keyboard(),
        )
        return

    latitude, longitude = card_location(card)
    await update.effective_message.reply_text(
        "¿Confirmás que encontraste el auto?",
        reply_markup=recovered_close_confirmation_keyboard(
            latitude, longitude, card.message_id
        ),
    )


async def privacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_unauthorized(update):
        return
    keyboard = await contextual_keyboard(update, context)
    await update.effective_message.reply_text(
        "Privacidad 🔒\n\n"
        "Este bot no usa una base de datos y no conserva ubicaciones, fotos, audios, notas ni "
        "identificadores de usuarios en su servidor. El contenido permanece en tu conversación "
        "de Telegram y podés eliminarlo desde el propio chat.\n\n"
        "La ubicación queda contenida temporalmente en los botones de la tarjeta fijada por Telegram. "
        "Al cerrar el estacionamiento, esos botones se eliminan.",
        reply_markup=keyboard,
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_unauthorized(update):
        return
    query = update.callback_query
    await query.answer()
    card = query.message
    action, latitude, longitude, original_card_id = parse_location_callback(query.data)

    valid_source = is_parking_card(card) or (
        original_card_id is not None
        and card.from_user
        and card.from_user.is_bot
    )
    if not valid_source or latitude is None or longitude is None:
        await query.answer(
            "La referencia original ya no está disponible.",
            show_alert=True,
        )
        return

    if action == "view":
        await context.bot.send_location(
            chat_id=card.chat_id,
            latitude=latitude,
            longitude=longitude,
        )
    elif action == "ask_close":
        await query.edit_message_text(
            "¿Confirmás que encontraste el auto?",
            reply_markup=(
                recovered_close_confirmation_keyboard(
                    latitude, longitude, original_card_id
                )
                if original_card_id is not None
                else close_confirmation_keyboard(latitude, longitude)
            ),
        )
    elif action == "cancel_close":
        await query.edit_message_text(
            f"{CARD_OPEN} 📍\n\n"
            "Esta tarjeta es el recordatorio de tu estacionamiento.\n"
            "Podés responderle con una foto, un audio o una nota.",
            reply_markup=parking_card_keyboard(latitude, longitude),
        )
    elif action == "cancel_recovered_close":
        await query.edit_message_text(
            "Operación cancelada.",
        )
    elif action == "confirm_close":
        target_message_id = original_card_id or card.message_id
        try:
            await context.bot.unpin_chat_message(
                chat_id=card.chat_id,
                message_id=target_message_id,
            )
        except BadRequest:
            LOGGER.info("La tarjeta ya no estaba fijada al momento de cerrarla.")
        closed_text = (
            f"{CARD_CLOSED} ✅\n\n"
            "Cerré y desfijé este recordatorio. No había datos tuyos guardados en el servidor."
        )
        if original_card_id is not None:
            try:
                await context.bot.edit_message_text(
                    chat_id=card.chat_id,
                    message_id=original_card_id,
                    text=closed_text,
                )
            except BadRequest:
                LOGGER.info("No se pudo editar la tarjeta original al cerrarla.")
            await query.delete_message()
            await context.bot.send_message(
                chat_id=card.chat_id,
                text="¡Auto encontrado! Cerré el estacionamiento ✅",
                reply_markup=inactive_keyboard(),
            )
        else:
            await query.edit_message_text(closed_text)
            await context.bot.send_message(
                chat_id=card.chat_id,
                text="El menú ya está listo para un nuevo estacionamiento.",
                reply_markup=inactive_keyboard(),
            )


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_unauthorized(update):
        return

    if is_parking_card(update.message.reply_to_message):
        await receive_reference(update, context)
        return

    text = normalize(update.message.text)
    if text in {normalize(PARK_BUTTON), "estacione", "estacionar", "deje el auto"}:
        await ask_location(update)
    elif text in {
        normalize(FIND_BUTTON),
        "donde estacione",
        "donde esta el auto",
        "donde deje el auto",
    }:
        await find_card(update, context)
    elif text in {
        normalize(CLOSE_BUTTON),
        "encontre",
        "encontre el auto",
        "ya lo encontre",
        "cerrar",
        "encontrado",
    }:
        await request_close(update, context)
    elif text in {normalize(REPLACE_BUTTON), "reemplazar ubicacion"}:
        await ask_location(update)
    elif text in {normalize(CANCEL_BUTTON), "cancelar"}:
        keyboard = await contextual_keyboard(update, context)
        await update.message.reply_text(
            "Operación cancelada.",
            reply_markup=keyboard,
        )
    elif text in {normalize(HELP_BUTTON), "ayuda", "help"}:
        await help_message(update, context)
    else:
        keyboard = await contextual_keyboard(update, context)
        await update.message.reply_text(
            "No entendí ese mensaje. Elegí una opción del menú o tocá “❓ Ayuda”.",
            reply_markup=keyboard,
        )


async def post_init(application: Application):
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Abrir el menú principal"),
            BotCommand("estacione", "Crear una tarjeta de estacionamiento"),
            BotCommand("donde", "Recuperar la ubicación guardada"),
            BotCommand("cerrar", "Cerrar el estacionamiento activo"),
            BotCommand("ayuda", "Ver cómo funciona"),
            BotCommand("privacidad", "Ver cómo se manejan tus datos"),
        ]
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    LOGGER.exception(
        "Error no controlado al procesar una actualización",
        exc_info=context.error,
    )


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN en .env")
    allowed_user_ids()

    application = Application.builder().token(token).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ayuda", help_message))
    application.add_handler(CommandHandler("estacione", estacionar_command))
    application.add_handler(CommandHandler("donde", find_card))
    application.add_handler(CommandHandler("cerrar", request_close))
    application.add_handler(CommandHandler("privacidad", privacy))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.LOCATION, receive_location))
    application.add_handler(
        MessageHandler(filters.PHOTO | filters.VOICE | filters.AUDIO, receive_reference)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_message)
    )
    application.add_error_handler(error_handler)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if render_url:
        port = int(os.getenv("PORT", "10000"))
        webhook_path = "telegram"
        webhook_secret = hashlib.sha256(token.encode("utf-8")).hexdigest()
        LOGGER.info("Bot iniciado mediante webhook en Render")
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=webhook_path,
            webhook_url=f"{render_url}/{webhook_path}",
            secret_token=webhook_secret,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        LOGGER.info("Bot iniciado mediante polling")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
