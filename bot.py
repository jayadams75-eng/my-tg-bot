import os
import asyncio
import logging
import json
import html
from datetime import datetime
from aiohttp import web, ClientSession, ClientTimeout

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, BotCommand
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(level=logging.INFO)
# Чтобы самопинг не засорял логи строками "GET /"
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")

# Публичный адрес сервиса. На Render переменная RENDER_EXTERNAL_URL
# подставляется автоматически; можно переопределить через KEEPALIVE_URL.
KEEPALIVE_URL = (
    os.environ.get("KEEPALIVE_URL")
    or os.environ.get("RENDER_EXTERNAL_URL")
    or "https://my-tg-bot-0nhz.onrender.com"
)
KEEPALIVE_INTERVAL = int(os.environ.get("KEEPALIVE_INTERVAL", "300"))  # секунд

bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None

# SimpleEventIsolation не даёт обработать два нажатия одного пользователя одновременно
try:
    from aiogram.fsm.storage.memory import SimpleEventIsolation

    dp = Dispatcher(events_isolation=SimpleEventIsolation())
except (ImportError, TypeError):
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


# ─── ВСПОМОГАТЕЛЬНОЕ ────────────────────────────────────
async def mark_answered(cb: CallbackQuery, choice_text: str):
    """Убирает кнопки у отвеченного вопроса и дописывает выбранный ответ."""
    try:
        await cb.message.edit_text(
            f"{cb.message.html_text}\n\n✅ <b>Ваш ответ:</b> {html.escape(choice_text)}",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.warning(f"Не удалось отметить ответ в сообщении: {e}")
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


# ─── ЛОГИКА ОПРОСА ──────────────────────────────────────

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    await state.update_data(
        tg_username=f"@{user.username}" if user and user.username else "Нет юзернейма",
        tg_full_name=user.full_name if user else ""
    )
    await message.answer(
        "👋 Привет! Я бот-диагност для бизнеса.\n\n"
        "За 2 минуты разберем, что стопорит рост, и определим точки роста.\n\n"
        "📌 <b>1/4. Напишите Вашу нишу</b> (чем занимается Ваш бизнес?):",
        parse_mode="HTML"
    )
    await state.set_state(Diag.niche)


@dp.message(Diag.niche, F.text)
async def process_niche(message: Message, state: FSMContext):
    await state.update_data(niche=message.text)
    await message.answer(
        "📌 <b>2/4. Какие главные трудности Вы сейчас испытываете?</b>\n"
        "(напишите кратко, 1–3 предложения)",
        parse_mode="HTML"
    )
    await state.set_state(Diag.problems)


@dp.message(Diag.problems, F.text)
async def process_problems(message: Message, state: FSMContext):
    await state.update_data(problems=message.text)
    await message.answer(
        "📌 <b>3/4. Какой результат Вы хотите получить?</b>\n"
        "(например: «вырасти в 2 раза за 3 месяца»)",
        parse_mode="HTML"
    )
    await state.set_state(Diag.goal)


@dp.message(Diag.goal, F.text)
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

    await mark_answered(cb, team_str)
    await send_next_question(cb.from_user.id, state)


async def send_next_question(chat_id: int, state: FSMContext):
    data = await state.get_data()
    q_index = data.get("q_index", 0)
    branch = data.get("branch")

    questions = SOLO_QUESTIONS if branch == "solo" else TEAM_QUESTIONS

    # Если ответили на все вопросы -> ЗАВЕРШАЕМ
    if q_index >= len(questions):
        await finish_diagnostic(chat_id, state)
        return

    q_data = questions[q_index]

    text = f"<b>Вопрос {q_index + 1} из {len(questions)}:</b>\n"
    text += f"<b>{q_data['title']}</b>\n\n"

    kb = InlineKeyboardBuilder()

    for code, opt_text in q_data["options"].items():
        text += f"{opt_text}\n\n"
        letter = opt_text.split(".")[0]
        # В callback_data зашит номер вопроса: старые/повторные нажатия не собьют ответы
        kb.button(text=f"Вариант {letter}", callback_data=f"ans:{q_index}:{code}")

    kb.button(text="✏️ Свой вариант", callback_data=f"ans:{q_index}:custom")
    kb.adjust(2)  # По 2 кнопки в ряд

    await bot.send_message(chat_id, text, reply_markup=kb.as_markup(), parse_mode="HTML")


@dp.callback_query(
    StateFilter(Diag.answering_questions, Diag.waiting_custom_answer),
    F.data.startswith("ans:")
)
async def handle_answer(cb: CallbackQuery, state: FSMContext):
    try:
        _, idx_str, code = cb.data.split(":", 2)
        idx = int(idx_str)
    except ValueError:
        await cb.answer()
        return

    data = await state.get_data()
    q_index = data.get("q_index", 0)
    branch = data.get("branch")
    questions = SOLO_QUESTIONS if branch == "solo" else TEAM_QUESTIONS

    # Нажали кнопку от уже пройденного вопроса (повторный тап / старое сообщение)
    if idx != q_index or q_index >= len(questions):
        await cb.answer("Этот вопрос уже пройден.")
        return

    if code == "custom":
        await cb.answer()
        await bot.send_message(
            cb.from_user.id,
            "⌨️ <b>Напишите ваш вариант ответа текстом:</b>",
            parse_mode="HTML"
        )
        await state.set_state(Diag.waiting_custom_answer)
        return

    selected_text = questions[q_index]["options"].get(code)
    if selected_text is None:
        await cb.answer()
        return

    await cb.answer()

    answers = list(data.get("answers", []))
    answers.append(selected_text)

    await state.set_state(Diag.answering_questions)
    await state.update_data(answers=answers, q_index=q_index + 1)

    await mark_answered(cb, selected_text)
    await send_next_question(cb.from_user.id, state)


@dp.message(Diag.waiting_custom_answer, F.text)
async def process_custom_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    q_index = data.get("q_index", 0)
    answers = list(data.get("answers", []))
    answers.append(f"Свой вариант: {message.text}")

    await state.set_state(Diag.answering_questions)
    await state.update_data(answers=answers, q_index=q_index + 1)

    await send_next_question(message.chat.id, state)


# ─── ФИНАЛ ──────────────────────────────────────────────
async def finish_diagnostic(chat_id: int, state: FSMContext):
    data = await state.get_data()
    # Сразу очищаем состояние: повторное завершение невозможно
    await state.clear()

    user_info = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "username": data.get("tg_username", "Нет юзернейма"),
        "full_name": data.get("tg_full_name", "")
    }
    answers = data.get("answers", [])

    # 1. Уведомление АДМИНУ (HTML с экранированием; если не вышло — простой текст)
    if ADMIN_ID:
        fields = [
            ("👤", "Клиент", f"{user_info['full_name']} ({user_info['username']})"),
            ("🏷", "Ниша", data.get("niche")),
            ("❓", "Трудности", data.get("problems")),
            ("🎯", "Цель", data.get("goal")),
            ("👥", "Команда", data.get("team_size")),
        ]
        html_lines = ["🔥 <b>НОВАЯ ДИАГНОСТИКА В БОТЕ!</b>", "━━━━━━━━━━━━━━━━━━━━"]
        plain_lines = ["🔥 НОВАЯ ДИАГНОСТИКА В БОТЕ!", "━━━━━━━━━━━━━━━━━━━━"]
        for emoji, label, value in fields:
            value = str(value or "")
            html_lines.append(f"{emoji} <b>{label}:</b> {html.escape(value)}")
            plain_lines.append(f"{emoji} {label}: {value}")
        html_lines += ["", "📋 <b>ОТВЕТЫ:</b>"]
        plain_lines += ["", "📋 ОТВЕТЫ:"]
        for i, ans in enumerate(answers, 1):
            html_lines.append(f"<b>В{i}:</b> {html.escape(ans)}")
            plain_lines.append(f"В{i}: {ans}")

        html_msg = "\n".join(html_lines)
        plain_msg = "\n".join(plain_lines)

        try:
            if len(html_msg) > 4096:
                raise ValueError("сообщение длиннее лимита Telegram")
            await bot.send_message(chat_id=ADMIN_ID, text=html_msg, parse_mode="HTML")
        except Exception as e:
            logging.warning(f"HTML-уведомление админу не ушло ({e}), отправляю простым текстом")
            try:
                for i in range(0, len(plain_msg), 4000):
                    await bot.send_message(chat_id=ADMIN_ID, text=plain_msg[i:i + 4000])
            except Exception as e2:
                logging.error(f"Не удалось отправить сообщение админу: {e2}")

    # 2. Финальный текст КЛИЕНТУ
    final_text = (
        "Спасибо за ваши ответы! 🎉\n\n"
        "Я изучу их и напишу вам, на что стоит обратить внимание в первую очередь "
        "и какие моменты стоит разобрать подробнее, чтобы понять, почему нет желаемого результата."
    )
    await bot.send_message(chat_id, final_text)

    # 3. Запись в Google Sheets (ждём завершения, а не бросаем в фон,
    #    чтобы перезапуск процесса не оборвал запись)
    await asyncio.to_thread(save_to_google_sheets, data, user_info)


# ─── ЗАПАСНЫЕ ОБРАБОТЧИКИ (регистрируются последними!) ───
# Если бот перезапустился, состояние в памяти пропало: вместо молчания
# пользователь получает понятную подсказку.
@dp.callback_query()
async def stale_callback(cb: CallbackQuery):
    await cb.answer(
        "Эта кнопка уже неактивна (возможно, бот перезапускался). "
        "Нажмите /start, чтобы начать заново.",
        show_alert=True
    )


@dp.message()
async def fallback_message(message: Message, state: FSMContext):
    current = await state.get_state()
    text_states = (
        Diag.niche.state, Diag.problems.state, Diag.goal.state, Diag.waiting_custom_answer.state
    )
    if current in text_states:
        await message.answer("Пожалуйста, ответьте текстовым сообщением.")
    elif current == Diag.team_size.state:
        await message.answer("Выберите вариант кнопкой под вопросом. Чтобы начать заново — /start.")
    elif current == Diag.answering_questions.state:
        await message.answer(
            "Выберите вариант кнопкой под вопросом или нажмите «✏️ Свой вариант». "
            "Чтобы начать заново — /start."
        )
    else:
        await message.answer("Чтобы пройти диагностику, нажмите /start")


# ─── ВЕБ-СЕРВЕР ДЛЯ RENDER И САМОПИНГ ────────────────────
async def health(request):
    return web.Response(text="ok")


async def keep_alive():
    """Раз в KEEPALIVE_INTERVAL секунд обращается к собственному публичному адресу.
    Для Render это входящий трафик, поэтому бесплатный сервис не засыпает."""
    if not KEEPALIVE_URL:
        logging.info("Самопинг выключен: адрес сервиса не задан")
        return

    ok_logged = False
    await asyncio.sleep(60)
    async with ClientSession(timeout=ClientTimeout(total=20)) as session:
        while True:
            try:
                async with session.get(KEEPALIVE_URL) as resp:
                    if resp.status < 400:
                        if not ok_logged:
                            logging.info(f"✅ Самопинг работает ({KEEPALIVE_URL})")
                            ok_logged = True
                    else:
                        logging.warning(f"⚠️ Самопинг: ответ {resp.status}")
            except Exception as e:
                logging.warning(f"⚠️ Самопинг не удался: {e}")
            await asyncio.sleep(KEEPALIVE_INTERVAL)


async def main():
    if not BOT_TOKEN:
        logging.error("❌ BOT_TOKEN не найден!")
        return

    # 1. Веб-сервер (Render должен увидеть открытый порт)
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"✅ Сервер запущен на порту {port}")

    # 2. Кнопка меню
    try:
        await bot.set_my_commands([BotCommand(command="start", description="🚀 Начать сначала")])
        logging.info("✅ Кнопка Меню установлена")
    except Exception as e:
        logging.error(f"Ошибка установки команд: {e}")

    # 3. Самопинг, чтобы Render не усыплял сервис
    keepalive_task = asyncio.create_task(keep_alive())

    # 4. Polling. Штатная остановка (SIGTERM от Render) возвращает управление
    #    без ошибки; любая реальная ошибка — повторный запуск через 5 секунд.
    try:
        while True:
            try:
                logging.info("🚀 Запуск Polling...")
                await dp.start_polling(bot)
                break
            except Exception:
                logging.exception("❌ Ошибка polling, перезапуск через 5 секунд")
                await asyncio.sleep(5)
    finally:
        keepalive_task.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
