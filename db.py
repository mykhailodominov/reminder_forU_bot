import sqlite3
from datetime import datetime, timedelta

from config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # USERS
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER NOT NULL UNIQUE,
            username TEXT,
            timezone TEXT
        );
        """
    )

    # На випадок старої БД без стовпця timezone
    cur.execute("PRAGMA table_info(users)")
    cols = [r["name"] for r in cur.fetchall()]
    if "timezone" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN timezone TEXT")

    # EVENTS
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            type TEXT NOT NULL,
            category TEXT,
            event_datetime TEXT NOT NULL,
            remind_before_minutes INTEGER DEFAULT 0,
            repeat_yearly INTEGER DEFAULT 0,
            notified_30d INTEGER DEFAULT 0,
            notified_7d INTEGER DEFAULT 0,
            notified_1d INTEGER DEFAULT 0,
            notified_before INTEGER DEFAULT 0,
            notified_main INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """
    )

    conn.commit()


# =============== USERS ==================


def get_or_create_user(tg_id: int, username: str | None) -> int:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
    row = cur.fetchone()
    if row:
        return row["id"]

    cur.execute(
        "INSERT INTO users (tg_id, username) VALUES (?, ?)",
        (tg_id, username),
    )
    conn.commit()
    return cur.lastrowid


def get_user_timezone(user_id: int) -> str | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT timezone FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return None
    return row["timezone"]


def set_user_timezone(user_id: int, tz: str) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET timezone = ? WHERE id = ?", (tz, user_id))
    conn.commit()


# =============== EVENTS CRUD ==================


def add_event(
    user_id: int,
    title: str,
    type_: str,
    category: str | None,
    event_dt_utc: datetime,
    remind_before_minutes: int = 0,
    repeat_yearly: bool = False,
) -> int:
    """
    ВАЖЛИВО: event_dt_utc — це вже час у UTC (naive).
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO events (
            user_id, title, type, category,
            event_datetime, remind_before_minutes,
            repeat_yearly, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            title,
            type_,
            category,
            event_dt_utc.isoformat(),
            remind_before_minutes,
            1 if repeat_yearly else 0,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_user_events(user_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM events
        WHERE user_id = ?
        ORDER BY datetime(event_datetime) ASC
        """,
        (user_id,),
    )
    return cur.fetchall()


def get_user_events_by_category(user_id: int, category: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM events
        WHERE user_id = ?
          AND (category = ? OR (category IS NULL AND ? = 'other'))
        ORDER BY datetime(event_datetime) ASC
        """,
        (user_id, category, category),
    )
    return cur.fetchall()


def get_user_birthdays(user_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM events
        WHERE user_id = ?
          AND type = 'birthday'
        ORDER BY datetime(event_datetime) ASC
        """,
        (user_id,),
    )
    return cur.fetchall()


def get_user_birthdays_by_category(user_id: int, category: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM events
        WHERE user_id = ?
          AND type = 'birthday'
          AND (category = ? OR (category IS NULL AND ? = 'other'))
        ORDER BY datetime(event_datetime) ASC
        """,
        (user_id, category, category),
    )
    return cur.fetchall()


def get_event_by_id(user_id: int, event_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM events WHERE id = ? AND user_id = ?",
        (event_id, user_id),
    )
    return cur.fetchone()


def delete_event(user_id: int, event_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM events WHERE id = ? AND user_id = ?",
        (event_id, user_id),
    )
    conn.commit()
    return cur.rowcount > 0


def delete_event_by_id(event_id: int) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM events WHERE id = ?", (event_id,))
    conn.commit()


def update_event_title(event_id: int, new_title: str) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE events SET title = ? WHERE id = ?",
        (new_title, event_id),
    )
    conn.commit()


def update_event_datetime_and_reset(
    event_id: int, new_dt_utc: datetime, is_birthday: bool
) -> None:
    """
    new_dt_utc — знову ж таки в UTC (naive).
    """
    conn = get_connection()
    cur = conn.cursor()

    if is_birthday:
        cur.execute(
            """
            UPDATE events
            SET event_datetime = ?,
                repeat_yearly = 1,
                notified_30d = 0,
                notified_7d = 0,
                notified_1d = 0,
                notified_before = 0,
                notified_main = 0
            WHERE id = ?
            """,
            (new_dt_utc.isoformat(), event_id),
        )
    else:
        cur.execute(
            """
            UPDATE events
            SET event_datetime = ?,
                notified_30d = 0,
                notified_7d = 0,
                notified_1d = 0,
                notified_before = 0,
                notified_main = 0
            WHERE id = ?
            """,
            (new_dt_utc.isoformat(), event_id),
        )

    conn.commit()


def update_event_remind_before(event_id: int, minutes: int) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE events SET remind_before_minutes = ? WHERE id = ?",
        (minutes, event_id),
    )
    conn.commit()


# =============== NOTIFICATIONS ==================


def get_events_to_notify(now_utc: datetime):
    """
    now_utc — поточний час в UTC (naive).
    event_datetime в БД також зберігається як UTC (naive).
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT e.*, u.tg_id, u.timezone
        FROM events e
        JOIN users u ON e.user_id = u.id
        """
    )
    rows = cur.fetchall()

    result = []

    for row in rows:
        event_dt_utc = datetime.fromisoformat(row["event_datetime"])
        event_type = row["type"]
        repeat_yearly = bool(row["repeat_yearly"])

        # Дні народження
        if event_type == "birthday":
            # 30 днів
            target_30 = event_dt_utc - timedelta(days=30)
            if (
                row["notified_30d"] == 0
                and 0 <= (now_utc - target_30).total_seconds() < 60
            ):
                result.append({"row": row, "kind": "30d"})
                continue

            # 7 днів
            target_7 = event_dt_utc - timedelta(days=7)
            if (
                row["notified_7d"] == 0
                and 0 <= (now_utc - target_7).total_seconds() < 60
            ):
                result.append({"row": row, "kind": "7d"})
                continue

            # 1 день
            target_1 = event_dt_utc - timedelta(days=1)
            if (
                row["notified_1d"] == 0
                and 0 <= (now_utc - target_1).total_seconds() < 60
            ):
                result.append({"row": row, "kind": "1d"})
                continue

            # Основний день
            if (
                row["notified_main"] == 0
                and 0 <= (now_utc - event_dt_utc).total_seconds() < 60
            ):
                result.append({"row": row, "kind": "main"})
                continue

        # Звичайні події
        else:
            before_min = row["remind_before_minutes"] or 0

            if before_min > 0:
                before_dt_utc = event_dt_utc - timedelta(minutes=before_min)
                if (
                    row["notified_before"] == 0
                    and 0 <= (now_utc - before_dt_utc).total_seconds() < 60
                ):
                    result.append({"row": row, "kind": "before"})
                    continue

            if (
                row["notified_main"] == 0
                and 0 <= (now_utc - event_dt_utc).total_seconds() < 60
            ):
                result.append({"row": row, "kind": "main"})
                continue

    return result


def mark_notified(event_id: int, kind: str, repeat_yearly: bool) -> None:
    conn = get_connection()
    cur = conn.cursor()

    if kind == "30d":
        cur.execute(
            "UPDATE events SET notified_30d = 1 WHERE id = ?",
            (event_id,),
        )
    elif kind == "7d":
        cur.execute(
            "UPDATE events SET notified_7d = 1 WHERE id = ?",
            (event_id,),
        )
    elif kind == "1d":
        cur.execute(
            "UPDATE events SET notified_1d = 1 WHERE id = ?",
            (event_id,),
        )
    elif kind == "before":
        cur.execute(
            "UPDATE events SET notified_before = 1 WHERE id = ?",
            (event_id,),
        )
    elif kind == "main":
        if repeat_yearly:
            # Для ДР: переносимо на наступний рік (в UTC)
            cur.execute(
                "SELECT event_datetime FROM events WHERE id = ?",
                (event_id,),
            )
            row = cur.fetchone()
            if row:
                dt = datetime.fromisoformat(row["event_datetime"])
                new_dt = dt.replace(year=dt.year + 1)
                cur.execute(
                    """
                    UPDATE events
                    SET event_datetime = ?,
                        notified_30d = 0,
                        notified_7d = 0,
                        notified_1d = 0,
                        notified_before = 0,
                        notified_main = 0
                    WHERE id = ?
                    """,
                    (new_dt.isoformat(), event_id),
                )
        else:
            cur.execute(
                "UPDATE events SET notified_main = 1 WHERE id = ?",
                (event_id,),
            )

    conn.commit()
