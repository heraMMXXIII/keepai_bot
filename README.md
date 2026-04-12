# keepai_bot

Telegram-бот для мониторинга сервисов KeepAI: балансы у платных API и проверка доступности нейросетей. Отчёты уходят в личку только указанным пользователям.

## Возможности

- **Балансы** (по API): ElevenLabs, Suno, Runway.
- **Работоспособность API**: ChatGPT (OpenAI), Claude, Gemini, Perplexity, Grok, Ideogram.
- **Даты пополнения** по каждому сервису — хранятся локально в `storage.json`, удобно сверять с расходом.
- **Расписание**: ежедневный полный отчёт (время задаётся в `.env`), периодические отчёты только по балансам, опциональные алерты при низком балансе (USD / токены).
- **Ручной запуск** из меню: «Проверить состояние нейросетей».

## Требования

- Python 3.12+ (как в текущей среде разработки).
- Токен бота от [@BotFather](https://t.me/BotFather).
- Ключи API нейросетей: проще всего положить их в `.env` бэкенда KeepAI и указать путь в `BACKEND_ENV_FILE` (см. ниже).

## Установка

На Debian/Ubuntu системный `pip` защищён ([PEP 668](https://peps.python.org/pep-0668/)) — зависимости ставьте только в виртуальное окружение:

```bash
cd /path/to/keepai_bot
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Зависимости: `python-telegram-bot`, `APScheduler`, `httpx`, `python-dotenv`.

## Конфигурация

1. Скопируйте пример и заполните значения:

   ```bash
   cp .env.example .env
   ```

2. Обязательно задайте:

   - `TELEGRAM_BOT_TOKEN` — токен бота.
   - `TELEGRAM_ALLOWED_USER_IDS` — числовые user id через запятую (кому разрешён доступ и кому слать отчёты). Свой id можно узнать у [@userinfobot](https://t.me/userinfobot) или по логам после `/start`.

3. Ключи OpenAI, Anthropic, Google, Perplexity, xAI и т.д. бот подхватывает из **`.env` бэкенда** по умолчанию (`../keepai_backend/.env`) или из файла, указанного в `BACKEND_ENV_FILE` (путь можно задать относительно каталога бота).

4. Остальные переменные (часовой пояс, время ежедневного отчёта, интервал проверки балансов, пороги алертов, модели) описаны в `.env.example`.

## Логи

В консоль пишутся только:

- **действия пользователей** (команды, кнопки, сохранение дат, отказ в доступе);
- **автоотчёты по расписанию** (интервальный отчёт по балансам и ежедневный полный отчёт).

Запросы к HTTP API (Telegram, нейросети) в лог не выводятся.

## Запуск

```bash
cd /path/to/keepai_bot
source .venv/bin/activate
python bot.py
```

Бот работает в режиме **long polling**; остановка — `Ctrl+C`.

Без активации venv:

```bash
/path/to/keepai_bot/.venv/bin/python /path/to/keepai_bot/bot.py
```

Для постоянной работы на сервере обычно настраивают **systemd** (или аналог) с `WorkingDirectory` на каталог бота и `ExecStart` на интерпретатор из `.venv`. Имя юнита ниже — `keepai-bot.service`; если у вас другое имя файла в `/etc/systemd/system/`, подставьте его.

После правок кода, зависимостей или `.env` перезапуск:

```bash
sudo systemctl restart keepai-bot.service
```

Остальные типовые команды:

```bash
sudo systemctl start keepai-bot.service      # запуск
sudo systemctl stop keepai-bot.service       # остановка
sudo systemctl status keepai-bot.service     # статус
sudo systemctl enable keepai-bot.service     # автозапуск при загрузке ОС (один раз)
```

Если меняли сам unit-файл (`/etc/systemd/system/keepai-bot.service`):

```bash
sudo systemctl daemon-reload
sudo systemctl restart keepai-bot.service
```

Логи сервиса:

```bash
sudo journalctl -u keepai-bot.service -f       # поток в реальном времени
sudo journalctl -u keepai-bot.service -n 100 # последние ~100 строк
```

## Команды в Telegram

| Команда | Описание |
|--------|----------|
| `/start` | Главное меню |
| `/popolnenie` | Выбор сервиса и ввод даты последнего пополнения (формат `ДД.ММ.ГГГГ`) |
| `/cancel` | Отмена ввода даты |

В меню бота: проверка нейросетей по кнопке, переход к датам пополнения.

## Структура проекта

| Файл / каталог | Назначение |
|----------------|------------|
| `bot.py` | Точка входа, хендлеры Telegram, сборка `Application` |
| `config.py` | Загрузка настроек из `.env` бота и бэкенда |
| `scheduler.py` | Планировщик и сбор отчётов |
| `storage.py` | Локальное хранилище дат пополнения |
| `messages.py` | Форматирование текстов отчётов |
| `checkers/` | Запросы балансов и health-check по API |
| `storage.json` | Создаётся при работе (даты пополнения), не коммитьте с секретами |

## Лицензия

Внутренний проект KeepAI; при публикации добавьте файл лицензии при необходимости.
