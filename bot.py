import os
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Включаем логирование, чтобы видеть ошибки в консоли Render
logging.basicConfig(level=logging.INFO)

# Получаем токен из переменных окружения
BOT_TOKEN = os.environ.get("BOT_TOKEN")

class Diag(StatesGroup):
    niche = State()
    problems = State()
    goal = State()
    leads = State()
    sales = State()
    content = State()
    funnel = State()

dp = Dispatcher()

# --- ТВОИ ХЕНДЛЕРЫ (логика бота) ---

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("👋 Привет! Я бот-диагност для бизнеса.\n\n📌 Напиши свою нишу:")
    await state.set_state(Diag.niche)

@dp.message(Diag.niche)
async def q1(message: Message, state: FSMContext):
    await state.update_data(niche=message.text)
    await message.answer("📌 Какие главные трудности сейчас?")
    await state.set_state(Diag.problems)

@dp.message(Diag.problems)
async def q2(message: Message, state: FSMContext):
    await state.update_data(problems=message.text)
    await message.answer("📌 Какой результат хочешь получить?")
    await state.set_state(Diag.goal)

@dp.message(Diag.goal)
async def q3(message: Message, state: FSMContext):
    await state.update_data(goal=message.text)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data="yes"), kb.button(text="❌ Нет", callback_data="no")
    await message.answer("📌 Устраивает количество заявок?", reply_markup=kb.as_markup())
    await state.set_state(Diag.leads)

@dp.callback_query(Diag.leads)
async def q4(cb: CallbackQuery, state: FSMContext):
    await state.update_data(leads=cb.data)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data="yes"), kb.button(text="❌ Нет", callback_data="no")
    await cb.message.edit_text("📌 Есть система продаж?", reply_markup=kb.as_markup())
    await state.set_state(Diag.sales)

@dp.callback_query(Diag.sales)
async def q5(cb: CallbackQuery, state: FSMContext):
    await state.update_data(sales=cb.data)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data="yes"), kb.button(text="❌ Нет", callback_data="no")
    await cb.message.edit_text("📌 Ведёшь соцсети регулярно?", reply_markup=kb.as_markup())
    await state.set_state(Diag.content)

@dp.callback_query(Diag.content)
async def q6(cb: CallbackQuery, state: FSMContext):
    await state.update_data(content=cb.data)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data="yes"), kb.button(text="❌ Нет", callback_data="no")
    await cb.message.edit_text("📌 Есть воронка?", reply_markup=kb.as_markup())
    await state.set_state(Diag.funnel)

@dp.callback_query(Diag.funnel)
async def q7(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await cb.message.edit_text("⏳ Анализирую...")
    await asyncio.sleep(1)
    # Упрощенный вывод для теста
    res = f"📊 Результат для ниши {data.get('niche')}:\nНужно больше воронки! Пиши @Malvitosa"
    await cb.message.answer(res)
    await state.clear()

# --- СЕРВЕРНАЯ ЧАСТЬ ДЛЯ RENDER ---

async def handle(request):
    return web.Response(text="Bot is running")

async def main():
    if not BOT_TOKEN:
        print("❌ ОШИБКА: BOT_TOKEN не найден в настройках Environment Variables!")
        return

    bot = Bot(token=BOT_TOKEN)
    
    # Создаем веб-сервер, чтобы Render был доволен
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Берем порт, который дает Render, или 8080 по умолчанию
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    print(f"✅ Сервер запущен на порту {port}")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Ошибка при запуске бота: {e}")

if __name__ == "__main__":
    asyncio.run(main())
