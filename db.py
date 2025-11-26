import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # таблиця користувачів
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE,
            username TEXT
        );
        """
    )

    # таблиця подій
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            type TEXT NOT NULL,                  
            category TEXT DEFAULT 'other',        -- family, friends, work, other
            event_datetime TEXT NOT NULL,        
            remind_before_minutes INTEGER DEFAULT 0,

            notified_30d INTEGER DEFAULT 0,
            notified_7d INTEGER DEFAULT 0,
            notified_1d INTEGER DEFAULT 0,
            notified_main INTEGER DEFAULT 0,

            repeat_yearly INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        """
    )

    conn.commit()
    conn.close()


def get_or_create_user(tg_id: int, username: Optional[str]) -> int:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
    row = cur.fetchone()

    if row:
        user_id = row["id"]
    else:
        cur.execute(
            "INSERT INTO users (tg_id, username) VALUES (?, ?)",
            (tg_id, username),
        )
        user_id = cur.lastrowid
        conn.commit()

    conn.close()
    return user_id


def add_event(
    user_id: int,
    title: str,
    type_: str,
    event_dt: datetime,
    category: str = "other",
    remind_before_minutes: int = 0,
    repeat_yearly: bool = False,
):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO events (
            user_id, title, type, category, event_datetime,
            remind_before_minutes, repeat_yearly
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            title,
            type_,
            category,
            event_dt.isoformat(),
            remind_before_minutes,
            1 if repeat_yearly else 0,
        ),
    )

    conn.commit()
    conn.close()


def get_user_events(user_id: int) -> List[sqlite3.Row]:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM events
        WHERE user_id = ?
        ORDER BY event_datetime ASC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_user_events_by_category(user_id: int, category: str) -> List[sqlite3.Row]:
    """Повертає події за категорією. category = 'family'/'friends'/'work'/'other'."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM events
        WHERE user_id = ? AND category = ?
        ORDER BY event_datetime ASC
        """,
        (user_id, category),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_user_birthdays(user_id: int) -> List[sqlite3.Row]:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM events
        WHERE user_id = ? AND type = 'birthday'
        ORDER BY event_datetime ASC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_user_birthdays_by_category(user_id: int, category: str) -> List[sqlite3.Row]:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM events
        WHERE user_id = ? AND type = 'birthday' AND category = ?
        ORDER BY event_datetime ASC
        """,
        (user_id, category),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_event(user_id: int, event_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM events WHERE id = ? AND user_id = ?",
        (event_id, user_id),
    )
    deleted = cur.rowcount > 0

    conn.commit()
    conn.close()
    return deleted


def get_event_by_id(user_id: int, event_id: int) -> Optional[sqlite3.Row]:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM events WHERE id = ? AND user_id = ?",
        (event_id, user_id),
    )
    row = cur.fetchone()
    conn.close()
    return row


def update_event_title(event_id: int, new_title: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE events SET title = ? WHERE id = ?",
        (new_title, event_id),
    )
    conn.commit()
    conn.close()


def update_event_datetime_and_reset(event_id: int, new_dt: datetime, is_birthday: bool):
    conn = get_connection()
    cur = conn.cursor()

    if is_birthday:
        cur.execute(
            """
            UPDATE events
            SET event_datetime = ?,
                notified_30d = 0,
                notified_7d = 0,
                notified_1d = 0,
                notified_main = 0
            WHERE id = ?
            """,
            (new_dt.isoformat(), event_id),
        )
    else:
        cur.execute(
            """
            UPDATE events
            SET event_datetime = ?,
                notified_main = 0
            WHERE id = ?
            """,
            (new_dt.isoformat(), event_id),
        )

    conn.commit()
    conn.close()


def update_event_remind_before(event_id: int, minutes: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE events
        SET remind_before_minutes = ?, notified_main = 0
        WHERE id = ?
        """,
        (minutes, event_id),
    )
    conn.commit()
    conn.close()


def get_events_to_notify(now: datetime) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT e.*, u.tg_id
        FROM events e
        JOIN users u ON e.user_id = u.id
        """
    )
    rows = cur.fetchall()
    conn.close()

    to_notify: List[Dict[str, Any]] = []

    for row in rows:
        event_dt = datetime.fromisoformat(row["event_datetime"])
        event_type = row["type"]

        # ---------- ДНІ НАРОДЖЕННЯ ----------
        if event_type == "birthday":
            stages = [
                ("30d", "notified_30d", 30),
                ("7d", "notified_7d", 7),
                ("1d", "notified_1d", 1),
                ("main", "notified_main", 0),
            ]

            for kind, flag, days_before in stages:
                if row[flag] == 1:
                    continue

                target_time = event_dt - timedelta(days=days_before)
                diff = (target_time - now).total_seconds()

                if 0 <= diff <= 60:
                    to_notify.append({"row": row, "kind": kind})

        # ---------- ЗВИЧАЙНІ ПОДІЇ ----------
        else:
            diff_sec = (event_dt - now).total_seconds()

            if row["remind_before_minutes"] > 0 and row["notified_main"] == 0:
                remind_moment = event_dt - timedelta(
                    minutes=row["remind_before_minutes"]
                )
                diff_before = (remind_moment - now).total_seconds()
                if 0 <= diff_before <= 60:
                    to_notify.append({"row": row, "kind": "before"})

            if row["notified_main"] == 0 and 0 <= diff_sec <= 60:
                to_notify.append({"row": row, "kind": "main"})

    return to_notify


def mark_notified(event_id: int, kind: str, repeat_yearly: bool):
    conn = get_connection()
    cur = conn.cursor()

    if kind == "30d":
        cur.execute("UPDATE events SET notified_30d = 1 WHERE id = ?", (event_id,))
    elif kind == "7d":
        cur.execute("UPDATE events SET notified_7d = 1 WHERE id = ?", (event_id,))
    elif kind == "1d":
        cur.execute("UPDATE events SET notified_1d = 1 WHERE id = ?", (event_id,))
    elif kind == "main":
        if repeat_yearly:
            cur.execute(
                "SELECT event_datetime FROM events WHERE id = ?",
                (event_id,),
            )
            row = cur.fetchone()
            old_dt = datetime.fromisoformat(row["event_datetime"])
            new_dt = old_dt.replace(year=old_dt.year + 1)

            cur.execute(
                """
                UPDATE events
                SET event_datetime = ?,
                    notified_main = 0,
                    notified_30d = 0,
                    notified_7d = 0,
                    notified_1d = 0
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
    conn.close()
