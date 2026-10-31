import os
import asyncio
import logging
import json
from datetime import datetime
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, BotCommand
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")

bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()


# ─── СОСТОЯНИЯ (FSM) ────────────────────────────────────
class Diag(StatesGroup):
    niche = State()
    problems = State()
    goal = State()
    team_size = State()
    answering_questions = State()
    waiting_custom_answer = State()


# ─── БАЗА ВОПРОСОВ ──────────────────────────────────────

# 1. Для тех, кто работает ОДИН (из картинок)
SOLO_QUESTIONS = [
    {
        "title": "1. Откуда сейчас приходят клиенты?",
        "options": {
            "opt_a": "А. В основном по рекомендациям и через знакомых.",
            "opt_b": "Б. Из соцсетей, рекламы или других каналов.",
            "opt_c": "В. Стабильного источника нет — клиенты приходят от случая к случаю."
        }
    },
    {
        "title": "2. Регулярно ли Вы публикуете рабочий контент в соцсетях?",
        "options": {
            "opt_a": "А. Да, у меня есть определённый график.",
            "opt_b": "Б. Нет, публикую, когда есть время и идеи.",
            "opt_c": "В. Часто надолго пропадаю из соцсетей, хотя понимаю, что нужно вести их активнее."
        }
    },
    {
        "title": "3. Устраивает ли Вас то, что вы публикуете?",
        "options": {
            "opt_a": "А. Да, мне нравится мой контент, и я понимаю, зачем его публикую.",
            "opt_b": "Б. Не совсем: не хватает идей, разнообразия или понимания, о чём рассказывать.",
            "opt_c": "В. Нет, публикую скорее потому, что надо, но не понимаю, помогает ли это продавать."
        }
    },
    {
        "title": "4. Устраивает ли Вас количество заявок от потенциальных клиентов?",
        "options": {
            "opt_a": "А. Да, обращений достаточно.",
            "opt_b": "Б. Нет, заявок мало, хотя я регулярно что-то делаю для продвижения.",
            "opt_c": "В. Количество заявок постоянно скачет: то есть обращения, то тишина."
        }
    },
    {
        "title": "5. Устраивает ли Вас количество клиентов, которые в итоге покупают?",
        "options": {
            "opt_a": "А. Да, большинство обращений заканчиваются продажей.",
            "opt_b": "Б. Нет, многие интересуются, но до покупки не доходят.",
            "opt_c": "В. Сложно сказать: я не отслеживаю, сколько обращений превращается в продажи."
        }
    },
    {
        "title": "6. Как Вам кажется, почему потенциальные клиенты не покупают?",
        "options": {
            "opt_a": "А. Им дорого, они сравнивают с конкурентами или просят скидку.",
            "opt_b": "Б. Не видят разницы между мной и другими специалистами и не понимают, почему стоит выбрать меня.",
            "opt_c": "В. Не знаю. Люди интересуются, задают вопросы, а потом пропадают."
        }
    },
    {
        "title": "7. Что Вы делаете, если клиент отвечает «я подумаю» или «дорого»?",
        "options": {
            "opt_a": "А. Уточняю, что именно его смущает, и продолжаю диалог.",
            "opt_b": "Б. Отвечаю на возражение, объясняю стоимость или предлагаю другой вариант.",
            "opt_c": "В. Обычно ничего — не хочу давить, поэтому жду, пока клиент сам вернётся."
        }
    }
]

# 2. Для тех, у кого есть КОМАНДА (из вашего текста)
TEAM_QUESTIONS = [
    {
        "title": "1. Что сейчас больше всего беспокоит в работе бизнеса?",
        "options": {
            "opt_a": "А. Я всё ещё вовлечён(а) почти во все процессы, без меня многое останавливается.",
            "opt_b": "Б. Команда занята, задач много, но результат не соответствует усилиям.",
            "opt_c": "В. Клиенты есть, но выручка почти не растёт.",
            "opt_d": "Г. Заявки приходят, но часть клиентов не покупает.",
            "opt_e": "Д. Бизнес работает стабильно, но я чувствую, что мы могли бы зарабатывать больше.",
            "opt_f": "Е. Не понимаю, где именно бизнес теряет деньги и возможности."
        }
    },
    {
        "title": "2. Насколько Вы можете отойти от операционной работы?",
        "options": {
            "opt_a": "А. Практически не могу: без меня возникают проблемы.",
            "opt_b": "Б. Могу отойти на несколько дней, но потом приходится разбирать накопившиеся вопросы.",
            "opt_c": "В. Команда справляется с текущими задачами, но стратегические решения остаются за мной.",
            "opt_d": "Г. Могу надолго отойти от операционки, процессы работают без моего постоянного участия."
        }
    },
    {
        "title": "3. Насколько Вас устраивает работа команды?",
        "options": {
            "opt_a": "А. Многие задачи приходится переделывать или контролировать лично.",
            "opt_b": "Б. Каждый отвечает за свою работу, но между сотрудниками регулярно возникают сбои.",
            "opt_c": "В. Команда работает самостоятельно, но я не всегда понимаю, кто и за какой результат отвечает.",
            "opt_d": "Г. Команда выполняет задачи и достигает целей, но потенциал сотрудников используется не полностью.",
            "opt_e": "Д. Работой команды в целом доволен(на)."
        }
    },
    {
        "title": "4. Понимаете ли Вы, какие действия приводят к росту выручки?",
        "options": {
            "opt_a": "А. Нет чёткого понимания, откуда приходят клиенты и что влияет на продажи.",
            "opt_b": "Б. Понимаю, какие каналы приводят клиентов, но не знаю, какие из них выгоднее.",
            "opt_c": "В. Знаю, откуда приходят клиенты, но не понимаю, на каком этапе теряется часть продаж.",
            "opt_d": "Г. Понимаю основные источники выручки и отслеживаю результаты.",
            "opt_e": "Д. Аналитика есть, но она не всегда помогает принимать решения о дальнейшем росте."
        }
    },
    {
        "title": "5. Что происходит с заявками, которые получает бизнес?",
        "options": {
            "opt_a": "А. Не знаю, сколько заявок в итоге превращается в продажи.",
            "opt_b": "Б. Заявки обрабатываются не всегда вовремя, часть клиентов теряется.",
            "opt_c": "В. Заявки обрабатывают, но конверсия в покупку меня не устраивает.",
            "opt_d": "Г. Основная проблема не в новых заявках, а в повторных продажах и среднем чеке.",
            "opt_e": "Д. С продажами всё в порядке, но текущего объёма клиентов недостаточно для желаемого роста.",
            "opt_f": "Е. Все этапы отслеживаются, конверсия меня устраивает."
        }
    },
    {
        "title": "6. Как Вы понимаете, где бизнес мог бы зарабатывать больше?",
        "options": {
            "opt_a": "А. Ориентируюсь в основном на общую выручку и остаток денег.",
            "opt_b": "Б. Знаю основные расходы, но не всегда понимаю прибыльность отдельных направлений или продуктов.",
            "opt_c": "В. Вижу, что ресурсы расходуются неэффективно, но пока не понимаю, где именно.",
            "opt_d": "Г. Есть идеи для роста, но не хватает времени или ресурсов на их реализацию.",
            "opt_e": "Д. Понимаю экономику бизнеса и основные точки роста, но пока не получается реализовать их в полной мере.",
            "opt_f": "Е. Регулярно анализирую прибыльность и принимаю решения на основе данных."
        }
    },
    {
        "title": "7. Если бы Вы могли изменить одну вещь в бизнесе в ближайшие полгода, что бы выбрали?",
        "options": {
            "opt_a": "А. Сделать так, чтобы команда работала самостоятельно, а я перестал(а) быть узким местом.",
            "opt_b": "Б. Повысить эффективность команды без постоянного увеличения затрат.",
            "opt_c": "В. Увеличить поток целевых заявок и привлечь больше подходящих клиентов.",
            "opt_d": "Г. Повысить конверсию в продажу, средний чек и повторные покупки.",
            "opt_e": "Д. Найти скрытые точки роста и увеличить прибыль без хаотичного расширения бизнеса.",
            "opt_f": "Е. Выстроить понятную систему управления, в которой решения принимаются на основе цифр, а не предположений."
        }
    }
]


# ─── СОХРАНЕНИЕ В GOOGLE SHEETS ─────────────────────────
def save_to_google_sheets(data: dict, user_info: dict):
    if not GOOGLE_CREDS_JSON:
        logging.warning("⚠️ GOOGLE_CREDS_JSON не настроен!")
        return

    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        sheet = client.open("Лиды Диагностика").sheet1
        
        answers = data.get("answers", [])
        
        row = [
            user_info.get("date"),
            user_info.get("username"),
            user_info.get("full_name"),
            data.get("niche", ""),
            data.get("problems", ""),
            data.get("goal", ""),
            data.get("team_size", ""),
            answers[0] if len(answers) > 0 else "",
            answers[1] if len(answers) > 1 else "",
            answers[2] if len(answers) > 2 else "",
            answers[3] if len(answers) > 3 else "",
            answers[4] if len(answers) > 4 else "",
            answers[5] if len(answers) > 5 else "",
            answers[6] if len(answers) > 6 else ""
        ]
        sheet.append_row(row)
        logging.info("✅ Данные сохранены в Таблицу!")
    except Exception as e:
        logging.error(f"❌ Ошибка записи в Таблицу: {e}")


# ─── ЛОГИКА ОПРОСА ──────────────────────────────────────

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Привет! Я бот-диагност для бизнеса.\n\n"
        "За 2 минуты разберем, что стопорит рост, и определим точки роста.\n\n"
        "📌 <b>1/4. Напишите Вашу нишу</b> (чем занимается Ваш бизнес?):",
        parse_mode="HTML"
    )
    await state.set_state(Diag.niche)


@dp.message(Diag.niche)
async def process_niche(message: Message, state: FSMContext):
    await state.update_data(niche=message.text)
    await message.answer(
        "📌 <b>2/4. Какие главные трудности Вы сейчас испытываете?</b>\n"
        "(напишите кратко, 1–3 предложения)",
        parse_mode="HTML"
    )
    await state.set_state(Diag.problems)


@dp.message(Diag.problems)
async def process_problems(message: Message, state: FSMContext):
    await state.update_data(problems=message.text)
    await message.answer(
        "📌 <b>3/4. Какой результат Вы хотите получить?</b>\n"
        "(например: «вырасти в 2 раза за 3 месяца»)",
        parse_mode="HTML"
    )
    await state.set_state(Diag.goal)


@dp.message(Diag.goal)
async def process_goal(message: Message, state: FSMContext):
    await state.update_data(goal=message.text)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Работаю один", callback_data="team_solo")
    kb.button(text="👥 2-6 человек", callback_data="team_small")
    kb.button(text="🏢 Больше 10 человек", callback_data="team_big")
    kb.adjust(1)

    await message.answer(
        "📌 <b>4/4. Сколько человек в вашей команде?</b>",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(Diag.team_size)


@dp.callback_query(Diag.team_size, F.data.startswith("team_"))
async def process_team_size(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    
    choice = cb.data
    if choice == "team_solo":
        team_str = "Работаю один"
        branch = "solo"
    elif choice == "team_small":
        team_str = "2-6 человек"
        branch = "team"
    else:
        team_str = "Больше 10 человек"
        branch = "team"

    await state.update_data(team_size=team_str, branch=branch, q_index=0, answers=[])
    await state.set_state(Diag.answering_questions)
    
    await send_next_question(cb.message, state)


async def send_next_question(message: Message, state: FSMContext):
    data = await state.get_data()
    q_index = data.get("q_index", 0)
    branch = data.get("branch")
    
    questions = SOLO_QUESTIONS if branch == "solo" else TEAM_QUESTIONS
    
    # Если ответили на все 7 вопросов -> ЗАВЕРШАЕМ
    if q_index >= len(questions):
        await finish_diagnostic(message, state, user_object=message.chat)
        return

    q_data = questions[q_index]
    
    # Формируем текст сообщения
    text = f"<b>Вопрос {q_index + 1} из 7:</b>\n"
    text += f"<b>{q_data['title']}</b>\n\n"
    
    kb = InlineKeyboardBuilder()
    
    # Добавляем варианты в текст и создаем кнопки
    for code, opt_text in q_data["options"].items():
        text += f"{opt_text}\n\n"
        # Буква кнопки (А, Б, В...)
        letter = opt_text.split(".")[0]
        kb.button(text=f"Вариант {letter}", callback_data=f"ans_{code}")
        
    kb.button(text="✏️ Свой вариант", callback_data="ans_custom")
    kb.adjust(2)  # По 2 кнопки в ряд

    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@dp.callback_query(Diag.answering_questions, F.data.startswith("ans_"))
async def handle_answer(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    code = cb.data.replace("ans_", "")
    
    if code == "custom":
        await cb.message.answer("⌨️ <b>Напишите ваш вариант ответа текстом:</b>", parse_mode="HTML")
        await state.set_state(Diag.waiting_custom_answer)
        return

    data = await state.get_data()
    q_index = data.get("q_index", 0)
    branch = data.get("branch")
    questions = SOLO_QUESTIONS if branch == "solo" else TEAM_QUESTIONS
    
    selected_text = questions[q_index]["options"].get(code, "Выбран вариант")
    
    answers = data.get("answers", [])
    answers.append(selected_text)
    
    await state.update_data(answers=answers, q_index=q_index + 1)
    await send_next_question(cb.message, state)


@dp.message(Diag.waiting_custom_answer)
async def process_custom_answer(message: Message, state: FSMContext):
    custom_text = f"Свой вариант: {message.text}"
    
    data = await state.get_data()
    q_index = data.get("q_index", 0)
    answers = data.get("answers", [])
    answers.append(custom_text)
    
    await state.update_data(answers=answers, q_index=q_index + 1)
    await state.set_state(Diag.answering_questions)
    
    await send_next_question(message, state)


# ─── ФИНАЛ ──────────────────────────────────────────────
async def finish_diagnostic(message: Message, state: FSMContext, user_object=None):
    data = await state.get_data()
    
    # ПРАВИЛЬНЫЙ СПОСОБ: 
    # Если мы пришли из колбэка, берем информацию о чате (это и есть юзер)
    user = user_object if user_object else message.from_user
    
    user_info = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "username": f"@{user.username}" if user.username else "Нет юзернейма",
        "full_name": user.full_name if hasattr(user, 'full_name') else f"{user.first_name} {user.last_name or ''}"
    }

    # 1. Запись в Google Sheets
    asyncio.create_task(asyncio.to_thread(save_to_google_sheets, data, user_info))

    # 2. Уведомление АДМИНУ
    if ADMIN_ID:
        answers_str = ""
        for i, ans in enumerate(data.get("answers", []), 1):
            answers_str += f"<b>В{i}:</b> {ans}\n"

        admin_msg = (
            f"🔥 <b>НОВАЯ ДИАГНОСТИКА В БОТЕ!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Клиент:</b> {user_info['full_name']} ({user_info['username']})\n"
            f"🏷 <b>Ниша:</b> {data.get('niche')}\n"
            f"❓ <b>Трудности:</b> {data.get('problems')}\n"
            f"🎯 <b>Цель:</b> {data.get('goal')}\n"
            f"👥 <b>Команда:</b> {data.get('team_size')}\n\n"
            f"📋 <b>ОТВЕТЫ:</b>\n{answers_str}"
        )
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение админу: {e}")

    # 3. Финальный текст КЛИЕНТУ
    final_text = (
        "Спасибо за ваши ответы! 🎉\n\n"
        "Я изучу их и напишу вам, на что стоит обратить внимание в первую очередь "
        "и какие моменты стоит разобрать подробнее, чтобы понять, почему нет желаемого результата."
    )
    
    await message.answer(final_text)
    await state.clear()


# ─── ВЕБ-СЕРВЕР DUMMY ДЛЯ RENDER ─────────────────────────
async def handle(request):
    return web.Response(text="Bot is running")

async def setup_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="🚀 Перезапустить бота / Начать сначала")
    ]
    await bot.set_my_commands(commands)

async def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не найден!")
        return

    # Устанавливаем синюю кнопку «Меню» внизу
    await setup_bot_commands(bot)

    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    print(f"✅ Сервер запущен на порту {port}. Бот работает!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
