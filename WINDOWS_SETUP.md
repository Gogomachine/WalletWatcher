# Установка на Windows

## Требования

- **Python 3.11 или 3.12** (Python 3.14 пока не поддерживается всеми зависимостями)
- Git (опционально)

## Шаг 1: Установка правильной версии Python

### Проверьте текущую версию:
```powershell
python --version
```

Если у вас Python 3.14, установите Python 3.11 или 3.12.

### Скачайте Python 3.11:

1. Перейдите на https://www.python.org/downloads/
2. Найдите **Python 3.11.x** (последняя версия 3.11)
3. Скачайте "Windows installer (64-bit)"
4. При установке:
   - ✅ Отметьте "Add Python 3.11 to PATH"
   - ✅ Выберите "Install for all users" (опционально)
   - Нажмите "Install Now"

### Проверьте установку:
```powershell
# Если установлено несколько версий Python
py -3.11 --version

# Должно показать: Python 3.11.x
```

## Шаг 2: Создание виртуального окружения

```powershell
# Перейдите в папку проекта
cd C:\txpeek

# Создайте виртуальное окружение с Python 3.11
py -3.11 -m venv venv

# Активируйте виртуальное окружение
.\venv\Scripts\Activate.ps1
```

**Если возникает ошибка политики выполнения:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\venv\Scripts\Activate.ps1
```

После активации вы увидите `(venv)` в начале строки.

## Шаг 3: Установка зависимостей

```powershell
# Убедитесь, что venv активировано (должно быть (venv) в начале)
# Обновите pip
python -m pip install --upgrade pip

# Установите зависимости
pip install -r requirements.txt
```

## Шаг 4: Настройка

```powershell
# Создайте .env файл
copy .env.example .env

# Откройте для редактирования
notepad .env
```

Добавьте ваш Telegram Bot Token:
```
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
DATABASE_PATH=./data/bot.db
MONITOR_INTERVAL=10
```

### Как получить токен:
1. Найдите [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot`
3. Следуйте инструкциям
4. Скопируйте токен в файл `.env`

## Шаг 5: Запуск

```powershell
# Убедитесь, что venv активировано
python main.py
```

Вы должны увидеть:
```
INFO - Initializing Solana client...
INFO - Initializing database...
INFO - Bot started!
```

## Остановка бота

Нажмите `Ctrl+C` в окне PowerShell.

## Устранение проблем

### "Python was not found"
- Переустановите Python и отметьте "Add to PATH"
- Или используйте `py -3.11` вместо `python`

### "pip is not recognized"
```powershell
python -m pip install --upgrade pip
```

### "Cannot be loaded because running scripts is disabled"
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### "No module named 'solana'"
- Убедитесь, что виртуальное окружение активировано (должно быть `(venv)`)
- Запустите снова: `pip install -r requirements.txt`

### Бот не отвечает
- Проверьте токен в `.env`
- Убедитесь, что нет лишних пробелов
- Проверьте логи на ошибки

## Работа с несколькими версиями Python

Если у вас установлено несколько версий Python:

```powershell
# Список всех версий
py --list

# Используйте конкретную версию
py -3.11 -m pip install -r requirements.txt
py -3.11 main.py
```

## Деактивация виртуального окружения

Когда закончите работу:
```powershell
deactivate
```

## Автоматический запуск (опционально)

Создайте файл `start.bat`:
```batch
@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
python main.py
pause
```

Двойной клик на `start.bat` запустит бота.

## Запуск в фоне (как служба)

Для запуска бота как службы Windows используйте NSSM:

1. Скачайте NSSM: https://nssm.cc/download
2. Извлеките `nssm.exe`
3. Запустите PowerShell как администратор:

```powershell
.\nssm.exe install WalletWatcherBot "C:\txpeek\venv\Scripts\python.exe" "C:\txpeek\main.py"
.\nssm.exe set WalletWatcherBot AppDirectory "C:\txpeek"
.\nssm.exe start WalletWatcherBot
```

Управление службой:
```powershell
# Остановить
.\nssm.exe stop WalletWatcherBot

# Удалить службу
.\nssm.exe remove WalletWatcherBot confirm
```
