import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ══════════════════════════════════════════════
# ВСТАВЬ СВОЙ ТОКЕН СЮДА (между кавычками):
BOT_TOKEN = "8654279425:AAFhm3JVMp2b1mIXHWyWwmAHW3hndMaTodI"
# ══════════════════════════════════════════════

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


class Diag(StatesGroup):
    niche = State()
    problems = State()
    goal = State()
    leads = State()
    sales = State()
    content = State()
    funnel = State()


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Привет! Я бот-диагност для бизнеса.\n\n"
        "За 2 минуты разберу, что стопорит рост, "
        "и дам план действий.\n\n"
        "📌 Напиши свою нишу (чем занимаешься?):"
    )
    await state.set_state(Diag.niche)


@dp.message(Diag.niche)
async def q1(message: Message, state: FSMContext):
    await state.update_data(niche=message.text)
    await message.answer(
        "✅ Ок!\n\n"
        "📌 Какие главные трудности сейчас?\n"
        "(напиши 1-3 предложения)"
    )
    await state.set_state(Diag.problems)


@dp.message(Diag.problems)
async def q2(message: Message, state: FSMContext):
    await state.update_data(problems=message.text)
    await message.answer(
        "✅ Понял!\n\n"
        "📌 Какой результат хочешь получить?\n"
        "(например: x3 к выручке за 3 месяца)"
    )
    await state.set_state(Diag.goal)


@dp.message(Diag.goal)
async def q3(message: Message, state: FSMContext):
    await state.update_data(goal=message.text)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data="yes")
    kb.button(text="❌ Нет", callback_data="no")
    kb.adjust(2)
    await message.answer(
        "Финальные вопросы — жми кнопку 👇\n\n"
        "📌 Устраивает текущее количество заявок?",
        reply_markup=kb.as_markup()
    )
    await state.set_state(Diag.leads)


@dp.callback_query(Diag.leads, F.data.in_({"yes", "no"}))
async def q4(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(leads=cb.data)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data="yes")
    kb.button(text="❌ Нет", callback_data="no")
    kb.adjust(2)
    await cb.message.edit_text(
        "📌 Есть система продаж? (скрипты, CRM)",
        reply_markup=kb.as_markup()
    )
    await state.set_state(Diag.sales)


@dp.callback_query(Diag.sales, F.data.in_({"yes", "no"}))
async def q5(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(sales=cb.data)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data="yes")
    kb.button(text="❌ Нет", callback_data="no")
    kb.adjust(2)
    await cb.message.edit_text(
        "📌 Ведёшь соцсети регулярно? (3+ поста в неделю)",
        reply_markup=kb.as_markup()
    )
    await state.set_state(Diag.content)


@dp.callback_query(Diag.content, F.data.in_({"yes", "no"}))
async def q6(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(content=cb.data)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data="yes")
    kb.button(text="❌ Нет", callback_data="no")
    kb.adjust(2)
    await cb.message.edit_text(
        "📌 Есть воронка? (лид-магнит → прогрев → продажа)",
        reply_markup=kb.as_markup()
    )
    await state.set_state(Diag.funnel)


@dp.callback_query(Diag.funnel, F.data.in_({"yes", "no"}))
async def q7(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(funnel=cb.data)
    data = await state.get_data()
    result = make_diagnosis(data)
    await cb.message.edit_text("⏳ Анализирую...")
    await asyncio.sleep(2)
    await cb.message.answer(result)
    await state.clear()


def make_diagnosis(d):
    issues = []
    tips = []

    if d.get("leads") == "no":
        issues.append("🔴 Мало заявок")
        tips.append("→ Запусти таргет + рилс-воронку")
    else:
        issues.append("🟢 Заявки — ок")

    if d.get("sales") == "no":
        issues.append("🔴 Нет системы продаж")
        tips.append("→ Внедри CRM + скрипты")
    else:
        issues.append("🟢 Продажи — ок")

    if d.get("content") == "no":
        issues.append("🔴 Нет регулярного контента")
        tips.append("→ Контент-план + автопостинг")
    else:
        issues.append("🟢 Контент — ок")

    if d.get("funnel") == "no":
        issues.append("🔴 Нет воронки")
        tips.append("→ Собери автоворонку в боте")
    else:
        issues.append("🟢 Воронка — ок")

    reds = sum(1 for i in issues if "🔴" in i)
    if reds == 0:
        verdict = "🏆 Крепкая база! Масштабируй."
    elif reds <= 2:
        verdict = "⚠️ 1-2 узких места съедают прибыль."
    else:
        verdict = "🚨 Бизнес на ручнике. Нужна система."

    return (
        f"📊 РЕЗУЛЬТАТЫ ДИАГНОСТИКИ\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷 Ниша: {d.get('niche')}\n"
        f"🎯 Цель: {d.get('goal')}\n\n"
        f"🔍 Что стопорит:\n" +
        "\n".join(issues) +
        f"\n\n🩺 Вердикт: {verdict}\n\n"
        f"📋 План действий:\n" +
        "\n".join(tips) +
        "\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 Хочешь разобрать детально? "
        f"Пиши @your_username"
    )


async def main():
    print("✅ Бот запущен! Не закрывай это окно.")
    await dp.start_polling(bot)

asyncio.run(main())
