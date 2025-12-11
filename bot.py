import asyncio
import io
import json
import csv
import re
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

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
    # якщо раптом немає ParseMode/StatesGroup/FSMContext — перевір, що aiogram 3.x
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
    delete_event_by_id,
    get_user_timezone,
    set_user_timezone,
)

# ======================== TZ + НАЛАШТУВАННЯ ============================

DEFAULT_TZ = "Europe/Tallinn"
UTC = ZoneInfo("UTC")

SUPPORT_LINK = "https://t.me/mykhailodominov"   # заміни на свій @username


def get_tzinfo_for_user(user_id: int) -> ZoneInfo:
    tz_str = get_user_timezone(user_id) or DEFAULT_TZ
    try:
        return ZoneInfo(tz_str)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def local_to_utc(dt_local: datetime, tz: ZoneInfo) -> datetime:
    """
    Отримує локальний datetime (naive) + tz → повертає UTC (naive),
    який ми і зберігаємо в БД.
    """
    return dt_local.replace(tzinfo=tz).astimezone(UTC).replace(tzinfo=None)


def utc_to_local(dt_utc: datetime, tz: ZoneInfo) -> datetime:
    """
    Отримує UTC (naive) → повертає локальний datetime (naive) у заданій TZ.
    """
    return dt_utc.replace(tzinfo=UTC).astimezone(tz).replace(tzinfo=None)


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
            [InlineKeyboardButton(text="🌍 Часовий пояс", callback_data="menu_tz")],
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


def build_preset_datetime_kb(user_tz: ZoneInfo) -> InlineKeyboardMarkup:
    """
    Міні-календар на 7 днів з готовими слотами 09:00 / 18:00,
    але в callback_data вже лежить час у UTC.
    """
    now_local = datetime.now(user_tz)
    today = now_local.date()

    buttons = []
    for i in range(7):
        d: date = today + timedelta(days=i)
        if i == 0:
            day_label = "Сьогодні"
        elif i == 1:
            day_label = "Завтра"
        else:
            day_label = d.strftime("%d.%m")

        for t_str in ("09:00", "18:00"):
            hh, mm = map(int, t_str.split(":"))
            dt_local = datetime(d.year, d.month, d.day, hh, mm)
            dt_utc = local_to_utc(dt_local, user_tz)
            dt_str = dt_utc.isoformat()

            text = f"{day_label} {t_str}"
            buttons.append(
                InlineKeyboardButton(
                    text=text,
                    callback_data=f"preset_dt:{dt_str}",
                )
            )

    rows = []
    for i in range(0, len(buttons), 2):
        rows.append(buttons[i:i + 2])

    rows.append(
        [InlineKeyboardButton(text="⌨️ Ввести дату і час вручну", callback_data="preset_dt_manual")]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def remind_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Без нагадування (0)", callback_data="remind_preset:0")],
            [
                InlineKeyboardButton(text="За 1 годину (60)", callback_data="remind_preset:60"),
                InlineKeyboardButton(text="За день (1440)", callback_data="remind_preset:1440"),
            ],
        ]
    )


def confirm_date_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Так", callback_data="bday_date_ok"),
                InlineKeyboardButton(text="🔁 Ввести ще раз", callback_data="bday_date_retry"),
            ]
        ]
    )


def confirm_time_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Так", callback_data="bday_time_ok"),
                InlineKeyboardButton(text="🔁 Ввести ще раз", callback_data="bday_time_retry"),
            ]
        ]
    )


def timezone_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇪🇪 Europe/Tallinn", callback_data="tz:Europe/Tallinn"),
                InlineKeyboardButton(text="🇺🇦 Europe/Kyiv", callback_data="tz:Europe/Kyiv"),
            ],
            [
                InlineKeyboardButton(text="🇵🇱 Europe/Warsaw", callback_data="tz:Europe/Warsaw"),
                InlineKeyboardButton(text="🇩🇪 Europe/Berlin", callback_data="tz:Europe/Berlin"),
            ],
            [
                InlineKeyboardButton(text="🇬🇧 Europe/London", callback_data="tz:Europe/London"),
            ],
            [
                InlineKeyboardButton(text="⌨️ Інший (ввести вручну)", callback_data="tz:manual"),
            ],
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


class DeleteEvent(StatesGroup):
    choose_id = State()


class SetTimezone(StatesGroup):
    waiting = State()


# ======================== ХЕЛПЕРИ ПАРСИНГУ ============================

def parse_datetime_full(text: str):
    raw = text.strip()
    raw = raw.replace("/", "-").replace(".", "-")
    raw = re.sub(r"\s+", " ", raw)

    for fmt in ("%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def parse_birthdate(text: str):
    raw = text.strip()
    raw = raw.replace("/", "-").replace(".", "-")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_time_str(text: str):
    raw = text.strip()
    raw = raw.replace(".", ":").replace(",", ":")

    if ":" not in raw and raw.isdigit() and len(raw) == 4:
        raw = raw[:2] + ":" + raw[2:]

    try:
        return datetime.strptime(raw, "%H:%M").time()
    except ValueError:
        return None


# ======================== /start, /help, /timezone, /birthdays, /export ============================

async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = get_or_create_user(message.from_user.id, message.from_user.username)
    tz_str = get_user_timezone(user_id) or DEFAULT_TZ

    text = (
        "Привіт 👋\n\n"
        "Я бот-нагадувач. Допоможу не забути важливі події.\n\n"
        f"Зараз твій часовий пояс: <b>{tz_str}</b>\n"
        "За потреби можеш змінити його через кнопку «🌍 Часовий пояс» або команду /timezone.\n\n"
        "Обери дію нижче:"
    )

    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(),
    )


async def cmd_help(message: Message, state: FSMContext):
    text = (
        "Якщо щось не працює, є питання або ідеї — "
        f"напиши мені в особисті: <a href=\"{SUPPORT_LINK}\">сюди</a> 💬\n\n"
        "Команди бота:\n"
        "/start — головне меню\n"
        "/birthdays — список днів народження\n"
        "/export — експорт усіх подій\n"
        "/timezone — налаштування часового поясу\n"
        "/help — ця підказка"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


async def cmd_birthdays(message: Message, state: FSMContext):
    await message.answer(
        "Обери фільтр для днів народження:",
        reply_markup=bday_filter_kb(),
    )


async def cmd_export(message: Message, state: FSMContext):
    await message.answer(
        "У якому форматі надіслати експорт твоїх подій? 🙂",
        reply_markup=export_format_kb(),
    )


async def cmd_timezone(message: Message, state: FSMContext):
    user_id = get_or_create_user(message.from_user.id, message.from_user.username)
    tz_str = get_user_timezone(user_id) or DEFAULT_TZ
    await message.answer(
        "Обери свій часовий пояс нижче або введи вручну.\n"
        f"Зараз встановлено: <b>{tz_str}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=timezone_kb(),
    )


async def menu_tz_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = get_or_create_user(callback.from_user.id, callback.from_user.username)
    tz_str = get_user_timezone(user_id) or DEFAULT_TZ
    await callback.message.answer(
        "Обери свій часовий пояс нижче або введи вручну.\n"
        f"Зараз встановлено: <b>{tz_str}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=timezone_kb(),
    )


async def tz_select_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = get_or_create_user(callback.from_user.id, callback.from_user.username)

    if callback.data == "tz:manual":
        await state.set_state(SetTimezone.waiting)
        await callback.message.answer(
            "Введи назву свого часового поясу, наприклад:\n"
            "<code>Europe/Tallinn</code>, <code>Europe/Kyiv</code>, <code>Europe/Warsaw</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    _, tz_str = callback.data.split(":", 1)
    try:
        tzinfo = ZoneInfo(tz_str)
    except Exception:
        await callback.message.answer(
            "Не вийшло розпізнати цей часовий пояс. "
            "Спробуй ще раз або обери інший.",
        )
        return

    set_user_timezone(user_id, tz_str)
    now_local = datetime.now(tzinfo)

    await callback.message.answer(
        f"✅ Часовий пояс оновлено: <b>{tz_str}</b>\n"
        f"Зараз у тебе: <b>{now_local.strftime('%Y-%m-%d %H:%M')}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(),
    )


async def tz_manual_set(message: Message, state: FSMContext):
    tz_str = message.text.strip()
    try:
        tzinfo = ZoneInfo(tz_str)
    except Exception:
        await message.answer(
            "Не вдалося розпізнати цей час. пояс.\n"
            "Приклад: <code>Europe/Tallinn</code>, <code>Europe/Kyiv</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    user_id = get_or_create_user(message.from_user.id, message.from_user.username)
    set_user_timezone(user_id, tz_str)
    await state.clear()

    now_local = datetime.now(tzinfo)
    await message.answer(
        f"✅ Часовий пояс оновлено: <b>{tz_str}</b>\n"
        f"Зараз у тебе: <b>{now_local.strftime('%Y-%m-%d %H:%M')}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(),
    )


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
    cb = callback.data

    if not cb.startswith("cat_"):
        return

    category_key = cb.split("_", 1)[1]
    await state.update_data(category=category_key)
    data = await state.get_data()
    event_type = data["type"]

    user_id = get_or_create_user(callback.from_user.id, callback.from_user.username)
    user_tzinfo = get_tzinfo_for_user(user_id)

    if event_type == "birthday":
        await state.set_state(AddEvent.datetime)
        await callback.message.answer(
            "Введи дату народження у будь-якому з форматів:\n"
            "<code>1999-05-10</code>, <code>10-05-1999</code>, "
            "<code>10.05.1999</code>, <code>10/05/1999</code>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await state.set_state(AddEvent.datetime)
        await callback.message.answer(
            "Оберіть дату і час події з варіантів нижче або введи вручну.\n\n"
            "Приклад ручного вводу:\n"
            "<code>2025-11-22 18:00</code>\n"
            "або <code>22.11.2025 18:00</code> чи <code>22-11-2025 18:00</code>.",
            parse_mode=ParseMode.HTML,
            reply_markup=build_preset_datetime_kb(user_tzinfo),
        )


# ---------- Ручний ввід дати/часу ----------

async def add_event_datetime(message: Message, state: FSMContext):
    data = await state.get_data()
    event_type = data["type"]
    user_id = get_or_create_user(message.from_user.id, message.from_user.username)
    user_tzinfo = get_tzinfo_for_user(user_id)

    # ДР
    if event_type == "birthday":
        bdate = parse_birthdate(message.text)
        if not bdate:
            await message.answer(
                "Невірний формат дати. Спробуй ще раз.\n"
                "Приклад: <code>1999-05-10</code> або <code>10.05.1999</code>.",
                parse_mode=ParseMode.HTML,
            )
            return

        await state.update_data(pending_birthdate=bdate.isoformat())
        await message.answer(
            f"Ти маєш на увазі: <b>{bdate.strftime('%d.%m.%Y')}</b>?",
            parse_mode=ParseMode.HTML,
            reply_markup=confirm_date_kb(),
        )
        return

    # Звичайні події: локальний datetime → UTC
    dt_local = parse_datetime_full(message.text)
    if not dt_local:
        await message.answer(
            "Не можу розібрати дату і час 😕\n"
            "Спробуй у форматі <code>2025-11-22 18:00</code>\n"
            "або <code>22.11.2025 18:00</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    dt_utc = local_to_utc(dt_local, user_tzinfo)
    now_utc = datetime.now(UTC).replace(tzinfo=None)

    if dt_utc < now_utc:
        await message.answer("Дата в минулому ⏳ Обери майбутню.")
        return

    await state.update_data(datetime=dt_utc)
    await state.set_state(AddEvent.remind)
    await message.answer(
        "За скільки хвилин нагадати?\n"
        "0 — тільки в момент події\n"
        "60 — за годину до\n"
        "1440 — за день до\n\n"
        "Можеш обрати готовий варіант нижче або ввести свою кількість хвилин.",
        parse_mode=ParseMode.HTML,
        reply_markup=remind_choice_kb(),
    )


# ---------- Підтвердження дати ДР ----------

async def bday_date_confirm_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()

    if callback.data == "bday_date_ok":
        bdate_iso = data.get("pending_birthdate")
        if not bdate_iso:
            await callback.message.answer("Щось пішло не так, спробуй ще раз додати ДР 🙈")
            await state.clear()
            return

        bdate = date.fromisoformat(bdate_iso)
        await state.update_data(birthdate=bdate)
        await state.set_state(AddEvent.birthday_time)

        await callback.message.answer(
            "О котрій годині тобі зручно отримувати нагадування про ДР?\n"
            "Формат: <b>HH:MM</b> (наприклад <code>09:00</code> або <code>8:30</code>)",
            parse_mode=ParseMode.HTML,
        )

    elif callback.data == "bday_date_retry":
        await callback.message.answer(
            "Добре, введи дату народження ще раз 🙂\n"
            "Наприклад: <code>1999-05-10</code> або <code>10.05.1999</code>",
            parse_mode=ParseMode.HTML,
        )


# ---------- Час для ДР + підтвердження ----------

async def add_birthday_time(message: Message, state: FSMContext):
    t = parse_time_str(message.text)
    if not t:
        await message.answer(
            "Невірний формат часу. Спробуй у форматі <code>09:00</code> або <code>9:00</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    await state.update_data(pending_btime=t.strftime("%H:%M"))
    await message.answer(
        f"Ти маєш на увазі час: <b>{t.strftime('%H:%M')}</b>?",
        parse_mode=ParseMode.HTML,
        reply_markup=confirm_time_kb(),
    )


async def bday_time_confirm_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()

    if callback.data == "bday_time_retry":
        await callback.message.answer(
            "Добре, введи час ще раз 🙂\nНаприклад: <code>09:00</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if callback.data != "bday_time_ok":
        return

    pending_time = data.get("pending_btime")
    bdate: date = data.get("birthdate")

    if not pending_time or not bdate:
        await callback.message.answer("Не вистачає даних, спробуй додати ДР ще раз 🙈")
        await state.clear()
        return

    t = datetime.strptime(pending_time, "%H:%M").time()
    user_id = get_or_create_user(callback.from_user.id, callback.from_user.username)
    user_tzinfo = get_tzinfo_for_user(user_id)

    today_local = datetime.now(user_tzinfo).date()
    year = today_local.year
    next_date = date(year, bdate.month, bdate.day)
    if next_date < today_local:
        next_date = date(year + 1, bdate.month, bdate.day)

    final_dt_local = datetime.combine(next_date, t)
    final_dt_utc = local_to_utc(final_dt_local, user_tzinfo)

    data = await state.get_data()

    add_event(
        user_id=user_id,
        title=data["title"],
        type_="birthday",
        category=data["category"],
        event_dt_utc=final_dt_utc,
        remind_before_minutes=0,
        repeat_yearly=True,
    )

    await state.clear()
    dt_local_show = final_dt_local
    await callback.message.answer(
        "🎉 День народження додано!\n\n"
        f"<b>{data['title']}</b>\n"
        f"Категорія: {CATEGORY_LABELS.get(data['category'], '📌 Інше')}\n"
        f"Наступна дата: {dt_local_show.strftime('%Y-%m-%d')} о {dt_local_show.strftime('%H:%M')}",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(),
    )


# ---------- Інлайн-пресети дати+часу (звичайні події) ----------

async def preset_datetime_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    event_type = data.get("type")

    user_id = get_or_create_user(callback.from_user.id, callback.from_user.username)
    user_tzinfo = get_tzinfo_for_user(user_id)

    if event_type == "birthday":
        await callback.message.answer(
            "Для дня народження краще ввести дату та час вручну 😊"
        )
        return

    if callback.data == "preset_dt_manual":
        await callback.message.answer(
            "Введи дату і час події у зручному форматі.\n"
            "Наприклад: <code>2025-11-22 18:00</code>\n"
            "або <code>22.11.2025 18:00</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    _, dt_str = callback.data.split(":", 1)
    try:
        dt_utc = datetime.fromisoformat(dt_str)
    except ValueError:
        await callback.message.answer(
            "Не вдалося розпізнати дату, введи її, будь ласка, вручну.",
        )
        return

    now_utc = datetime.now(UTC).replace(tzinfo=None)
    if dt_utc < now_utc:
        await callback.message.answer("Ця дата вже в минулому. Обери щось у майбутньому.")
        return

    await state.update_data(datetime=dt_utc)
    await state.set_state(AddEvent.remind)
    dt_local = utc_to_local(dt_utc, user_tzinfo)
    await callback.message.answer(
        "За скільки хвилин нагадати?\n"
        "0 — тільки в момент події\n"
        "60 — за годину до\n"
        "1440 — за день до\n\n"
        f"Обрана дата: <b>{dt_local.strftime('%Y-%m-%d %H:%M')}</b>\n"
        "Можеш обрати готовий варіант нижче або ввести свою кількість хвилин.",
        parse_mode=ParseMode.HTML,
        reply_markup=remind_choice_kb(),
    )


# ---------- Ввід remind ----------

async def add_event_remind(message: Message, state: FSMContext):
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer("Введи лише число (наприклад 0 або 60).")
        return

    minutes = int(raw)
    if minutes < 0:
        await message.answer("Мінімальне значення — 0 хвилин.")
        return

    data = await state.get_data()
    user_id = get_or_create_user(message.from_user.id, message.from_user.username)
    dt_utc = data.get("datetime")

    if isinstance(dt_utc, str):
        dt_utc = datetime.fromisoformat(dt_utc)

    add_event(
        user_id=user_id,
        title=data["title"],
        type_=data["type"],
        category=data["category"],
        event_dt_utc=dt_utc,
        remind_before_minutes=minutes,
        repeat_yearly=False,
    )

    await state.clear()
    await message.answer(
        "Подію додано ✅",
        reply_markup=main_menu_kb(),
    )


async def remind_preset_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    _, val = callback.data.split(":", 1)
    try:
        minutes = int(val)
    except ValueError:
        await callback.message.answer("Помилка з числом хвилин, введи, будь ласка, вручну.")
        await state.set_state(AddEvent.remind)
        return

    data = await state.get_data()
    user_id = get_or_create_user(callback.from_user.id, callback.from_user.username)

    dt_utc = data.get("datetime")
    if isinstance(dt_utc, str):
        dt_utc = datetime.fromisoformat(dt_utc)

    if dt_utc is None:
        await callback.message.answer(
            "Не бачу дати події, спробуй додати подію ще раз 🙈"
        )
        await state.clear()
        return

    add_event(
        user_id=user_id,
        title=data["title"],
        type_=data["type"],
        category=data["category"],
        event_dt_utc=dt_utc,
        remind_before_minutes=minutes,
        repeat_yearly=False,
    )

    await state.clear()
    await callback.message.answer(
        "Подію додано ✅",
        reply_markup=main_menu_kb(),
    )


# ======================== СПИСКИ ПОДІЙ ============================

async def render_events(message: Message, events, header: str):
    user_id = get_or_create_user(message.from_user.id, message.from_user.username)
    tzinfo = get_tzinfo_for_user(user_id)

    if not events:
        await message.answer("Немає подій за цим фільтром.", reply_markup=main_menu_kb())
        return

    text = f"{header}\n\n"
    for idx, e in enumerate(events, start=1):
        dt_utc = datetime.fromisoformat(e["event_datetime"])
        dt_local = utc_to_local(dt_utc, tzinfo)
        cat = e["category"] if e["category"] else "other"
        text += (
            f"{idx}) <b>{e['title']}</b>\n"
            f"ID: <code>{e['id']}</code>\n"
            f"{dt_local.strftime('%Y-%m-%d %H:%M')}\n"
            f"Тип: {e['type']}\n"
            f"Категорія: {CATEGORY_LABELS.get(cat, '📌 Інше')}\n\n"
        )

    text += "👉 Для редагування/видалення використовуй саме ID.\n"

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


async def render_birthdays(message: Message, events, header: str):
    user_id = get_or_create_user(message.from_user.id, message.from_user.username)
    tzinfo = get_tzinfo_for_user(user_id)

    if not events:
        await message.answer("Немає днів народження за цим фільтром 🎂", reply_markup=main_menu_kb())
        return

    text = f"{header}\n\n"
    for idx, e in enumerate(events, start=1):
        dt_utc = datetime.fromisoformat(e["event_datetime"])
        dt_local = utc_to_local(dt_utc, tzinfo)
        cat = e["category"] if e["category"] else "other"
        text += (
            f"{idx}) <b>{e['title']}</b>\n"
            f"ID: <code>{e['id']}</code>\n"
            f"Наступна дата: {dt_local.strftime('%Y-%m-%d')} о {dt_local.strftime('%H:%M')}\n"
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

    cb = callback.data
    key = cb.split("_", 2)[2]

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

    cb = callback.data
    key = cb.split("_", 2)[2]

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
        "event_datetime_utc",
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
            "event_datetime_utc": e["event_datetime"],
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
    tzinfo = get_tzinfo_for_user(user_id)
    events = get_user_events(user_id)

    if not events:
        await callback.message.answer("Немає подій для видалення.", reply_markup=main_menu_kb())
        return

    text = "Введи ID події для видалення:\n\n"
    for e in events:
        dt_utc = datetime.fromisoformat(e["event_datetime"])
        dt_local = utc_to_local(dt_utc, tzinfo)
        text += f"ID {e['id']}: {e['title']} ({dt_local.strftime('%Y-%m-%d %H:%M')})\n"

    await state.set_state(DeleteEvent.choose_id)
    await callback.message.answer(text, reply_markup=ReplyKeyboardRemove())


async def delete_event_process(message: Message, state: FSMContext):
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer("Введи числовий ID.")
        return

    event_id = int(raw)
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
    tzinfo = get_tzinfo_for_user(user_id)
    events = get_user_events(user_id)

    if not events:
        await callback.message.answer("Немає подій для редагування.", reply_markup=main_menu_kb())
        return

    text = "Введи ID події, яку хочеш змінити:\n\n"
    for e in events:
        dt_utc = datetime.fromisoformat(e["event_datetime"])
        dt_local = utc_to_local(dt_utc, tzinfo)
        cat = e["category"] if e["category"] else "other"
        text += (
            f"ID {e['id']}: {e['title']} "
            f"({dt_local.strftime('%Y-%m-%d %H:%M')}, тип: {e['type']}, "
            f"категорія: {CATEGORY_LABELS.get(cat, '📌 Інше')})\n"
        )

    await state.set_state(EditEvent.choose_id)
    await callback.message.answer(text, reply_markup=ReplyKeyboardRemove())


async def edit_event_choose_id(message: Message, state: FSMContext):
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer("Введи числовий ID події.")
        return

    event_id = int(raw)
    user_id = get_or_create_user(message.from_user.id, message.from_user.username)
    row = get_event_by_id(user_id, event_id)

    if not row:
        await message.answer("Подію з таким ID не знайдено. Спробуй ще раз.")
        return

    event_type = row["type"]
    await state.update_data(edit_event_id=event_id, edit_event_type=event_type)
    await state.set_state(EditEvent.choose_field)

    tzinfo = get_tzinfo_for_user(user_id)
    dt_utc = datetime.fromisoformat(row["event_datetime"])
    dt_local = utc_to_local(dt_utc, tzinfo)

    await message.answer(
        "Що хочеш змінити?\n\n"
        f"<b>{row['title']}</b>\n"
        f"{dt_local.strftime('%Y-%m-%d %H:%M')}\n"
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
                "або <b>DD-MM-YYYY</b> (наприклад: <code>1999-05-10</code> або <code>10.05.1999</code>)"
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
                "або <b>DD-MM-YYYY HH:MM</b>\n"
                "Наприклад: <code>2025-12-31 18:00</code> або <code>31.12.2025 18:00</code>"
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

    user_tzinfo = get_tzinfo_for_user(user_id)
    now_utc = datetime.now(UTC).replace(tzinfo=None)

    if field == "title":
        new_title = message.text.strip()
        if len(new_title) < 2:
            await message.answer("Назва надто коротка, спробуй ще раз.")
            return
        update_event_title(event_id, new_title)
        await state.clear()
        await message.answer("Назву оновлено ✅", reply_markup=main_menu_kb())
        return

    if event_type == "birthday":
        existing_dt_utc = datetime.fromisoformat(row["event_datetime"])
        existing_dt_local = utc_to_local(existing_dt_utc, user_tzinfo)

        if field == "birthdate":
            bdate = parse_birthdate(message.text)
            if not bdate:
                await message.answer(
                    "Невірний формат. Спробуй так: <code>1999-05-10</code> або <code>10.05.1999</code>.",
                    parse_mode=ParseMode.HTML,
                )
                return

            today_local = datetime.now(user_tzinfo).date()
            year = today_local.year
            next_bday = date(year, bdate.month, bdate.day)
            if next_bday < today_local:
                next_bday = date(year + 1, bdate.month, bdate.day)

            new_local = datetime.combine(next_bday, existing_dt_local.time())
            new_utc = local_to_utc(new_local, user_tzinfo)

            update_event_datetime_and_reset(event_id, new_utc, is_birthday=True)

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

            new_local = datetime.combine(existing_dt_local.date(), t)
            new_utc = local_to_utc(new_local, user_tzinfo)

            if new_utc < now_utc:
                new_local = new_local.replace(year=new_local.year + 1)
                new_utc = local_to_utc(new_local, user_tzinfo)

            update_event_datetime_and_reset(event_id, new_utc, is_birthday=True)

            await state.clear()
            await message.answer("Час нагадувань оновлено ✅", reply_markup=main_menu_kb())
            return

    else:
        if field == "datetime":
            dt_local = parse_datetime_full(message.text)
            if not dt_local:
                await message.answer(
                    "Невірний формат. Спробуй так:\n"
                    "<code>2025-12-31 18:00</code> або <code>31.12.2025 18:00</code>.",
                    parse_mode=ParseMode.HTML,
                )
                return

            dt_utc = local_to_utc(dt_local, user_tzinfo)
            if dt_utc < now_utc:
                await message.answer("Ця дата вже в минулому. Вкажи майбутню.")
                return

            update_event_datetime_and_reset(event_id, dt_utc, is_birthday=False)
            await state.clear()
            await message.answer(
                "Дату й час події оновлено ✅",
                reply_markup=main_menu_kb(),
            )
            return

        if field == "remind":
            raw = message.text.strip()
            if not raw.isdigit():
                await message.answer("Введи число хвилин (0, 60, 1440 тощо).")
                return
            minutes = int(raw)
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
        now_utc = datetime.now(UTC).replace(tzinfo=None)
        events = get_events_to_notify(now_utc)

        for item in events:
            row = item["row"]
            kind = item["kind"]

            tg_id = row["tg_id"]
            title = row["title"]
            event_dt_utc = datetime.fromisoformat(row["event_datetime"])
            repeat_yearly = bool(row["repeat_yearly"])
            event_type = row["type"]
            tz_str = row["timezone"] or DEFAULT_TZ
            try:
                user_tzinfo = ZoneInfo(tz_str)
            except Exception:
                user_tzinfo = ZoneInfo(DEFAULT_TZ)

            event_dt_local = utc_to_local(event_dt_utc, user_tzinfo)

            if event_type == "birthday":
                if kind == "30d":
                    text = f"🥳 За місяць день народження: <b>{title}</b>"
                elif kind == "7d":
                    text = f"🎉 За тиждень день народження: <b>{title}</b>"
                elif kind == "1d":
                    text = f"🎈 Вже завтра день народження: <b>{title}</b>"
                else:
                    text = f"🔥 Сьогодні день народження <b>{title}</b>!"

                try:
                    await bot.send_message(tg_id, text, parse_mode=ParseMode.HTML)
                except Exception as e:
                    print(f"Помилка надсилання (birthday): {e}")

                mark_notified(row["id"], kind, repeat_yearly)

            else:
                if kind == "before":
                    text = (
                        f"⏰ Нагадування: <b>{title}</b>\n"
                        f"О {event_dt_local.strftime('%Y-%m-%d %H:%M')}"
                    )
                    try:
                        await bot.send_message(tg_id, text, parse_mode=ParseMode.HTML)
                    except Exception as e:
                        print(f"Помилка надсилання (before): {e}")

                    mark_notified(row["id"], kind, repeat_yearly)

                elif kind == "main":
                    text = (
                        f"🔥 Подія зараз: <b>{title}</b>\n"
                        f"{event_dt_local.strftime('%Y-%m-%d %H:%M')}"
                    )
                    try:
                        await bot.send_message(tg_id, text, parse_mode=ParseMode.HTML)
                    except Exception as e:
                        print(f"Помилка надсилання (main): {e}")

                    try:
                        delete_event_by_id(row["id"])
                        print(f"Подію id={row['id']} видалено автоматично після проходження.")
                    except Exception as e:
                        print(f"Помилка автознищення події id={row['id']}: {e}")

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
    dp.message.register(cmd_timezone, Command("timezone"))

    # Меню
    dp.callback_query.register(menu_add_callback, F.data == "menu_add")
    dp.callback_query.register(menu_list_callback, F.data == "menu_list")
    dp.callback_query.register(menu_birthdays_callback, F.data == "menu_birthdays")
    dp.callback_query.register(menu_edit_callback, F.data == "menu_edit")
    dp.callback_query.register(menu_delete_callback, F.data == "menu_delete")
    dp.callback_query.register(menu_tz_callback, F.data == "menu_tz")

    # TZ
    dp.callback_query.register(tz_select_callback, F.data.startswith("tz:"))
    dp.message.register(tz_manual_set, SetTimezone.waiting)

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

    # Інлайн-пресети дати+часу
    dp.callback_query.register(
        preset_datetime_callback,
        F.data.startswith("preset_dt"),
    )

    # Підтвердження дати/часу для ДР
    dp.callback_query.register(
        bday_date_confirm_callback,
        F.data.in_(["bday_date_ok", "bday_date_retry"]),
    )
    dp.callback_query.register(
        bday_time_confirm_callback,
        F.data.in_(["bday_time_ok", "bday_time_retry"]),
    )

    # Пресети remind
    dp.callback_query.register(
        remind_preset_callback,
        F.data.startswith("remind_preset"),
    )

    # Додавання події
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
    dp.message.register(delete_event_process, DeleteEvent.choose_id)

    # Усе інше
    dp.message.register(fallback)


async def main():
    init_db()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()

    setup_handlers(dp)

    asyncio.create_task(reminder_loop(bot))

    print("Bot started (background worker, multi-TZ).")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
