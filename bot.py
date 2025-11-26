import asyncio
import io
import json
import csv
from datetime import datetime, date

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    BufferedInputFile,
)
from aiogram.enums import ParseMode
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from config import BOT_TOKEN
from db import (
    init_db,
    get_or_create_user,
    add_event,
    get_user_events,
    get_user_events_by_category,
    get_user_birthdays,
    get_user_birthdays_by_category,
    delete_event,
    get_events_to_notify,
    mark_notified,
    get_event_by_id,
    update_event_title,
    update_event_datetime_and_reset,
    update_event_remind_before,
)

SUPPORT_LINK = "https://t.me/dominov_mykhailo"


# ======================== КАТЕГОРІЇ ============================

CATEGORY_LABELS = {
    "family": "👨‍👩‍👧 Сім'я",
    "friends": "👥 Друзі",
    "work": "💼 Робота",
    "other": "📌 Інше",
}


# ======================== INLINE КЛАВІАТУРИ ============================

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Додати подію", callback_data="menu_add")],
            [InlineKeyboardButton(text="📋 Мої події", callback_data="menu_list")],
            [InlineKeyboardButton(text="🎂 Мої дні народження", callback_data="menu_birthdays")],
            [InlineKeyboardButton(text="✏️ Редагувати подію", callback_data="menu_edit")],
            [InlineKeyboardButton(text="🗑 Видалити подію", callback_data="menu_delete")],
            [InlineKeyboardButton(text="🆘 Допомога", url=SUPPORT_LINK)],
        ]
    )



def event_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎂 День народження", callback_data="type_birthday"),
                InlineKeyboardButton(text="📅 Зустріч", callback_data="type_meeting"),
            ],
            [InlineKeyboardButton(text="⭐ Інше", callback_data="type_other")],
        ]
    )


def category_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👨‍👩‍👧 Сім'я", callback_data="cat_family"),
                InlineKeyboardButton(text="👥 Друзі", callback_data="cat_friends"),
            ],
            [
                InlineKeyboardButton(text="💼 Робота", callback_data="cat_work"),
                InlineKeyboardButton(text="📌 Інше", callback_data="cat_other"),
            ],
        ]
    )


def list_filter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌀 Усі", callback_data="list_cat_all")],
            [InlineKeyboardButton(text="👨‍👩‍👧 Сім'я", callback_data="list_cat_family")],
            [InlineKeyboardButton(text="👥 Друзі", callback_data="list_cat_friends")],
            [InlineKeyboardButton(text="💼 Робота", callback_data="list_cat_work")],
            [InlineKeyboardButton(text="📌 Інше", callback_data="list_cat_other")],
        ]
    )


def bday_filter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌀 Усі ДР", callback_data="bday_cat_all")],
            [InlineKeyboardButton(text="👨‍👩‍👧 Сім'я", callback_data="bday_cat_family")],
            [InlineKeyboardButton(text="👥 Друзі", callback_data="bday_cat_friends")],
            [InlineKeyboardButton(text="💼 Робота", callback_data="bday_cat_work")],
            [InlineKeyboardButton(text="📌 Інше", callback_data="bday_cat_other")],
        ]
    )


def edit_fields_kb(event_type: str) -> InlineKeyboardMarkup:
    if event_type == "birthday":
        rows = [
            [InlineKeyboardButton(text="✏️ Назву", callback_data="editf_title")],
            [InlineKeyboardButton(text="📅 Дату народження", callback_data="editf_birthdate")],
            [InlineKeyboardButton(text="⏰ Час нагадувань", callback_data="editf_bday_time")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="✏️ Назву", callback_data="editf_title")],
            [InlineKeyboardButton(text="📅 Дату і час події", callback_data="editf_datetime")],
            [InlineKeyboardButton(text="⏰ За скільки хвилин нагадати", callback_data="editf_remind")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def export_format_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 CSV", callback_data="export_csv"),
                InlineKeyboardButton(text="🧾 JSON", callback_data="export_json"),
            ]
        ]
    )


# ======================== FSM ============================

class AddEvent(StatesGroup):
    type = State()
    title = State()
    category = State()
    datetime = State()
    birthday_time = State()
    remind = State()


class EditEvent(StatesGroup):
    choose_id = State()
    choose_field = State()
    new_value = State()


# ======================== ХЕЛПЕРИ ============================

def parse_datetime_full(text: str):
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def parse_birthdate(text: str):
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_time_str(text: str):
    try:
        return datetime.strptime(text.strip(), "%H:%M").time()
    except ValueError:
        return None


# ======================== /start та базові команди ============================

async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    get_or_create_user(message.from_user.id, message.from_user.username)

    await message.answer(
        "Привіт 👋\n\n"
        "Я бот-нагадувач.\n"
        "Допоможу не забути важливі події.\n\n"
        "Обери дію нижче:",
        reply_markup=main_menu_kb(),
    )


async def cmd_birthdays(message: Message, state: FSMContext):
    """Команда /birthdays — показати фільтри для ДР."""
    await message.answer(
        "Обери фільтр для днів народження:",
        reply_markup=bday_filter_kb(),
    )


async def cmd_export(message: Message, state: FSMContext):
    """Команда /export — вибір формату CSV/JSON."""
    await message.answer(
        "У якому форматі надіслати експорт твоїх подій? 🙂",
        reply_markup=export_format_kb(),
    )

async def cmd_help(message: Message, state: FSMContext):
    text = (
        "Якщо щось не працює, є питання або ідеї — "
        f"напиши мені в особисті: <a href=\"{SUPPORT_LINK}\">написати сюди</a> 💬\n\n"
        "Команди бота:\n"
        "/start — головне меню\n"
        "/birthdays — список днів народження\n"
        "/export — експорт усіх подій\n"
        "/help — ця підказка"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


# ======================== ДОДАВАННЯ ПОДІЇ ============================

async def menu_add_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AddEvent.type)
    await callback.message.answer(
        "Оберіть тип події:", reply_markup=event_type_kb()
    )


async def add_event_type_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    cb = callback.data

    type_map = {
        "type_birthday": "birthday",
        "type_meeting": "meeting",
        "type_other": "other",
    }
    if cb not in type_map:
        return

    event_type = type_map[cb]
    await state.update_data(type=event_type)
    await state.set_state(AddEvent.title)

    await callback.message.answer(
        "Введи назву події (наприклад: <b>Мама</b>, <b>Катя</b>, <b>Андрій</b>):",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )


async def add_event_title(message: Message, state: FSMContext):
    title = message.text.strip()
    if len(title) < 1:
        await message.answer("Назва надто коротка. Спробуй ще раз.")
        return

    await state.update_data(title=title)
    await state.set_state(AddEvent.category)

    await message.answer(
        "Обери категорію для цієї події:",
        reply_markup=category_kb(),
    )


async def add_event_category_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    cb = callback.data  # cat_family / cat_friends / cat_work / cat_other

    if not cb.startswith("cat_"):
        return

    category_key = cb.split("_", 1)[1]  # family / friends / work / other
    await state.update_data(category=category_key)

    data = await state.get_data()
    event_type = data["type"]

    await state.set_state(AddEvent.datetime)

    if event_type == "birthday":
        await callback.message.answer(
            "Введи дату народження у форматі <b>YYYY-MM-DD</b>\n"
            "Наприклад: <code>1999-05-10</code>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await callback.message.answer(
            "Введи дату і час події у форматі <b>YYYY-MM-DD HH:MM</b>\n"
            "Наприклад: <code>2025-11-22 18:00</code>",
            parse_mode=ParseMode.HTML,
        )


async def add_event_datetime(message: Message, state: FSMContext):
    data = await state.get_data()
    event_type = data["type"]

    # День народження
    if event_type == "birthday":
        bdate = parse_birthdate(message.text)
        if not bdate:
            await message.answer(
                "Невірний формат дати. Спробуй ще раз у форматі <code>1999-05-10</code>.",
                parse_mode=ParseMode.HTML,
            )
            return

        await state.update_data(birthdate=bdate)
        await state.set_state(AddEvent.birthday_time)

        await message.answer(
            "О котрій годині тобі зручно отримувати нагадування?\n"
            "Формат: <b>HH:MM</b> (наприклад <code>09:00</code> або <code>08:30</code>)",
            parse_mode=ParseMode.HTML,
        )
        return

    # Інші події
    dt = parse_datetime_full(message.text)
    if not dt:
        await message.answer(
            "Невірний формат. Спробуй ще раз у форматі <code>2025-11-22 18:00</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    if dt < datetime.now():
        await message.answer("Дата в минулому ⏳ Обери майбутню.")
        return

    await state.update_data(datetime=dt)
    await state.set_state(AddEvent.remind)

    await message.answer(
        "За скільки хвилин нагадати?\n"
        "0 — тільки в момент події\n"
        "60 — за годину до\n"
        "1440 — за день до",
        parse_mode=ParseMode.HTML,
    )


async def add_birthday_time(message: Message, state: FSMContext):
    t = parse_time_str(message.text)
    if not t:
        await message.answer(
            "Невірний формат часу. Спробуй у форматі <code>09:00</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    data = await state.get_data()
    birthdate = data["birthdate"]
    category = data["category"]

    today = date.today()
    year = today.year
    next_date = date(year, birthdate.month, birthdate.day)
    if next_date < today:
        next_date = date(year + 1, birthdate.month, birthdate.day)

    final_dt = datetime.combine(next_date, t)

    user_id = get_or_create_user(message.from_user.id, message.from_user.username)
    add_event(
        user_id=user_id,
        title=data["title"],
        type_="birthday",
        category=category,
        event_dt=final_dt,
        remind_before_minutes=0,
        repeat_yearly=True,
    )

    await state.clear()
    await message.answer(
        "🎉 День народження додано!\n\n"
        f"<b>{data['title']}</b>\n"
        f"Категорія: {CATEGORY_LABELS.get(category, '📌 Інше')}\n"
        f"Дата: {final_dt.strftime('%Y-%m-%d')} о {final_dt.strftime('%H:%M')}",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(),
    )


async def add_event_remind(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введи лише число (наприклад 0 або 60).")
        return

    minutes = int(message.text)
    if minutes < 0:
        await message.answer("Мінімальне значення — 0 хвилин.")
        return

    data = await state.get_data()
    user_id = get_or_create_user(message.from_user.id, message.from_user.username)

    add_event(
        user_id=user_id,
        title=data["title"],
        type_=data["type"],
        category=data["category"],
        event_dt=data["datetime"],
        repeat_yearly=False,
        remind_before_minutes=minutes,
    )

    await state.clear()
    await message.answer(
        "Подію додано ✅",
        reply_markup=main_menu_kb(),
    )


# ======================== СПИСКИ ПОДІЙ (З ФІЛЬТРАМИ) ============================

async def render_events(message: Message, events, header: str):
    if not events:
        await message.answer("Немає подій за цим фільтром.", reply_markup=main_menu_kb())
        return

    text = f"{header}\n\n"
    for idx, e in enumerate(events, start=1):
        dt = datetime.fromisoformat(e["event_datetime"])
        cat = e["category"] if e["category"] else "other"
        text += (
            f"{idx}) <b>{e['title']}</b>\n"
            f"ID: <code>{e['id']}</code>\n"
            f"{dt.strftime('%Y-%m-%d %H:%M')}\n"
            f"Тип: {e['type']}\n"
            f"Категорія: {CATEGORY_LABELS.get(cat, '📌 Інше')}\n\n"
        )

    text += "👉 Для редагування/видалення використовуй саме ID.\n"

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


async def render_birthdays(message: Message, events, header: str):
    if not events:
        await message.answer("Немає днів народження за цим фільтром 🎂", reply_markup=main_menu_kb())
        return

    text = f"{header}\n\n"
    for idx, e in enumerate(events, start=1):
        dt = datetime.fromisoformat(e["event_datetime"])
        cat = e["category"] if e["category"] else "other"
        text += (
            f"{idx}) <b>{e['title']}</b>\n"
            f"ID: <code>{e['id']}</code>\n"
            f"Наступна дата: {dt.strftime('%Y-%m-%d')} о {dt.strftime('%H:%M')}\n"
            f"Категорія: {CATEGORY_LABELS.get(cat, '📌 Інше')}\n\n"
        )

    text += "👉 Щоб відредагувати або видалити ДР — використовуй ID.\n"

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


async def menu_list_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Обери фільтр для подій:",
        reply_markup=list_filter_kb(),
    )


async def list_filter_callback(callback: CallbackQuery):
    await callback.answer()
    user_id = get_or_create_user(callback.from_user.id, callback.from_user.username)

    cb = callback.data  # list_cat_all / list_cat_family ...
    key = cb.split("_", 2)[2]  # all / family / friends / work / other

    if key == "all":
        events = get_user_events(user_id)
        header = "📋 <b>Список усіх подій:</b>"
    else:
        events = get_user_events_by_category(user_id, key)
        header = f"📋 <b>Події — {CATEGORY_LABELS.get(key, 'Категорія')}:</b>"

    await render_events(callback.message, events, header)


async def menu_birthdays_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Обери фільтр для днів народження:",
        reply_markup=bday_filter_kb(),
    )


async def birthdays_filter_callback(callback: CallbackQuery):
    await callback.answer()
    user_id = get_or_create_user(callback.from_user.id, callback.from_user.username)

    cb = callback.data  # bday_cat_all / bday_cat_family ...
    key = cb.split("_", 2)[2]  # all / family / friends / work / other

    if key == "all":
        events = get_user_birthdays(user_id)
        header = "🎂 <b>Усі дні народження:</b>"
    else:
        events = get_user_birthdays_by_category(user_id, key)
        header = f"🎂 <b>Дні народження — {CATEGORY_LABELS.get(key, 'Категорія')}:</b>"

    await render_birthdays(callback.message, events, header)


# ======================== EXPORT ============================

async def export_csv_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = get_or_create_user(callback.from_user.id, callback.from_user.username)
    events = get_user_events(user_id)

    if not events:
        await callback.message.answer(
            "У тебе поки немає подій для експорту.",
            reply_markup=main_menu_kb()
        )
        return

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "id",
        "title",
        "type",
        "category",
        "event_datetime",
        "remind_before_minutes",
        "repeat_yearly",
    ])

    for e in events:
        writer.writerow([
            e["id"],
            e["title"],
            e["type"],
            e["category"],
            e["event_datetime"],
            e["remind_before_minutes"],
            e["repeat_yearly"],
        ])

    csv_data = output.getvalue().encode("utf-8")
    output.close()

    file = BufferedInputFile(
        csv_data,
        filename=f"events_{user_id}.csv"
    )

    await callback.message.answer_document(
        document=file,
        caption="Ось твій експорт подій у форматі CSV 📄"
    )


async def export_json_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = get_or_create_user(callback.from_user.id, callback.from_user.username)
    events = get_user_events(user_id)

    if not events:
        await callback.message.answer(
            "У тебе поки немає подій для експорту.",
            reply_markup=main_menu_kb()
        )
        return

    data = []
    for e in events:
        data.append({
            "id": e["id"],
            "title": e["title"],
            "type": e["type"],
            "category": e["category"],
            "event_datetime": e["event_datetime"],
            "remind_before_minutes": e["remind_before_minutes"],
            "repeat_yearly": bool(e["repeat_yearly"]),
        })

    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    json_bytes = json_str.encode("utf-8")

    file = BufferedInputFile(
        json_bytes,
        filename=f"events_{user_id}.json"
    )

    await callback.message.answer_document(
        document=file,
        caption="Ось твій експорт подій у форматі JSON 🧾"
    )


# ======================== ВИДАЛЕННЯ ============================

async def menu_delete_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = get_or_create_user(callback.from_user.id, callback.from_user.username)
    events = get_user_events(user_id)

    if not events:
        await callback.message.answer("Немає подій для видалення.", reply_markup=main_menu_kb())
        return

    text = "Введи ID події для видалення:\n\n"
    for e in events:
        dt = datetime.fromisoformat(e["event_datetime"])
        text += f"ID {e['id']}: {e['title']} ({dt.strftime('%Y-%m-%d %H:%M')})\n"

    await state.set_state("delete_id")
    await callback.message.answer(text, reply_markup=ReplyKeyboardRemove())


async def delete_event_process(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введи числовий ID.")
        return

    event_id = int(message.text)
    user_id = get_or_create_user(message.from_user.id, message.from_user.username)

    ok = delete_event(user_id, event_id)
    await state.clear()

    if ok:
        await message.answer("Подію видалено ✅", reply_markup=main_menu_kb())
    else:
        await message.answer("Подію не знайдено ❌", reply_markup=main_menu_kb())


# ======================== РЕДАГУВАННЯ ============================

async def menu_edit_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = get_or_create_user(callback.from_user.id, callback.from_user.username)
    events = get_user_events(user_id)

    if not events:
        await callback.message.answer("Немає подій для редагування.", reply_markup=main_menu_kb())
        return

    text = "Введи ID події, яку хочеш змінити:\n\n"
    for e in events:
        dt = datetime.fromisoformat(e["event_datetime"])
        cat = e["category"] if e["category"] else "other"
        text += (
            f"ID {e['id']}: {e['title']} "
            f"({dt.strftime('%Y-%m-%d %H:%M')}, тип: {e['type']}, "
            f"категорія: {CATEGORY_LABELS.get(cat, '📌 Інше')})\n"
        )

    await state.set_state(EditEvent.choose_id)
    await callback.message.answer(text, reply_markup=ReplyKeyboardRemove())


async def edit_event_choose_id(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введи числовий ID події.")
        return

    event_id = int(message.text)
    user_id = get_or_create_user(message.from_user.id, message.from_user.username)
    row = get_event_by_id(user_id, event_id)

    if not row:
        await message.answer("Подію з таким ID не знайдено. Спробуй ще раз.")
        return

    event_type = row["type"]
    await state.update_data(edit_event_id=event_id, edit_event_type=event_type)
    await state.set_state(EditEvent.choose_field)

    dt = datetime.fromisoformat(row["event_datetime"])
    await message.answer(
        "Що хочеш змінити?\n\n"
        f"<b>{row['title']}</b>\n"
        f"{dt.strftime('%Y-%m-%d %H:%M')}\n"
        f"Тип: {event_type}",
        parse_mode=ParseMode.HTML,
        reply_markup=edit_fields_kb(event_type),
    )


async def edit_event_choose_field_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    event_type = data["edit_event_type"]
    cb = callback.data

    field = None
    prompt = None

    if event_type == "birthday":
        if cb == "editf_title":
            field = "title"
            prompt = "Введи нову назву:"
        elif cb == "editf_birthdate":
            field = "birthdate"
            prompt = (
                "Введи нову дату народження у форматі <b>YYYY-MM-DD</b>\n"
                "Наприклад: <code>1999-05-10</code>"
            )
        elif cb == "editf_bday_time":
            field = "bday_time"
            prompt = (
                "Введи новий час нагадувань у форматі <b>HH:MM</b>\n"
                "Наприклад: <code>09:00</code>"
            )
    else:
        if cb == "editf_title":
            field = "title"
            prompt = "Введи нову назву:"
        elif cb == "editf_datetime":
            field = "datetime"
            prompt = (
                "Введи нові дату і час у форматі <b>YYYY-MM-DD HH:MM</b>\n"
                "Наприклад: <code>2025-12-31 18:00</code>"
            )
        elif cb == "editf_remind":
            field = "remind"
            prompt = "Введи нове значення (кількість хвилин):"

    if not field:
        return

    await state.update_data(edit_field=field)
    await state.set_state(EditEvent.new_value)

    await callback.message.answer(
        prompt,
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )


async def edit_event_new_value(message: Message, state: FSMContext):
    data = await state.get_data()
    event_id = data["edit_event_id"]
    event_type = data["edit_event_type"]
    field = data["edit_field"]

    user_id = get_or_create_user(message.from_user.id, message.from_user.username)
    row = get_event_by_id(user_id, event_id)

    if not row:
        await state.clear()
        await message.answer(
            "Подію не знайдено. Можливо, її вже видалили.",
            reply_markup=main_menu_kb(),
        )
        return

    now = datetime.now()

    # Назва
    if field == "title":
        new_title = message.text.strip()
        if len(new_title) < 2:
            await message.answer("Назва надто коротка, спробуй ще раз.")
            return
        update_event_title(event_id, new_title)
        await state.clear()
        await message.answer("Назву оновлено ✅", reply_markup=main_menu_kb())
        return

    # Дні народження
    if event_type == "birthday":
        existing_dt = datetime.fromisoformat(row["event_datetime"])

        if field == "birthdate":
            bdate = parse_birthdate(message.text)
            if not bdate:
                await message.answer(
                    "Невірний формат. Має бути <code>1999-05-10</code>.",
                    parse_mode=ParseMode.HTML,
                )
                return

            today = date.today()
            year = today.year
            next_bday = date(year, bdate.month, bdate.day)
            if next_bday < today:
                next_bday = date(year + 1, bdate.month, bdate.day)

            new_dt = datetime.combine(next_bday, existing_dt.time())
            update_event_datetime_and_reset(event_id, new_dt, is_birthday=True)

            await state.clear()
            await message.answer("Дату народження оновлено ✅", reply_markup=main_menu_kb())
            return

        if field == "bday_time":
            t = parse_time_str(message.text)
            if not t:
                await message.answer(
                    "Невірний формат. Має бути <code>09:00</code>.",
                    parse_mode=ParseMode.HTML,
                )
                return

            new_dt = datetime.combine(existing_dt.date(), t)
            if new_dt < now:
                new_dt = new_dt.replace(year=new_dt.year + 1)

            update_event_datetime_and_reset(event_id, new_dt, is_birthday=True)

            await state.clear()
            await message.answer("Час нагадувань оновлено ✅", reply_markup=main_menu_kb())
            return

    # Інші події
    else:
        if field == "datetime":
            dt = parse_datetime_full(message.text)
            if not dt:
                await message.answer(
                    "Невірний формат. Має бути <code>2025-12-31 18:00</code>.",
                    parse_mode=ParseMode.HTML,
                )
                return
            if dt < now:
                await message.answer("Ця дата вже в минулому. Вкажи майбутню.")
                return

            update_event_datetime_and_reset(event_id, dt, is_birthday=False)
            await state.clear()
            await message.answer(
                "Дату й час події оновлено ✅",
                reply_markup=main_menu_kb(),
            )
            return

        if field == "remind":
            if not message.text.isdigit():
                await message.answer("Введи число хвилин (0, 60, 1440 тощо).")
                return
            minutes = int(message.text)
            if minutes < 0:
                await message.answer("Число не може бути від’ємним.")
                return

            update_event_remind_before(event_id, minutes)
            await state.clear()
            await message.answer(
                "Час нагадування оновлено ✅",
                reply_markup=main_menu_kb(),
            )
            return

    await state.clear()
    await message.answer("Зміни збережено ✅", reply_markup=main_menu_kb())


# ======================== Нагадувач ============================

async def reminder_loop(bot: Bot):
    while True:
        now = datetime.now()
        events = get_events_to_notify(now)

        for item in events:
            row = item["row"]
            kind = item["kind"]

            tg_id = row["tg_id"]
            title = row["title"]
            event_dt = datetime.fromisoformat(row["event_datetime"])
            repeat_yearly = bool(row["repeat_yearly"])
            event_type = row["type"]

            if event_type == "birthday":
                if kind == "30d":
                    text = f"🥳 За місяць день народження: <b>{title}</b>"
                elif kind == "7d":
                    text = f"🎉 За тиждень день народження: <b>{title}</b>"
                elif kind == "1d":
                    text = f"🎈 Вже завтра день народження: <b>{title}</b>"
                else:
                    text = f"🔥 Сьогодні день народження <b>{title}</b>!"
            else:
                if kind == "before":
                    text = (
                        f"⏰ Нагадування: <b>{title}</b>\n"
                        f"О {event_dt.strftime('%Y-%m-%d %H:%M')}"
                    )
                else:
                    text = (
                        f"🔥 Подія зараз: <b>{title}</b>\n"
                        f"{event_dt.strftime('%Y-%m-%d %H:%M')}"
                    )

            try:
                await bot.send_message(tg_id, text, parse_mode=ParseMode.HTML)
            except Exception as e:
                print(f"Помилка надсилання: {e}")

            mark_notified(row["id"], kind, repeat_yearly)

        await asyncio.sleep(60)


# ======================== Fallback ============================

async def fallback(message: Message):
    await message.answer("Оберіть дію з меню 👇", reply_markup=main_menu_kb())


# ======================== ROUTES / MAIN ============================

def setup_handlers(dp: Dispatcher):
    # Команди
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(cmd_birthdays, Command("birthdays"))
    dp.message.register(cmd_export, Command("export"))


    # Меню
    dp.callback_query.register(menu_add_callback, F.data == "menu_add")
    dp.callback_query.register(menu_list_callback, F.data == "menu_list")
    dp.callback_query.register(menu_birthdays_callback, F.data == "menu_birthdays")
    dp.callback_query.register(menu_edit_callback, F.data == "menu_edit")
    dp.callback_query.register(menu_delete_callback, F.data == "menu_delete")

    # Експорт
    dp.callback_query.register(export_csv_callback, F.data == "export_csv")
    dp.callback_query.register(export_json_callback, F.data == "export_json")

    # Вибір типу
    dp.callback_query.register(
        add_event_type_callback,
        F.data.in_(["type_birthday", "type_meeting", "type_other"]),
    )

    # Вибір категорії
    dp.callback_query.register(
        add_event_category_callback,
        F.data.in_(["cat_family", "cat_friends", "cat_work", "cat_other"]),
    )

    # Додавання події (FSM)
    dp.message.register(add_event_title, AddEvent.title)
    dp.message.register(add_event_datetime, AddEvent.datetime)
    dp.message.register(add_birthday_time, AddEvent.birthday_time)
    dp.message.register(add_event_remind, AddEvent.remind)

    # Фільтри списків
    dp.callback_query.register(list_filter_callback, F.data.startswith("list_cat_"))
    dp.callback_query.register(birthdays_filter_callback, F.data.startswith("bday_cat_"))

    # Редагування
    dp.message.register(edit_event_choose_id, EditEvent.choose_id)
    dp.callback_query.register(edit_event_choose_field_callback, F.data.startswith("editf_"))
    dp.message.register(edit_event_new_value, EditEvent.new_value)

    # Видалення
    dp.message.register(delete_event_process, F.state == "delete_id")

    # Усе інше
    dp.message.register(fallback)


async def main():
    init_db()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()

    setup_handlers(dp)

    asyncio.create_task(reminder_loop(bot))

    print("Bot started (background worker).")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
