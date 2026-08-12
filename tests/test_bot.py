import unittest
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch

from bot import (
    CARD_OPEN,
    active_keyboard,
    allowed_user_ids,
    button_callback,
    card_reference_ids,
    find_card,
    location_callback,
    normalize,
    parking_card_keyboard,
    receive_reference,
    receive_location,
    request_close,
    inactive_keyboard,
    text_message,
)


class BotTests(unittest.TestCase):
    def test_normalize_removes_accents_case_and_punctuation(self):
        self.assertEqual(normalize(" ¿Dónde ESTACIONÉ? "), "donde estacione")

    def test_close_phrase_normalizes_as_expected(self):
        self.assertEqual(normalize("¡Encontré el auto!"), "encontre el auto")

    def test_public_access_when_allowed_user_id_is_empty(self):
        with patch.dict("os.environ", {"ALLOWED_TELEGRAM_USER_ID": ""}):
            self.assertIsNone(allowed_user_ids())

    def test_rejects_invalid_allowed_user_id(self):
        with patch.dict("os.environ", {"ALLOWED_TELEGRAM_USER_ID": "Mariana"}):
            with self.assertRaises(RuntimeError):
                allowed_user_ids()

    def test_contextual_keyboards_show_only_valid_actions(self):
        inactive_texts = [
            button.text for row in inactive_keyboard().keyboard for button in row
        ]
        active_texts = [
            button.text for row in active_keyboard().keyboard for button in row
        ]
        self.assertIn("🚗 Estacioné", inactive_texts)
        self.assertNotIn("📍 ¿Dónde está mi auto?", inactive_texts)
        self.assertIn("✅ Encontré el auto", active_texts)
        self.assertNotIn("🚗 Estacioné", active_texts)


def parking_card(message_id=20, location_message_id=10, reference_ids=None):
    location_message = SimpleNamespace(
        message_id=location_message_id,
        location=SimpleNamespace(latitude=-34.9, longitude=-58.5),
    )
    return SimpleNamespace(
        chat_id=1,
        message_id=message_id,
        from_user=SimpleNamespace(is_bot=True),
        text=f"{CARD_OPEN} 📍",
        reply_to_message=location_message,
        reply_markup=parking_card_keyboard(-34.9, -58.5, reference_ids),
    )


class BotFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_photo_is_added_when_parking_is_active(self):
        message = SimpleNamespace(
            message_id=30,
            reply_to_message=None,
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(
            message=message,
            effective_message=message,
            effective_chat=SimpleNamespace(id=1),
            effective_user=SimpleNamespace(id=2),
        )
        bot = SimpleNamespace(
            get_chat=AsyncMock(
                return_value=SimpleNamespace(pinned_message=parking_card())
            ),
            edit_message_reply_markup=AsyncMock(),
        )

        await receive_reference(update, SimpleNamespace(bot=bot))

        self.assertIn(
            "Referencia agregada",
            message.reply_text.await_args.args[0],
        )
        markup = bot.edit_message_reply_markup.await_args.kwargs["reply_markup"]
        stored_card = SimpleNamespace(reply_markup=markup)
        self.assertEqual(card_reference_ids(stored_card), [30])

    async def test_reference_requires_an_active_parking(self):
        message = SimpleNamespace(
            reply_to_message=None,
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(
            message=message,
            effective_message=message,
            effective_chat=SimpleNamespace(id=1),
            effective_user=SimpleNamespace(id=2),
        )
        bot = SimpleNamespace(
            get_chat=AsyncMock(
                return_value=SimpleNamespace(pinned_message=None)
            ),
        )

        await receive_reference(update, SimpleNamespace(bot=bot))

        self.assertIn(
            "No hay un estacionamiento activo",
            message.reply_text.await_args.args[0],
        )

    async def test_direct_text_is_added_as_note_when_parking_is_active(self):
        message = SimpleNamespace(
            message_id=31,
            text="Nivel 2, cerca del ascensor",
            reply_to_message=None,
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(
            message=message,
            effective_message=message,
            effective_chat=SimpleNamespace(id=1),
            effective_user=SimpleNamespace(id=2),
        )
        bot = SimpleNamespace(
            get_chat=AsyncMock(
                return_value=SimpleNamespace(pinned_message=parking_card())
            ),
            edit_message_reply_markup=AsyncMock(),
        )

        await text_message(update, SimpleNamespace(bot=bot))

        self.assertIn("Referencia agregada", message.reply_text.await_args.args[0])
        markup = bot.edit_message_reply_markup.await_args.kwargs["reply_markup"]
        stored_card = SimpleNamespace(reply_markup=markup)
        self.assertEqual(card_reference_ids(stored_card), [31])

    async def test_receive_location_creates_and_pins_card(self):
        card = parking_card()
        message = SimpleNamespace(
            message_id=10,
            location=SimpleNamespace(latitude=-34.9, longitude=-58.5),
            reply_text=AsyncMock(side_effect=[card, None]),
        )
        update = SimpleNamespace(
            message=message,
            effective_message=message,
            effective_chat=SimpleNamespace(id=1),
            effective_user=SimpleNamespace(id=2),
        )
        bot = SimpleNamespace(
            get_chat=AsyncMock(return_value=SimpleNamespace(pinned_message=None)),
            pin_chat_message=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot)

        await receive_location(update, context)

        bot.pin_chat_message.assert_awaited_once_with(
            chat_id=1, message_id=20, disable_notification=True
        )
        confirmation = message.reply_text.await_args_list[1].args[0]
        self.assertIn("foto, un audio o una nota", confirmation)

    async def test_find_card_sends_location_from_pinned_card(self):
        card = parking_card()
        # getChat omite reply_to_message dentro de pinned_message.
        card.reply_to_message = None
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_message=message,
            effective_chat=SimpleNamespace(id=1),
            effective_user=SimpleNamespace(id=2),
        )
        bot = SimpleNamespace(
            get_chat=AsyncMock(return_value=SimpleNamespace(pinned_message=card)),
            send_location=AsyncMock(),
        )

        await find_card(update, SimpleNamespace(bot=bot))

        bot.send_location.assert_awaited_once_with(
            chat_id=1, latitude=-34.9, longitude=-58.5, reply_markup=ANY
        )

    async def test_find_card_returns_saved_references(self):
        card = parking_card(reference_ids=[30, 31])
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_message=message,
            effective_chat=SimpleNamespace(id=1),
            effective_user=SimpleNamespace(id=2),
        )
        bot = SimpleNamespace(
            get_chat=AsyncMock(return_value=SimpleNamespace(pinned_message=card)),
            send_location=AsyncMock(),
            copy_message=AsyncMock(),
        )

        await find_card(update, SimpleNamespace(bot=bot))

        self.assertEqual(bot.copy_message.await_count, 2)
        copied_ids = [
            call.kwargs["message_id"]
            for call in bot.copy_message.await_args_list
        ]
        self.assertEqual(copied_ids, [30, 31])

    async def test_reference_button_returns_the_saved_message(self):
        card = parking_card(reference_ids=[30])
        query = SimpleNamespace(
            data="reference|30",
            message=card,
            answer=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=2),
            effective_message=card,
        )
        bot = SimpleNamespace(copy_message=AsyncMock())

        await button_callback(update, SimpleNamespace(bot=bot))

        bot.copy_message.assert_awaited_once_with(
            chat_id=1,
            from_chat_id=1,
            message_id=30,
        )

    async def test_close_from_active_menu_targets_pinned_card(self):
        card = parking_card()
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_message=message,
            effective_chat=SimpleNamespace(id=1),
            effective_user=SimpleNamespace(id=2),
        )
        bot = SimpleNamespace(
            get_chat=AsyncMock(return_value=SimpleNamespace(pinned_message=card)),
        )

        await request_close(update, SimpleNamespace(bot=bot))

        callback = (
            message.reply_text.await_args.kwargs["reply_markup"]
            .inline_keyboard[0][0]
            .callback_data
        )
        self.assertTrue(callback.endswith("|20"))

    async def test_close_unpins_the_card(self):
        card = parking_card()
        query = SimpleNamespace(
            data=location_callback("confirm_close", -34.9, -58.5),
            message=card,
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=2),
            effective_message=card,
        )
        bot = SimpleNamespace(
            unpin_chat_message=AsyncMock(),
            send_message=AsyncMock(),
        )

        await button_callback(update, SimpleNamespace(bot=bot))

        bot.unpin_chat_message.assert_awaited_once_with(chat_id=1, message_id=20)

    async def test_close_from_menu_closes_original_pinned_card(self):
        prompt = SimpleNamespace(
            chat_id=1,
            message_id=30,
            from_user=SimpleNamespace(is_bot=True),
            text="¿Confirmás que encontraste el auto?",
            reply_markup=None,
        )
        query = SimpleNamespace(
            data=location_callback("confirm_close", -34.9, -58.5, 20),
            message=prompt,
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
            delete_message=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=2),
            effective_message=prompt,
        )
        bot = SimpleNamespace(
            unpin_chat_message=AsyncMock(),
            edit_message_text=AsyncMock(),
            send_message=AsyncMock(),
        )

        await button_callback(update, SimpleNamespace(bot=bot))

        bot.unpin_chat_message.assert_awaited_once_with(chat_id=1, message_id=20)
        bot.edit_message_text.assert_awaited_once()
        query.delete_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
