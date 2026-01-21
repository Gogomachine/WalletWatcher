#!/usr/bin/env python3
"""
Скрипт для полной очистки базы данных.
ВНИМАНИЕ: Удаляет ВСЕ данные - пользователей, адреса, группы, настройки!
"""

import asyncio
import os
from pathlib import Path


async def reset_sqlite():
    """Очистка SQLite базы данных."""
    db_path = Path("data/wallet_watcher.db")

    if db_path.exists():
        print(f"🗑️  Удаляю файл базы данных: {db_path}")
        db_path.unlink()
        print("✅ SQLite база данных удалена")
    else:
        print(f"⚠️  Файл {db_path} не найден")

    # Создаём директорию если её нет
    db_path.parent.mkdir(exist_ok=True)

    # Импортируем и инициализируем новую БД
    from src.database.db import Database

    db = Database(str(db_path))
    await db.init_db()
    print("✅ SQLite база данных пересоздана с чистой структурой")


async def reset_postgres():
    """Очистка PostgreSQL базы данных."""
    try:
        from src.database.postgres_db import PostgresDatabase

        # Получаем connection string из переменных окружения
        connection_string = os.getenv("DATABASE_URL")

        if not connection_string:
            print("⚠️  DATABASE_URL не найден в переменных окружения - пропускаю PostgreSQL")
            return

        print(f"🔗 Подключаюсь к PostgreSQL...")
        pg_db = PostgresDatabase(connection_string)
        await pg_db.connect()

        # Удаляем все таблицы
        async with pg_db.pool.acquire() as conn:
            print("🗑️  Удаляю все таблицы...")
            await conn.execute("DROP TABLE IF EXISTS tracked_addresses CASCADE")
            await conn.execute("DROP TABLE IF EXISTS address_groups CASCADE")
            await conn.execute("DROP TABLE IF EXISTS user_settings CASCADE")
            print("✅ Все таблицы удалены")

        # Пересоздаём таблицы
        await pg_db.init_db()
        print("✅ PostgreSQL база данных пересоздана с чистой структурой")

        await pg_db.close()

    except ImportError:
        print("⚠️  PostgreSQL модуль не найден - пропускаю")
    except Exception as e:
        print(f"❌ Ошибка при работе с PostgreSQL: {e}")


async def main():
    """Главная функция очистки."""
    print("=" * 60)
    print("🔥 ПОЛНАЯ ОЧИСТКА БАЗЫ ДАННЫХ")
    print("=" * 60)
    print()
    print("⚠️  ВНИМАНИЕ: Это удалит ВСЕ данные:")
    print("   • Всех пользователей")
    print("   • Все отслеживаемые адреса")
    print("   • Все группы")
    print("   • Все настройки")
    print("   • Все счетчики и историю")
    print()

    # Запрашиваем подтверждение
    confirm = input("Вы уверены? Введите 'ДА' для подтверждения: ")

    if confirm != "ДА":
        print("❌ Отменено")
        return

    print()
    print("🚀 Начинаю очистку...")
    print()

    # Очищаем SQLite
    await reset_sqlite()
    print()

    # Очищаем PostgreSQL (если используется)
    await reset_postgres()
    print()

    print("=" * 60)
    print("✅ БАЗА ДАННЫХ ПОЛНОСТЬЮ ОЧИЩЕНА И ПЕРЕСОЗДАНА")
    print("=" * 60)
    print()
    print("Теперь можно запустить бота - он будет работать с чистой базой")
    print()


if __name__ == "__main__":
    asyncio.run(main())
