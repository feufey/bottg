import decimal
import random
import requests
import xml.etree.ElementTree as ET



from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command, CommandStart, Text
from aiogram.types import CallbackQuery, ContentType, Message
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta
from collections import deque
import config
import games
import keyboards
import utils
from utils import m # То что спасет тысячи жизней
import utils_db
from loader import bot, cryptopay, dp
import logging
import aiosqlite
from aiogram.dispatcher.filters.state import StatesGroup, State
from aiogram import types
import asyncio
import time
import uuid
import json

logging.basicConfig(level=logging.DEBUG)

crush_range = [round(1 + i * 0.01, 2) for i in range(1, 900+1)]

async def handle_payment_error(user_id, user_name, amount, error_message):
    admin_message = f"Пользователю <a href='tg://user?id={user_id}'>{user_name}</a> [{user_id}] необходимо произвести ручной вывод средств в размере {amount} $ из-за ошибки: {error_message}"
    for admin_id in [config.ADMIN_ID, config.ADMIN_SD]:
        await bot.send_message(admin_id, admin_message)
    await bot.send_message(user_id, "❌ Произошла ошибка при попытке вывода средств. Администрация уже уведомлена. Перешлите это сообщение @cartsupo")

async def send_cash_with_error_handling(user_id, user_name, amount, transaction_id):
    try:
        await cryptopay.send_cash(user_id, amount, transaction_id)
    except Exception as e:
        logging.error(f"Error sending cash: {e}")
        await handle_payment_error(user_id, user_name, amount, str(e))


games_dict = {
    "чет": games.even_game, "нечет": games.odd_game,
    "больше": games.more_game, "меньше": games.less_game,
    "дартс мимо": games.darts_by, "дартс центр": games.darts_center,
    'дартс белое': games.darts_bellow, 'дартс красное': games.darts_red,
    'бумага': games.paper,
    'ножницы': games.scissors,
    'камень': games.stone,
    'центр': games.darts_center,
    'мимо': games.darts_by,
    'белое': games.darts_bellow,
    'плинко': games.plinko_game,
    'слоты': games.slots_game,
    "пвп": games.pvp_cube,
    'баскет гол': games.basket_game,
    'баскет мимо': games.basket_game,
    'баскетбол гол': games.basket_game,
    'баскетбол мимо': games.basket_game,
    'футбол гол': games.futbol_game,
    'футбол мимо': games.futbol_game,
    'фут гол': games.futbol_game,
    'фут мимо': games.futbol_game,
    'красное': games.rulet,
    'черное': games.rulet,
    'зеленое': games.rulet,
    'орел': games.coin_flip_game,
    'решка': games.coin_flip_game
    
}

async def get_usd_to_rub():
    try:
        response = requests.get('https://www.cbr.ru/scripts/XML_daily.asp')
        response.encoding = 'windows-1251'
        tree = ET.ElementTree(ET.fromstring(response.text))
        root = tree.getroot()

        for valute in root.findall('Valute'):
            char_code = valute.find('CharCode').text
            if char_code == 'USD':
                value = valute.find('Value').text
                return float(value.replace(',', '.'))
    except Exception as e:
        return config.OFFLINE_DOLLAR

async def calculate_winrate(user_id):
    # Получаем все ставки пользователя
    user_bets = [game for game in utils_db.get_gamses(user_id).execute()]

    if not user_bets:
        return 0

    # Вычисляем количество выигрышей
    wins = sum(1 for bet in user_bets if bet.status == 1)

    # Вычисляем винрейт
    winrate = (wins / len(user_bets)) * 100

    return round(winrate, 2)

@dp.callback_query_handler(lambda c: c.data == 'hidden_user')
async def process_callback(callback_query: CallbackQuery):
    with open('hidden_list.txt', 'r') as f:
        hidden_users = f.read().splitlines()

    if str(callback_query.from_user.id) in hidden_users:
        hidden_users.remove(str(callback_query.from_user.id))
        await bot.answer_callback_query(callback_query.id, "Ваш никнейм теперь будет виден при ставке.")
    else:
        hidden_users.append(str(callback_query.from_user.id))
        await bot.answer_callback_query(callback_query.id, "Ваш никнейм теперь будет скрыт при ставке.")

    with open('hidden_list.txt', 'w') as f:
        for user_id in hidden_users:
            f.write(user_id + '\n')
            


async def handle_bid(data: dict):
    try:
        true_name = data['name']
        # Если пользователь скрыт, замените его имя
        with open('hidden_list.txt', 'r') as f:
            hidden_users = f.read().splitlines()
        if str(data['user_id']) in hidden_users:
            data['name'] = 'Secret User'
    except Exception as e:
        logging.error(f"Error processing hidden users list: {e}")
        await bot.send_message(config.ERROR_CHAT_ID, f"Error processing hidden users list: {e}")

    if data['comment'] not in games_dict and "краш" != data['comment'].split()[0]:
        zalupf = float(m(data['bid']) * m(0.93))
        try:
            await send_cash_with_error_handling(data['user_id'], true_name, zalupf, random.randint(0, 100000000))
        except Exception as e:
            logging.error(f"Error sending cash: {e}")
            await bot.send_message(config.ERROR_CHAT_ID, f"Error sending cash: {e}")
        return await bot.send_message(
            config.CHANNEL_ID,
            "<b>[❌] Ошибка!\n\n"
            f"{data['name']} - вы забыли дописать <a href='https://t.me/+kryvyhComxQ2NDBi'>комментарий</a> к ставке.\n"
            "Был совершён возврат денежных средств. <code>Комиссия составляет: 7%.</code></b>",
            parse_mode='HTML'
        )

    user = utils_db.get_user(data["user_id"])

    if user is None:
        user = utils_db.create_user(data["user_id"])

    # Если в конфиге xamount_action = True, умножаем ставку игрока на 1.1
    if config.xamount_action:
        original_bid = float(m(data['bid']) * m(1.1))
        bid_message = f"<b>Сумма ставки {original_bid} $ (умножена на 1.1х)</b>"
    else:
        bid_message = f"<b>Сумма ставки {data['bid']} $</b>"

    game = utils_db.create_game(
        user,
        data['name'],
        data["bid"],
        data["comment"],
        0,
        datetime.now(),
        decimal.Decimal('0.00')
    )

    hide_cf = False
    spl = data['comment'].split()
    if spl[0] == "краш":
        if len(spl) != 2:
            zalupf = float(m(data['bid']) * m(0.93))
            try:
                await send_cash_with_error_handling(data['user_id'], true_name, zalupf, random.randint(0, 100000000))
            except Exception as e:
                logging.error(f"Error sending cash: {e}")
                await bot.send_message(config.ERROR_CHAT_ID, f"Error sending cash: {e}")
            return await bot.send_message(
                config.CHANNEL_ID,
                "<b>[❌] Ошибка!\n\n"
                f"{data['name']} - вы забыли дописать <a href='https://t.me/+kryvyhComxQ2NDBi'>комментарий</a> к ставке.\n"
                "Был совершён возврат денежных средств. <code>Комиссия составляет: 7%.</code></b>",
                parse_mode='HTML'
            )

        if not utils.is_float(spl[1]):
            zalupf = float(m(data['bid']) * m(0.93))
            try:
                await send_cash_with_error_handling(data['user_id'], true_name, zalupf, random.randint(0, 100000000))
            except Exception as e:
                logging.error(f"Error sending cash: {e}")
                await bot.send_message(config.ERROR_CHAT_ID, f"Error sending cash: {e}")
            return await bot.send_message(
                config.CHANNEL_ID,
                "<b>[❌] Ошибка!\n\n"
                f"{data['name']} - вы указали неверный коэффициент краша (пример: <blockquote>краш 1.2</blockquote>).\n"
                "Был совершён возврат денежных средств. <code>Комиссия составляет: 7%.</code></b>",
                parse_mode='HTML'
            )

        try:
            b = float(spl[1])
            if b not in crush_range or b < 1.2:
                zalupf = float(m(data['bid']) * m(0.93))
                try:
                    await send_cash_with_error_handling(data['user_id'], true_name, zalupf, random.randint(0, 100000000))
                except Exception as e:
                    logging.error(f"Error sending cash: {e}")
                    await bot.send_message(config.ERROR_CHAT_ID, f"Error sending cash: {e}")
                return await bot.send_message(
                    config.CHANNEL_ID,
                    "<b>[❌] Ошибка!\n\n"
                    f"{data['name']} - вы указали неверный коэффициент краша (пример: <blockquote>краш 1.2</blockquote>).\n"
                    "Был совершён возврат денежных средств. <code>Комиссия составляет: 7%.</code></b>",
                    parse_mode='HTML'
                )
            hide_cf = True
        except ValueError as e:
            logging.error(f"Error converting coefficient to float: {e}")
            await bot.send_message(config.ERROR_CHAT_ID, f"Error converting coefficient to float: {e}")
            zalupf = float(m(data['bid']) * m(0.93))
            try:
                await send_cash_with_error_handling(data['user_id'], true_name, zalupf, random.randint(0, 100000000))
            except Exception as e:
                logging.error(f"Error sending cash: {e}")
                await bot.send_message(config.ERROR_CHAT_ID, f"Error sending cash: {e}")
            return await bot.send_message(
                config.CHANNEL_ID,
                "<b>[❌] Ошибка!\n\n"
                f"{data['name']} - вы указали неверный коэффициент краша.\n"
                "Был совершён возврат денежных средств. <code>Комиссия составляет: 7%.</code></b>",
                parse_mode='HTML'
            )

        func = games.crush_game
    else:
        func = games_dict.get(data['comment'])

    try:
        with open('blur_list.txt', 'r') as f:
            blur_list = f.read().splitlines()
        for blur_word in blur_list:
            data['name'] = data['name'].replace(blur_word, "****")
    except Exception as e:
        logging.error(f"Error processing blur list: {e}")
        await bot.send_message(config.ERROR_CHAT_ID, f"Error processing blur list: {e}")

    winrate = await calculate_winrate(data['user_id'])
    if data['comment'] in ['2б', '2м', '2 больше', '2 меньше']:
        kef = config.kef
    elif data['comment'] in ['меньше', 'больше', 'плинко', 'чет', 'нечет']:
        kef = config.kefzalupa
    elif data['comment'] in ['бумага', 'камень', 'ножницы']:
        kef = config.kefsuefa
    elif data['comment'] in ['баскет гол', 'баскетбол гол', 'футбол мимо', 'фут мимо']:
        kef = config.kefzalupa
    elif data['comment'] in ['баскет мимо', 'баскетбол мимо', 'футбол гол', 'фут гол']:
        kef = config.kefbasket
    elif data['comment'] in ['красное', 'черное']:
        kef = 2
    elif data['comment'] in ['зеленое']:
        kef = 15
    else:
        kef = config.kef2

    coef_msg = f"<blockquote><b>Коэффициент {kef}x</b></blockquote>\n" if not hide_cf else ""

    await bot.send_message(
        config.CHANNEL_ID,
        f"<b>❤️‍🔥 Новая ставка от {data['name']}</b>\n\n"
        f"<blockquote>{bid_message}</blockquote>\n"
        f"<blockquote><b>Поставил на {data['comment']}</b></blockquote>\n"
        f"{coef_msg}"
    )

    try:
        result = await func(data)
        if not result[0]:
            return

        if user.referral_id and result[0] > 0 and result[0] > data['bid']:
            ref_user = user.referral_id
            ref_user.balance += m(result[0]) / m(25)
            ref_user.save()

            referral_earnings = round(float(m(result[0]) / m(25)), 2)
            await dp.bot.send_message(
                ref_user.user_id,
                f"<b>🎉 C реферала вы получаете <code>{referral_earnings}$</code></b>"
            )

            # Отправка уведомления администратору
            await bot.send_message(config.ERROR_CHAT_ID, f"Пользователь {ref_user.user_id} получил реферальное начисление {referral_earnings} $ от ставки пользователя {data['user_id']}")

        if 0 < result[0] < data['bid']:
            game.status = 2
            game.comission_profit = decimal.Decimal(data['bid']) * decimal.Decimal('0.07')
        elif result[0] >= data['bid']:
            game.status = 1
        game.save()

        if result[0] > 1:
            return await send_cash_with_error_handling(
                game.user_id,
                true_name,
                result[0],
                random.randint(0, 100000000)
            )
 
    except Exception as e:
        logging.error(f"Error processing game result: {e}")
        await bot.send_message(config.ERROR_CHAT_ID, f"Error processing game result: {e}")

@dp.message_handler(Command("topup"))
async def topup(msg: Message):
    try:
        sum = float(msg.text.split()[-1])
    except:
        return await msg.answer(
            "<b>❌ Введите корректную сумму!</b>"
        )
    
    invoice = await cryptopay.create_invoice(sum)

    await bot.send_message(
        msg.chat.id,
        invoice.bot_invoice_url
    )


# Словарь для хранения временных меток действий пользователей
user_actions = {}

# Максимальное количество действий в течение 10 секунд
max_actions = config.max_actions

@dp.message_handler(CommandStart())
async def start(msg: Message):
    user_id = msg.from_user.id
    referrer_id = int(msg.get_args()) if msg.get_args().isdigit() else None

    # Если пользователь уже есть в словаре, добавляем новую временную метку
    if user_id in user_actions:
        user_actions[user_id].append(time.time())
    else:
        # Если пользователя еще нет в словаре, создаем новый список с одной временной меткой
        user_actions[user_id] = [time.time()]

    # Удаляем все временные метки, которые старше 10 секунд
    user_actions[user_id] = [timestamp for timestamp in user_actions[user_id] if time.time() - timestamp < config.timeout]

    # Если количество действий превышает максимальное, отправляем сообщение об ошибке
    if len(user_actions[user_id]) > max_actions:
        await msg.answer(f"<b> Вы слишком часто взаимодействуете с ботом, подождите еще {time.time() - user_actions[user_id][0]:.2f} секунд </b>")
        return

    user = utils_db.get_user(msg.from_user.id)

    if not user:
        user = utils_db.create_user(msg.from_user.id, referrer_id)
        if referrer_id:
            await msg.answer(f"<b>👋 Добро пожаловать, {msg.from_user.mention}</b>\n\n"
                             f"Вы были приглашены пользователем с ID {referrer_id}.")
        else:
            await msg.answer(f"<b>👋 Добро пожаловать, {msg.from_user.mention}</b>\n\n"
                             "Канал со ставками - <a href='https://t.me/+pl-MTk-sIz0xNmFi'>тык</a>\n"
                             "Новостной канал - <a href='https://t.me/+zJ8rp4z5HNsyYTEy'>тык</a>")
    else:
        if not user.referral_id and referrer_id:
            user.referral_id = referrer_id
            user.save()
            await msg.answer(f"<b>Ваш реферал успешно установлен. ID реферала: {referrer_id}</b>")

    await msg.answer(f"<b>👋 Добро пожаловать, {msg.from_user.mention}</b>\n\n"
                     "Канал со ставками - <a href='https://t.me/+pl-MTk-sIz0xNmFi'>тык</a>\n"
                     "Новостной канал - <a href='https://t.me/+zJ8rp4z5HNsyYTEy'>тык</a>",
                     reply_markup=keyboards.user_markup)



@dp.message_handler(Text("⚡️ Профиль"))
async def profile(msg: Message):
    user_id = msg.from_user.id

    # Если пользователь уже есть в словаре, добавляем новую временную метку
    if user_id in user_actions:
        user_actions[user_id].append(time.time())
    else:
        # Если пользователя еще нет в словаре, создаем новый список с одной временной меткой
        user_actions[user_id] = [time.time()]

    # Удаляем все временные метки, которые старше 10 секунд
    user_actions[user_id] = [timestamp for timestamp in user_actions[user_id] if time.time() - timestamp < config.timeout]

    # Если количество действий превышает максимальное, отправляем сообщение об ошибке
    if len(user_actions[user_id]) > max_actions:
        await msg.answer(f"<b> Вы слишком часто взаимодействуете с ботом, подождите еще {time.time() - user_actions[user_id][0]:.2f} секунд </b>")
        return
    
    user = utils_db.get_user(msg.from_user.id)
    games = utils_db.get_user_games(msg.from_user.id) or []
    referrals = utils_db.get_referrals(msg.from_user.id) or []
    winrate = await calculate_winrate(user_id=msg.from_user.id)
    total_bets = sum(game.bid for game in games) or 0
    register_date = user.timestamp.strftime('%Y-%m-%d %H:%M')
    today_bets = 0
    today_games = 0
    photo_url = "https://i.postimg.cc/L6t7t6DW/vazimoff.png"
    print(winrate)
    await msg.answer_photo(
        photo_url,
        caption=f"<b>🎲 Профиль</b>\n"
                f"👉🏼 ID: <code>{msg.from_user.id}</code>\n"
                f"💰 Баланс: <code>{round(float(user.balance), 2)} $</code>\n\n"
                f"➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
                f"⚙️ Никнейм: <code>{msg.from_user.first_name}</code> |\n"
                f"🎮 Юзернейм: <code>@{msg.from_user.username}</code>\n\n"
                f"➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
                f"📊 Статистика:\n\n"
                f"💎 Винрейт: <code>{winrate:.2f}%</code>\n\n"
                f"💸 Ставки за всё время: <code>{round(total_bets,2)}</code> $ за <code>{len(games)}</code> игр.\n"
                f"📆 Дата регистрации: <code>{register_date}</code>",
        reply_markup=keyboards.profile_markup
    )



@dp.message_handler(Text("🔗 Реферальная система"))
async def referral_link(msg: Message):
    user_id = msg.from_user.id

    # Если пользователь уже есть в словаре, добавляем новую временную метку
    if user_id in user_actions:
        user_actions[user_id].append(time.time())
    else:
        # Если пользователя еще нет в словаре, создаем новый список с одной временной меткой
        user_actions[user_id] = [time.time()]

    # Удаляем все временные метки, которые старше 10 секунд
    user_actions[user_id] = [timestamp for timestamp in user_actions[user_id] if time.time() - timestamp < config.timeout]

    # Если количество действий превышает максимальное, отправляем сообщение об ошибке
    if len(user_actions[user_id]) > max_actions:
        await msg.answer(f"<b> Вы слишком часто взаимодействуете с ботом, подождите еще {time.time() - user_actions[user_id][0]:.2f} секунд </b>")
        return
    
    referrals = utils_db.get_referrals(msg.from_user.id)

    await msg.answer(
        "<b>🔗 Реферальная система\n\n"
        "💸 Вы получаете <code>5%</code> с выигрышей рефералов.\n"
        f"⭐️ Кол-во рефералов: <code>{referrals.count()} шт.</code>\n"
        f"⚡️ Ваша реферальная ссылка - https://t.me/{(await bot.get_me()).username}?start={msg.from_user.id}</b>",
        disable_web_page_preview=True
    )

async def get_total_bets():
    async with aiosqlite.connect('database.sqlite') as db:
        cursor = await db.execute("SELECT MAX(id) FROM game")
        total_bets = await cursor.fetchone()
        return total_bets[0] if total_bets else 0

@dp.message_handler(Text("💌 О нас"))
async def about_us(msg: Message):
    user_id = msg.from_user.id

    # Если пользователь уже есть в словаре, добавляем новую временную метку
    if user_id in user_actions:
        user_actions[user_id].append(time.time())
    else:
        # Если пользователя еще нет в словаре, создаем новый список с одной временной меткой
        user_actions[user_id] = [time.time()]

    # Удаляем все временные метки, которые старше 10 секунд
    user_actions[user_id] = [timestamp for timestamp in user_actions[user_id] if time.time() - timestamp < config.timeout]

    # Если количество действий превышает максимальное, отправляем сообщение об ошибке
    if len(user_actions[user_id]) > max_actions:
        await msg.answer(f"<b> Вы слишком часто взаимодействуете с ботом, подождите еще {time.time() - user_actions[user_id][0]:.2f} секунд </b>")
        return

    total_bets = 37000 + await get_total_bets()

    # Подсчитываем общую сумму выплат в долларах
    games = utils_db.get_games()
    total_payouts_usd = sum(game.bid for game in games if game.status == 1)

    # Получаем курс доллара к рублю
    usd_to_rub = await get_usd_to_rub()

    if usd_to_rub is None:
        await msg.answer("Не удалось получить текущий курс доллара. Пожалуйста, попробуйте позже.")
        return

    # Конвертируем общую сумму выплат в рубли
    total_payouts_rub = 18120000 + total_payouts_usd * usd_to_rub
    total_payouts_formatted = f"{total_payouts_rub:,.2f}".replace(',', ' ')

    total_bets_formatted = f"{total_bets:,}".replace(',', ' ')

    photo_url = "https://i.imgur.com/enOfF9u.jpeg"

    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("👤 Администратор", url="http://t.me/majorbelg"),
        InlineKeyboardButton("💬 Чат", url="https://t.me/+tP7rWORo0-9hODli"),
        InlineKeyboardButton("📰 Новостной канал", url="https://t.me/+zJ8rp4z5HNsyYTEy"),
        InlineKeyboardButton("🎲 Канал со ставками", url="https://t.me/+pl-MTk-sIz0xNmFi")
    )

    await msg.answer_photo(
        photo_url,
        caption="<b>📊 Статистика:</b>\n"
                f"💰 Всего ставок: <code>{total_bets_formatted} шт.</code>\n"
                f"💸 Всего выплат: <code>{total_payouts_formatted} ₽</code>",
        reply_markup=keyboard,
    )



@dp.callback_query_handler(Text("withdraw_money"))
async def withdraw_money(call: CallbackQuery):
    user = utils_db.get_user(call.from_user.id)
    
    # Проверка на минимальный баланс
    if float(user.balance) < config.min_vivod:
        await call.answer()
        return await call.message.answer(
            f"<b>❌ Минимальная сумма вывода - <code>{config.min_vivod} $</code></b>"
        )
    
    # Проверка на наличие блокировки
    if user.is_withdrawing:
        await call.answer("Ваш запрос на вывод уже обрабатывается.", show_alert=True)
        return
    
    # Устанавливаем блокировку
    user.is_withdrawing = True
    user.save()

    balance = user.balance

    try:
        invoice = await send_cash_with_error_handling(user.user_id, call.from_user.username, float(balance), str(uuid.uuid4()))
        withdrawal = utils_db.create_withdrawal(user.user_id, float(balance))
        user.balance = decimal.Decimal(0)
        user.save()
        await bot.send_message(
            config.VIPLAT_ID,
            f"<b> 💎 Новый вывод</b>\n"
            f"<b>├ 💰 Сумма: {balance} $</b>\n"
            f"<b>└ 😈 Пользователь: {call.from_user.username} </b>"
        )
        await call.message.answer(f"<b>Деньги были успешно выведены на ваш CryptoBot.</b>")
        await call.answer()
    except Exception as e:
        logging.error(f"Error during withdrawal: {e}")
        await call.message.answer(f"Произошла ошибка: {e}")
    finally:
        # Сбрасываем блокировку в любом случае
        user.is_withdrawing = False
        user.save()




@dp.callback_query_handler(Text(startswith="scam_"))
async def scam_bid(call: CallbackQuery):
    await bot.delete_message(
        call.message.chat.id,
        call.message.message_id
    )

    game: utils_db.Game = utils_db.get_game(int(call.data.split("_")[-1]))
    smile = config.knb.get(game.comment)


    # Если пользователь скрыт, замените его имя
    with open('hidden_list.txt', 'r') as f:
        hidden_users = f.read().splitlines()
    if str(game.user_id) in hidden_users:
        game.name = 'Secret User'
        
    await bot.send_message(
        config.CHANNEL_ID,
        f"<b>❤️‍🔥 Новая ставка от {game.name}</b>\n\n"
        f"<blockquote><b> Сумма ставки: {game.bid} $ </b> </blockquote>\n"
        f"<blockquote><b>Поставил на {game.comment}</b></blockquote>\n"
        f"<blockquote><b>Коэффициент {config.kefsuefa}x</b></blockquote>\n"
    )

    await bot.send_message(
        config.CHANNEL_ID,
        config.knb_values.get(game.comment)
    )
    asyncio.sleep(3)
    await bot.send_message(
        config.CHANNEL_ID,
        smile
    )

    await utils.lose_notify(
        f"Выпал {config.knb_smiles.get(smile)}.",
        "https://i.imgur.com/3fZLyX8.png", game.bid, game.user_id
    )


@dp.callback_query_handler(Text(startswith="access_"))
async def access_bid(call: CallbackQuery):
    await bot.delete_message(
        call.message.chat.id,
        call.message.message_id
    )

    game: utils_db.Game = utils_db.get_game(int(call.data.split("_")[-1]))
    smile = config.knb_win.get(game.comment)

    await bot.send_message(
        config.CHANNEL_ID,
        f"<b>❤️‍🔥 Новая ставка от {game.name}</b>\n\n"
        f"<blockquote>💸 Сумма ставки: <code>{game.bid} $</code></blockquote>\n"
        f"<blockquote><b>Поставил на {game.comment}</b></blockquote>\n"
        f"<blockquote><b>Коэффициент {config.kef}x</b></blockquote>\n",
        parse_mode="html"
    )

    await bot.send_message(
        config.CHANNEL_ID,
        config.knb_values.get(game.comment)
    )
    await bot.send_message(
        config.CHANNEL_ID,
        smile
    )

    await utils.win_notify(
        float(round(game.bid * 2., 2)),
        f"Выпал {config.knb_smiles.get(smile)}.",
        "https://i.imgur.com/2WHXfkP.png"
    )
    game.delete().execute()


@dp.message_handler(Command("admin"))
async def admin(msg: Message):
    if msg.from_user.id not in [config.ADMIN_ID, config.ADMIN_SD]:
        await msg.answer("У вас нет доступа к этой команде.")
        return

    # Статистика за все время
    games = utils_db.get_games()
    users = utils_db.get_all_users()
    users_today = users.select().where(utils_db.User.timestamp > datetime.now() - timedelta(days=1))
    users_week = users.select().where(utils_db.User.timestamp > datetime.now() - timedelta(days=7))
    wins = sum([x.bid for x in games.where(utils_db.Game.status == 1)]) * 1.7

    # Статистика за сегодня
    today_stats = utils_db.get_game_statistics("24h")

    # Статистика за неделю
    week_stats = utils_db.get_game_statistics("7d")

    wtinfo = utils_db.get_all_withdrawals()
    all_profit = sum([x.bid for x in games.where(utils_db.Game.status == 0)])
    all_cost = sum([x.bid for x in games.where(utils_db.Game.status == 1)])
    all_comission = float(m(sum([x.bid for x in games])) * m(0.027))
    all_comission_profit = utils_db.get_total_commission_profit()
    all_bids = sum([x.bid for x in games])

    await msg.answer(
        "<b>🚀 Админ панель</b>\n\n"
        "<b>📊 Общая статистика:</b>\n"
        f"Всего юзеров: <code>{len(users)} шт.</code>\n"
        f"Всего депов: <code>{len(games)} шт.</code>\n"
        f"Заработано: <code>{round(all_profit, 1)} $</code>\n"
        f"Потрачено: <code>{round(all_cost, 1)} $</code>\n"
        f"Комиссионный доход: <code>{round(all_comission_profit, 2)} $</code>\n"
        f"Комиссия CryptoBot: <code>{round(all_comission, 2)} $</code>\n"
        f"Общая сумма ставок: <code>{round(all_bids,2)} $</code>\n"
        f"Всего выводов: <code>{round(wtinfo, 2)} $</code>\n"
        f"Чистый доход: <code>{round(float(m(all_profit) - m(all_cost) - m(all_comission) - m(wtinfo)),2)} $</code>\n\n"
        "<b>📅 Статистика за сегодня:</b>\n"
        f"Сегодня зарегистрировалось: <code>{len(users_today)} шт.</code>\n"
        f"Количество игр: <code>{today_stats['total_games']} шт.</code>\n"
        f"Выигрыши: <code>{today_stats['wins']} шт.</code>\n"
        f"Проигрыши: <code>{today_stats['losses']} шт.</code>\n"
        f"Ничьи: <code>{today_stats['draws']} шт.</code>\n"  # Добавляем информацию о ничьих
        f"Комиссионный доход: <code>{today_stats['commission_profit']} $</code>\n"  # Добавляем комиссионный доход
        f"Общая сумма ставок: <code>{today_stats['total_bid']} $</code>\n"
        f"Прибыль: <code>{today_stats['total_profit']} $</code>\n"
        f"Затраты: <code>{today_stats['total_cost']} $</code>\n"
        f"Комиссия CryptoBot: <code>{round(today_stats['commission'], 2)} $</code>\n"
        f"Чистый доход: <code>{round(float(m(today_stats['commission_profit']) + m(today_stats['net_income']) - m(today_stats['commission']) - m(today_stats['total_withdrawn'])),2)} $</code>\n"  # Вычитаем комиссию из чистого дохода
        f"Изменение прибыльности: <code>{today_stats['profitability_change']:.2f}%</code>\n"
        f"Выводы: <code>{today_stats['total_withdrawn']} $</code>\n\n"  # Добавляем информацию о выводах
        "<b>📅 Статистика за неделю:</b>\n"
        f"На этой неделе зарегистрировалось: <code>{len(users_week)} шт.</code>\n"
        f"Количество игр: <code>{week_stats['total_games']} шт.</code>\n"
        f"Выигрыши: <code>{week_stats['wins']} шт.</code>\n"
        f"Проигрыши: <code>{week_stats['losses']} шт.</code>\n"
        f"Ничьи: <code>{week_stats['draws']} шт.</code>\n"  # Добавляем информацию о ничьих
        f"Комиссионный доход: <code>{week_stats['commission_profit']} $</code>\n"  # Добавляем комиссионный доход
        f"Общая сумма ставок: <code>{week_stats['total_bid']} $</code>\n"
        f"Прибыль: <code>{week_stats['total_profit']} $</code>\n"
        f"Затраты: <code>{week_stats['total_cost']} $</code>\n"
        f"Комиссия CryptoBot: <code>{round(week_stats['commission'], 2)} $</code>\n"
        f"Выводы с лк: <code>{round(float(wtinfo),2)} $</code>\n"
        f"Чистый доход: <code>{round(float(m(week_stats['commission_profit']) + m(week_stats['net_income']) - m(week_stats['commission']) - m(week_stats['total_withdrawn'])),2)} $</code>\n"  # Вычитаем комиссию из чистого дохода
        f"Изменение прибыльности: <code>{week_stats['profitability_change']:.2f}%</code>\n"
        f"Выводы: <code>{week_stats['total_withdrawn']} $</code>\n\n"  # Добавляем информацию о выводах
        f"Баланс казино: <code>{await cryptopay.balance()}</code> $\n\n"
        f'<b>📅 Техническая информация:</b>\n\n'
        f'{"├─ 🔥 Акция 1.1Х включена" if config.xamount_action else "├─ ❌ Акция 1.1Х выключена"}\n'
        f"├─ Скам-сумма: <code>{config.SCAM_SUM} $</code>\n"
        f"├─ Скам-процент колеса: <code>{config.SCAM_WHEEL} %</code>\n"
        f'├─ Тайм-аут антифлуда: <code>{config.timeout} сек.</code>\n'
        f'├─ Максимальное количество действий в течение {config.timeout} секунд: <code>{config.max_actions} шт.</code>',
        reply_markup=keyboards.admin_markup,
        parse_mode='HTML'
    )




@dp.message_handler(Command("set_invoice_link"))
async def set_invoice_link(msg: Message):
    if msg.from_user.id not in [config.ADMIN_ID, config.ADMIN_SD]:
        await msg.answer("У вас нет доступа к этой команде.")
        return

    new_link = msg.get_args().strip()
    if not new_link:
        await msg.answer("Неверное количество аргументов. Используйте /set_invoice_link 'new_link'")
        return

    config.INVOICE_LINK = new_link
    await msg.answer(f"Ссылка на инвойс успешно изменена на {new_link}")

@dp.message_handler(Command("add_blur"))
async def add_blur(msg: Message):
    if msg.from_user.id not in [config.ADMIN_ID, config.ADMIN_SD]:
        await msg.answer("У вас нет доступа к этой команде.")
        return

    username_to_blur = msg.get_args().strip()
    if not username_to_blur:
        await msg.answer("Неверное количество аргументов. Используйте /add_blur 'username'")
        return

    with open('blur_list.txt', 'a') as f:
        f.write(f"\n{username_to_blur}")

    await msg.answer(f"Никнейм {username_to_blur} добавлен в блюр-лист.")


@dp.message_handler(Command("setscamsum"))
async def set_scam_sum(msg: Message, command: Command):
    if msg.from_user.id not in [config.ADMIN_ID, config.ADMIN_SD]:
        await msg.answer("У вас нет доступа к этой команде.")
        return

    if command.args is None:
        await msg.answer("Неверное количество аргументов. Используйте /setscamsum 'new_scam_sum'")
        return

    command_args = command.args.split()
    if len(command_args) != 1:
        await msg.answer("Неверное количество аргументов. Используйте /setscamsum 'new_scam_sum'")
        return

    new_scam_sum = command_args[0]
    try:
        new_scam_sum = float(new_scam_sum)
    except ValueError:
        await msg.answer("Неверный формат аргументов. Используйте /setscamsum 'new_scam_sum'")
        return

    config.SCAM_SUM = new_scam_sum

    await msg.answer(f"Скам-сумма успешно обновлена до {new_scam_sum}")

@dp.message_handler(Command("scamwheel"))
async def scum_wheel(msg: Message, command: Command):
    if msg.from_user.id not in [config.ADMIN_ID, config.ADMIN_SD]:
        await msg.answer("У вас нет доступа к этой команде.")
        return

    if command.args is None:
        await msg.answer("Неверное количество аргументов. Используйте /scamwheel 'new_scam_percent'")
        return

    command_args = command.args.split()
    if len(command_args) != 1:
        await msg.answer("Неверное количество аргументов. Используйте /scamwheel 'new_scam_percent'")
        return

    new_scam_precent = command_args[0]

    if str(new_scam_precent).isdigit() == False:
        await msg.answer("Неверный тип аргрумента. Используйте /scamwheel 'new_scam_percent' (целое неотрицательное число)")
        return
    new_scam_precent = int(new_scam_precent)

    if new_scam_precent > 100:
        config.SCAM_WHEEL = 100
    else:
        config.SCAM_WHEEL = new_scam_precent

    await msg.answer(f"Скам-процент колеса успешно обновлен до {config.SCAM_WHEEL}%")


@dp.message_handler(Command("getstats"))
async def get_stats(msg: Message, command: Command):
    if msg.from_user.id not in [config.ADMIN_ID, config.ADMIN_SD]:
        await msg.answer("У вас нет доступа к этой команде.")
        return
    
    if command.args is None:
        await msg.answer("Неверное количество аргументов. Используйте /getstats 'time_period'")
        return

    command_args = command.args.split()
    if len(command_args) != 1:
        await msg.answer("Неверное количество аргументов. Используйте /getstats 'time_period'")
        return

    time_period = command_args[0]

    try:
        stats = utils_db.get_game_statistics(time_period)
    except ValueError as e:
        await msg.answer(str(e))
        return

    await msg.answer(
        f"<b>📊 Статистика за {time_period}:</b>\n"
        f"Количество игр: <code>{stats['total_games']} шт.</code>\n"
        f"Выигрыши: <code>{stats['wins']} шт.</code>\n"
        f"Проигрыши: <code>{stats['losses']} шт.</code>\n"
        f"Ничьи: <code>{stats['draws']} шт.</code>\n"  # Добавляем информацию о ничьих
        f"Комиссионный доход: <code>{stats['commission_profit']} $</code>\n"  # Добавляем комиссионный доход
        f"Общая сумма ставок: <code>{stats['total_bid']} $</code>\n"
        f"Прибыль: <code>{stats['total_profit']} $</code>\n"
        f"Затраты: <code>{stats['total_cost']} $</code>\n"
        f"Комиссия CryptoBot: <code>{round(stats['commission'], 2)} $</code>\n"
        f"Чистый доход: <code>{round(float(m(stats['commission_profit']) + m(stats['net_income']) - m(stats['commission']) - m(stats['total_withdrawn'])),2)} $</code>\n"  # Вычитаем комиссию из чистого дохода
        f"Изменение прибыльности: <code>{stats['profitability_change']:.2f}%</code>\n"
        f"Выводы: <code>{stats['total_withdrawn']} $</code>\n\n"  # Добавляем информацию о выводах
    )




@dp.message_handler(Command("sett"))
async def set_scam_sum(msg: Message, command: Command):
    if msg.from_user.id not in [config.ADMIN_ID, config.ADMIN_SD]:
        await msg.answer("У вас нет доступа к этой команде.")
        return

    if command.args is None:
        await msg.answer("Неверное количество аргументов. Используйте /sett 'timeout'")
        return

    command_args = command.args.split()
    if len(command_args) != 1:
        await msg.answer("Неверное количество аргументов. Используйте /sett 'timeout'")
        return

    new_timeout = command_args[0]
    try:
        new_timeout = float(new_timeout)
    except ValueError:
        await msg.answer("Неверный формат аргументов. Используйте /sett 'timeout'")
        return

    config.timeout = new_timeout

    await msg.answer(f"Тайм-аут антифлуда изменен на  {new_timeout}")

@dp.message_handler(Command("setbalance"))
async def set_balance(msg: Message, command: Command):
    if msg.from_user.id not in [config.ADMIN_ID, config.ADMIN_SD]:
        await msg.answer("У вас нет доступа к этой команде.")
        return
    
    if command.args is None:
        await msg.answer("Неверное количество аргументов. Используйте /setbalance 'user_id' 'new_balance'")
        return

    command_args = command.args.split()
    if len(command_args) != 2:
        await msg.answer("Неверное количество аргументов. Используйте /setbalance 'user_id' 'new_balance'")
        return

    user_id, new_balance = command_args
    try:
        user_id = int(user_id)
        new_balance = float(new_balance)
    except ValueError:
        await msg.answer("Неверный формат аргументов. Используйте /setbalance 'user_id' 'new_balance'")
        return

    user = utils_db.get_user(user_id)
    if user is None:
        await msg.answer(f"Пользователь с ID {user_id} не найден.")
        return

    user.balance = new_balance
    user.save()

    await msg.answer(f"Баланс пользователя с ID {user_id} успешно обновлен до {new_balance}")

@dp.callback_query_handler(text="promo_1x1")
async def promo_1x1(call: CallbackQuery):
    config.xamount_action = True
    await call.answer("Акция 1.1Х включена")
    await bot.send_photo(
        chat_id=config.NEWS_ID,
        photo="https://i.imgur.com/UV5wa0Z.jpeg",
        caption="<b> Уважаемые пользователи, включена акция 1.1Х.\n\nУспейте поставить и словить большой КЭФ </b>.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        "🎲 Сделать ставку",
                        url=f'{config.INVOICE_LINK}'
                    )
                ]
            ]
        ),
        parse_mode='HTML'
    )


@dp.message_handler(Command("1x1off"))
async def disable_xamount_action(msg: Message):
    if msg.from_user.id not in [config.ADMIN_ID, config.ADMIN_SD]:
        await msg.answer("У вас нет доступа к этой команде.")
        return

    config.xamount_action = False

    await msg.answer("1.1 оффнуто, блять.")
    
@dp.callback_query_handler(Text("cancel"), state="*")
async def cancel(call: CallbackQuery, state: FSMContext):
    await state.finish()
    await call.answer("❌ Отменено!")
    await call.message.delete()


@dp.callback_query_handler(Text("mailing"))
async def mailing_msg(call: CallbackQuery, state: FSMContext):
    await state.set_state("mailing")
    await call.message.answer(
        "<b>⚡️ Отправьте сообщение для рассылки</b>",
        reply_markup=keyboards.back_markup
    )


@dp.message_handler(content_types=[ContentType.ANY], state="mailing")
async def mailing(message: Message):
    await message.copy_to(
        message.from_user.id,
        reply_markup=keyboards.accept_mailing
    )


@dp.callback_query_handler(Text("start_mailing"), state="mailing")
async def accept_mail(call: CallbackQuery, state: FSMContext):
    start_time = datetime.now()
    await state.finish()

    error_count = 0

    msg = await call.message.answer(
        '<b>✅ Рассылка запущена</b>'
    )
    users = utils_db.get_all_users()

    for user in users:
        try:
            await call.message.copy_to(
                user.user_id, 
                reply_markup=keyboards.close_mailing
            )
        except:
            error_count += 1
            continue
    
    await msg.edit_text(
        "<b>🎉 Рассылка завершена!\n\n"
        f"✅ Успешно: <code>{len(users) - error_count} шт.</code>\n"
        f"❌ Ошибок: <code>{error_count} шт.</code>\n"
        f"⏳ Времени заняло: <code>{(datetime.now() - start_time).total_seconds():.2} c.</code></b>"
    )



        

@dp.callback_query_handler(Text("close_mailing"))
async def close_mailing(call: CallbackQuery):
    await call.message.delete()


async def send_chat_invite():
    while True:
        await asyncio.sleep(config.CHAT_MESSAGE_INTERVAL)  # Интервал в секундах

        # Отправка сообщения с фотографией и кнопкой
        await bot.send_photo(
            config.CHANNEL_ID,
            photo="https://azimoff.online/chatt.jpg",
            caption=f"Присоединяйтесь к нашему ламповому чату",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("💬 Чат", url=config.CHAT_LINK)
            )
        )

game_queue = deque()
processing_game = False


@dp.channel_post_handler(chat_id=config.CHANNEL_ID)
async def channel_post_handler(message: Message):
    try:
        data = utils.parse_data(message)
        if data and 'user_id' in data and 'bid' in data and 'comment' in data:
            utils_db.add_to_queue(data['user_id'], data)  # Добавляем данные в очередь
            await message.delete()
    except Exception as e:
        logging.error(f"Error parsing data: {e}")
        await bot.send_message(config.ERROR_CHAT_ID, f"Error parsing data: {e}")


async def process_game_queue():
    global processing_game
    while True:
        queue = utils_db.get_queue()
        if queue and not processing_game:
            processing_game = True
            for queue_item in queue:
                data = json.loads(queue_item.data)
                await handle_bid(data)
                utils_db.delete_from_queue(queue_item.id)
                await asyncio.sleep(7)  # Интервал между играми
            processing_game = False
        await asyncio.sleep(0.5)  # Интервал между проверкой очереди
if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(send_chat_invite())
    loop.create_task(process_game_queue())
    executor.start_polling(dp, skip_updates=True)
