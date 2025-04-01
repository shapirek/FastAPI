import sqlite3
from datetime import datetime

# Добавляем константу для формата даты
DEFAULT_EXPIRATION_FORMAT = "%Y-%m-%d %H:%M:%S"  # Теперь с секундами


def get_connection():
    conn = sqlite3.connect('shortener.db', check_same_thread=False)
    # Добавляем преобразование дат для SQLite
    conn.execute("PRAGMA foreign_keys = 1")

    # Регистрируем адаптеры для datetime
    sqlite3.register_adapter(datetime, lambda dt: dt.strftime(DEFAULT_EXPIRATION_FORMAT))
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_url TEXT NOT NULL,
            short_code TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
            clicks INTEGER DEFAULT 0,
            last_used_at TEXT,
            expires_at TEXT
        )
    ''')
    conn.commit()
    conn.close()


init_db()
