# Быстрый старт WalletWatcher

## 1. Настройка

Скопируйте файл с примером конфигурации:
```bash
cp .env.example .env
```

Отредактируйте `.env` и добавьте ваш Telegram Bot Token:
```bash
nano .env
```

Пример `.env`:
```
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
DATABASE_PATH=./data/bot.db
MONITOR_INTERVAL=10
```

## 2. Получение токена бота

1. Найдите [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot`
3. Следуйте инструкциям
4. Скопируйте полученный токен в файл `.env`

## 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

## 4. Запуск

```bash
python main.py
```

Или используйте скрипт:
```bash
chmod +x run.sh
./run.sh
```

## 5. Использование

1. Найдите вашего бота в Telegram
2. Отправьте `/start`
3. Используйте меню для:
   - 📊 Проверки адресов
   - ➕ Добавления адресов в отслеживание
   - 📋 Управления отслеживаемыми адресами
   - ⚙️ Настройки уведомлений

## Пример адресов для тестирования

```
7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU
DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263
```

## Docker (альтернативный метод)

```bash
# Создайте .env файл
cp .env.example .env

# Отредактируйте и добавьте токен
nano .env

# Запустите
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down
```

## Устранение неполадок

**Ошибка: "Invalid bot token"**
- Проверьте правильность токена в `.env`
- Убедитесь, что нет лишних пробелов

**Ошибка: "Connection error"**
- Проверьте интернет-соединение
- Попробуйте другой RPC endpoint для Solana

**Бот не отвечает**
- Проверьте, что бот запущен (`python main.py`)
- Проверьте логи на наличие ошибок

## Полезные команды

```bash
# Просмотр логов
tail -f logs/bot.log  # если настроено логирование в файл

# Остановка бота
Ctrl+C

# Проверка процессов
ps aux | grep main.py
```
