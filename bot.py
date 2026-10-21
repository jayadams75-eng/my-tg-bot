import os
import asyncio
import logging
import json
from datetime import datetime
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID")  # Ваш Telegram ID для уведомлений
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")  # Содержимое json файла

bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

class Diag(StatesGroup):
    niche = State()
    problems = State()
    goal = State()
    leads = State()
    sales = State()
    content = State()
    funnel = State()


# ─── ФУНКЦИЯ СОХРАНЕНИЯ В GOOGLE SHEETS ───
def save_to_google_sheets(data: dict, user_info: dict):
    if not GOOGLE_CREDS_JSON:
        logging.warning("⚠️ GOOGLE_CREDS_JSON не настроен. Данные не сохранены в таблицу.")
        return

    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        # Открываем таблицу с названием "Лиды Диагностика"
        sheet = client.open("Лиды Диагностика").sheet1
        
        row = [
            user_info.get("date"),
            user_info.get("username"),
            user_info.get("full_name"),
            data.get("niche", ""),
            data.get("problems", ""),
            data.get("goal", ""),
            "Да" if data.get("leads") == "yes" else "Нет",
            "Да" if data.get("sales") == "yes" else "Нет",
            "Да" if data.get("content") == "yes" else "Нет",
            "Да" if data.get("funnel") == "yes" else "Нет",
        ]
        sheet.append_row(row)
        logging.info("✅ Данные успешно сохранены в Google Sheets!")
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения в Google Sheets: {e}")


# ─── ХЕНДЛЕРЫ БОТА ───
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Привет! Я бот-диагност для бизнеса.\n\n"
        "За 2 минуты разберу, что стопорит рост, и дам план действий.\n\n"
        "📌 <b>Напиши свою нишу</b> (чем занимаешься?):",
        parse_mode="HTML"
    )
    await state.set_state(Diag.niche)

@dp.message(Diag.niche)
async def q1(message: Message, state: FSMContext):
    await state.update_data(niche=message.text)
    await message.answer("📌 <b>Какие главные трудности сейчас испытываешь?</b>\n(1-3 предложения)", parse_mode="HTML")
    await state.set_state(Diag.problems)

@dp.message(Diag.problems)
async def q2(message: Message, state: FSMContext):
    await state.update_data(problems=message.text)
    await message.answer("📌 <b>Какой результат хочешь получить?</b>\n(например: x3 к выручке за 3 месяца)", parse_mode="HTML")
    await state.set_state(Diag.goal)

@dp.message(Diag.goal)
async def q3(message: Message, state: FSMContext):
    await state.update_data(goal=message.text)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data="yes")
    kb.button(text="❌ Нет", callback_data="no")
    kb.adjust(2)
    await message.answer("📌 <b>Устраивает текущее количество заявок?</b>", reply_markup=kb.as_markup(), parse_mode="HTML")
    await state.set_state(Diag.leads)

@dp.callback_query(Diag.leads)
async def q4(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(leads=cb.data)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data="yes")
    kb.button(text="❌ Нет", callback_data="no")
    kb.adjust(2)
    await cb.message.edit_text("📌 <b>Есть выстроенная система продаж?</b> (CRM, скрипты)", reply_markup=kb.as_markup(), parse_mode="HTML")
    await state.set_state(Diag.sales)

@dp.callback_query(Diag.sales)
async def q5(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(sales=cb.data)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data="yes")
    kb.button(text="❌ Нет", callback_data="no")
    kb.adjust(2)
    await cb.message.edit_text("📌 <b>Ведёшь соцсети регулярно?</b> (3+ поста/сторис в неделю)", reply_markup=kb.as_markup(), parse_mode="HTML")
    await state.set_state(Diag.content)

@dp.callback_query(Diag.content)
async def q6(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(content=cb.data)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data="yes")
    kb.button(text="❌ Нет", callback_data="no")
    kb.adjust(2)
    await cb.message.edit_text("📌 <b>Есть ли автоворонка?</b> (лид-магнит → прогрев)", reply_markup=kb.as_markup(), parse_mode="HTML")
    await state.set_state(Diag.funnel)

@dp.callback_query(Diag.funnel)
async def q7(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(funnel=cb.data)
    data = await state.get_data()
    
    await cb.message.edit_text("⏳ Анализирую ответы...")

    # Информация о пользователе
    user = cb.from_user
    user_info = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "username": f"@{user.username}" if user.username else "Нет юзернейма",
        "full_name": user.full_name
    }

    # 1. Формируем диагноз пользователю
    result_text = make_diagnosis(data)
    
    # 2. Сохраняем в Google Таблицу (в отдельном потоке, чтобы бот не «зависал»)
    asyncio.create_task(asyncio.to_thread(save_to_google_sheets, data, user_info))

    # 3. Отправляем уведомление администратору (тебе)
    if ADMIN_ID:
        admin_msg = (
            f"🔥 <b>НОВЫЙ ЛИД ПРОШЁЛ ДИАГНОСТИКУ!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Клиент:</b> {user_info['full_name']} ({user_info['username']})\n"
            f"🏷 <b>Ниша:</b> {data.get('niche')}\n"
            f"❓ <b>Трудности:</b> {data.get('problems')}\n"
            f"🎯 <b>Цель:</b> {data.get('goal')}\n\n"
            f"📊 <b>Ответы:</b>\n"
            f"• Заявки устраивают: {data.get('leads')}\n"
            f"• Система продаж: {data.get('sales')}\n"
            f"• Регулярный контент: {data.get('content')}\n"
            f"• Воронка: {data.get('funnel')}\n"
        )
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Не удалось отправить уведомление админу: {e}")

    await asyncio.sleep(1)
    await cb.message.answer(result_text, parse_mode="HTML")
    await state.clear()


def make_diagnosis(d):
    issues, tips = [], []

    if d.get("leads") == "no":
        issues.append("🔴 <b>Мало входящих заявок</b>")
        tips.append("→ Запусти таргет + рилс-воронку для ежедневного трафика")
    else:
        issues.append("🟢 <b>Трафик</b> — заявки есть")

    if d.get("sales") == "no":
        issues.append("🔴 <b>Нет системы продаж</b> (слив лидов)")
        tips.append("→ Внедри CRM и скрипты продаж")
    else:
        issues.append("🟢 <b>Продажи</b> — система есть")

    if d.get("content") == "no":
        issues.append("🔴 <b>Нет регулярного контента</b>")
        tips.append("→ Составь контент-план + настрой прогревы")
    else:
        issues.append("🟢 <b>Контент</b> — выходите регулярно")

    if d.get("funnel") == "no":
        issues.append("🔴 <b>Нет автоворонки</b>")
        tips.append("→ Собери связку: Лид-магнит → Бот → Продажа")
    else:
        issues.append("🟢 <b>Воронка</b> — работает")

    reds = sum(1 for i in issues if "🔴" in i)
    verdict = "🏆 У тебя крепкая база! Время масштабироваться." if reds == 0 else \
              "⚠️ Есть 1-2 узких места, съедающих прибыль." if reds <= 2 else \
              "🚨 Системный сбой: бизнес работает на «ручнике»."

    return (
        f"📊 <b>РЕЗУЛЬТАТЫ ДИАГНОСТИКИ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷 Ниша: <i>{d.get('niche')}</i>\n"
        f"🎯 Цель: <i>{d.get('goal')}</i>\n\n"
        f"🔍 <b>Что стопорит бизнес:</b>\n" + "\n".join(issues) +
        f"\n\n🩺 <b>Вердикт:</b> {verdict}\n\n"
        f"📋 <b>План действий:</b>\n" + "\n".join(tips) +
        "\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 Хочешь разобрать это детально? "
        f"Напиши мне в личку — проведем разбор! 🎁"
    )

async def handle(request):
    return web.Response(text="Bot is active")

async def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не найден!")
        return
        
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    print(f"✅ Сервер открыт на порту {port}. Бот слушает Telegram...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
