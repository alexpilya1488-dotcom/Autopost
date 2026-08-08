# Деплой assistant_bot.py на VPS

Нужен постоянно работающий сервер (не GitHub Actions) — только так Telegram
Stars-платежи будут успевать подтверждаться за 10 секунд. Инструкция
рассчитана на то, что делаете всё с телефона, без компьютера.

## 1. Арендовать VPS

Любой провайдер с Ubuntu 22.04/24.04, минимальная конфигурация (1 vCPU,
512 МБ–1 ГБ RAM) — этому боту много не надо. Из RU-провайдеров с простой
оплатой российской картой: Timeweb Cloud, Selectel, REG.RU и похожие —
выбирайте сами, конкретные цены/интерфейсы меняются, тут не буду гадать.

После создания сервера у вас будут: **IP-адрес**, **логин** (обычно `root`)
и **пароль** (или SSH-ключ — если провайдер сам сгенерирует, сохраните его).

## 2. Подключиться по SSH с телефона

Поставьте приложение **Termius** (iOS/Android, бесплатное) — это SSH-клиент.
- Новое подключение → введите IP-адрес, логин `root`, пароль от сервера.
- Подключитесь — откроется терминал прямо на сервере.

Дальше все команды вводите там, в Termius.

## 3. Установить Python и зависимости

```bash
apt update && apt install -y python3 python3-pip git
```

## 4. Скопировать код бота на сервер

Проще всего — склонировать репозиторий (публичный, ключи не нужны):

```bash
git clone https://github.com/alexpilya1488-dotcom/Autopost.git /opt/autopost
cd /opt/autopost
pip3 install -r requirements.txt
```

## 5. Создать пользователя для запуска бота (не root, так безопаснее)

```bash
useradd -r -s /bin/false botrunner
chown -R botrunner:botrunner /opt/autopost
```

## 6. Создать файл с секретами

```bash
nano /opt/autopost/.env
```

Вставьте (замените на реальные значения — те же самые, что и в GitHub
Secrets для остальных ботов):

```
ASSISTANT_BOT_TOKEN=ваш_токен_бота
GEMINI_API_KEY=ваш_ключ
GROQ_API_KEY=ваш_ключ
```

Сохраните: `Ctrl+O`, `Enter`, потом `Ctrl+X` для выхода.

```bash
chmod 600 /opt/autopost/.env
chown botrunner:botrunner /opt/autopost/.env
```

## 7. Установить systemd-сервис (чтобы бот работал 24/7 и сам перезапускался)

```bash
cp /opt/autopost/deploy/assistant-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable assistant-bot
systemctl start assistant-bot
```

## 8. Проверить, что работает

```bash
systemctl status assistant-bot
```

Должно быть зелёное `active (running)`. Логи в реальном времени:

```bash
journalctl -u assistant-bot -f
```

(Выход из просмотра логов — `Ctrl+C`, сам бот при этом продолжит работать.)

Напишите боту `/start` в Telegram — должен ответить сразу (не через 15 минут,
как раньше).

## Обновление кода после того, как я пришлю новые изменения

```bash
cd /opt/autopost
git pull
systemctl restart assistant-bot
```

## Если что-то не работает

Пришлите вывод `systemctl status assistant-bot` и последние строки
`journalctl -u assistant-bot -n 50` — разберёмся по логам, как обычно.

### Ошибка "Network is unreachable" / бот не отвечает вообще

Если в логах видно `ConnectionError` / `Network is unreachable` при обращении
к `api.telegram.org`, а обычные сайты (`curl https://api.github.com`) при
этом открываются — значит сеть сервера блокирует именно Telegram (бывает у
некоторых хостеров). Решение — прокси через бесплатный Cloudflare Worker:

1. На cloudflare.com зарегистрируйте бесплатный аккаунт → **Workers & Pages**
   → **Create** → **Workers** → дайте имя, например `tg-proxy`.
2. В открывшемся редакторе кода замените содержимое на:
   ```js
   export default {
     async fetch(request) {
       const url = new URL(request.url);
       const target = "https://api.telegram.org" + url.pathname + url.search;
       const resp = await fetch(target, {
         method: request.method,
         headers: request.headers,
         body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(),
       });
       return new Response(resp.body, { status: resp.status, headers: resp.headers });
     },
   };
   ```
3. **Deploy**. Скопируйте адрес воркера (вида
   `https://tg-proxy.ваш-логин.workers.dev`).
4. На сервере откройте `.env` (`nano /opt/autopost/.env`) и добавьте строку
   (замените на свой адрес воркера, плейсхолдеры `{token}`/`{method}` — как
   есть, не менять):
   ```
   TELEGRAM_API_BASE=https://tg-proxy.ваш-логин.workers.dev/bot{token}/{method}
   ```
5. Сохраните, затем `git pull && systemctl restart assistant-bot`.
