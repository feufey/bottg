import re
from decimal import Decimal
import config
import decimal
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from loader import bot, cryptopay
import aiosqlite
import random
import hashlib
from datetime import datetime

m = lambda num: decimal.Decimal(f"{num}")

   
def is_float(s):
    if re.match("^\d+?\.\d+?$", s) is None:
        return s.isdigit()
    return True


async def get_user_balance(user_id):
    async with aiosqlite.connect('database.sqlite') as db:
        async with db.cursor() as cursor:
            await cursor.execute("SELECT balance FROM user WHERE user_id=?", (user_id,))
            result = await cursor.fetchone()
            return result[0] if result else None

async def update_user_balance(user_id, new_balance):
    async with aiosqlite.connect('database.sqlite') as db:
        async with db.cursor() as cursor:
            await cursor.execute("UPDATE user SET balance=? WHERE user_id=?", (new_balance, user_id))
            await db.commit()

async def lose_notify(msg: str, photo: str, zalupa : float, user_id: str):
    datatest = Decimal(zalupa)
    sobaka = datatest * Decimal('0.04')
    sobaka_str = str(sobaka.quantize(Decimal('0.00')))  # Форматируем число так, чтобы оно всегда имело два знака после запятой

    current_time = datetime.now().isoformat()
    hash_input = f"{user_id}{zalupa}{current_time}".encode('utf-8')
    hash_object = hashlib.sha256(hash_input)
    hash_hex = hash_object.hexdigest()
    
    # Получаем текущий баланс пользователя
    current_balance = await get_user_balance(user_id)
    # Если баланс равен None, устанавливаем его равным 0
    if current_balance is None:
        current_balance = '0'
    # Вычисляем новый баланс, добавляя кэшбек
    new_balance = Decimal(current_balance) + sobaka
    # Обновляем баланс пользователя
    await update_user_balance(user_id, str(new_balance))

    return await bot.send_photo(
    config.CHANNEL_ID,
    photo,
    f"<b>Вы проиграли.</b>\n\n"
    "<blockquote>"
    "Попытай свою удачу снова!\nЖелаю удачи в следующих ставках!"
    "</blockquote>\n\n"
    f"<b>• Вам начислен кэшбек {sobaka_str} $ на баланс бота.</b>\n\n"
    f"Хэш игры: <code> {hash_hex} </code>\n\n"
    f'<a href="{config.FAQ_LINK}">Как сделать ставку?</a> | '
    f'<a href="{config.SUPPORT_LINK}">Тех. поддержка</a> | '
    f'<a href="{config.RULES_LINK}">Правила</a> | '
    f'<a href="{config.NEWS_LINK}">Новостной канал</a>',
    reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                "⚡️ Сделать ставку",
                config.INVOICE_LINK
            )],
        ]
    )
)


async def win_notify(sum: float, msg: str, photo: str):
    sum = round(sum, 2)
    # Генерация хэша
    hash_input = f"{sum}{msg}".encode('utf-8')
    hash_object = hashlib.sha256(hash_input)
    hash_hex = hash_object.hexdigest()
    return await bot.send_photo(
        config.CHANNEL_ID,
        photo,
        f"<b>Победа! {msg}\n\n"
        "<blockquote>"
        f"На ваш баланс был зачислен выигрыш {sum} $.\n"
        "Опробуйте свою удачу сполна и познайте путь истинных победителей по жизни!"
        "</blockquote>\n\n"
        f"Хэш игры: <code> {hash_hex} </code>\n\n"
        f'<a href="{config.FAQ_LINK}">Как сделать ставку?</a> |'
        f'<a href="{config.SUPPORT_LINK}">Тех. поддержка</a> | '
        f'<a href="{config.NEWS_LINK}">Новостной канал</a></b>',
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    "⚡️ Сделать ставку",
                    config.INVOICE_LINK
                )],
            ]
        )
    )

async def nic_notify(msg: str, photo: str, bid: float, user_id: str):
    bids = Decimal(bid)
    bidchlen = round(bid * 0.93, 2)
    current_time = datetime.now().isoformat()
    hash_input = f"{user_id}{msg}{current_time}".encode('utf-8')
    hash_object = hashlib.sha256(hash_input)
    hash_hex = hash_object.hexdigest()
    return await bot.send_photo(
        config.CHANNEL_ID,
        photo,
        f"<b>Ничья!\n\n"
        "<blockquote>"
        f"На ваш баланс CryptoBot были возвращены {bidchlen} $ (комиссия 7%) \n"
        "Опробуйте свою удачу сполна и познайте путь истинных победителей по жизни!"
        "</blockquote>\n\n"
        f"Хэш игры: <code> {hash_hex} </code>\n\n"
        f'<a href="{config.FAQ_LINK}">Как сделать ставку?</a> |'
        f'<a href="{config.SUPPORT_LINK}">Тех. поддержка</a> | '
        f'<a href="{config.NEWS_LINK}">Новостной канал</a></b>',
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    "⚡️ Сделать ставку",
                    config.INVOICE_LINK
                )],
            ]
        )
    )

async def draw_notify(msg: str, photo: str):
    return await bot.send_photo(
        config.CHANNEL_ID,
        photo,
        f"<b>Ничья! Ставка возвращена на баланс.</b>\n"
        f'<a href="{config.FAQ_LINK}">Как сделать ставку?</a> |'
        f'<a href="{config.SUPPORT_LINK}">Тех. поддержка</a> | '
        f'<a href="{config.RULES_LINK}">Правила</a> | '
        f'<a href="{config.NEWS_LINK}">Новостной канал</a>',
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    "⚡️ Сделать ставку",
                    config.INVOICE_LINK
                )],
            ]
        )
    )


def parse_data(msg: Message) -> dict[str, int | str]:
    try:
        user_id = msg.entities[0].user.id
        name = msg.entities[0].user.first_name
        bid_text = re.search(r'\(\$(.*?)\)', msg.text.split('\n')[0].split()[-1])
        bid = float(bid_text.group(1)) if bid_text else 0.0
        comment = ' '.join(msg.text.split('\n')[-1].split()[1::]).lower()
        
        return {
            "user_id": user_id,
            "name": name,
            "bid": bid,
            "comment": comment
        }
    except (AttributeError, IndexError, ValueError):
        return {}


async def notify_bid(data: dict, game):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton(
            "✅ Одобрить",
            callback_data=f"access_{game.id}"
        ),
        InlineKeyboardButton(
            "😈 Скамнуться",
            callback_data=f"scam_{game.id}"
        )
    )

    await bot.send_message(
        config.ADMIN_ID,
        f"<b>Ник: {data['name']}\n"
        f"Сумма скама: {data['bid']} $</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )
