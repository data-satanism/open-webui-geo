# Список ритуалов для апдейта на новую версию

1. В `src/lib/constants.ts`:
   Поменять 
   ```ts
   export const APP_NAME = 'Geomas';
   ```

2. В `backend/open_webui/env.py` (примерно строка 93):

   Изменить на:

   ```py
   WEBUI_NAME = os.environ.get("WEBUI_NAME", "Geomas")
   ```
   И в следующей строке убрать автоизменение имени, иначе система откатит изменения 
   Удалить или закомментировать:

   ```py
   if WEBUI_NAME != "Open WebUI":
       WEBUI_NAME += " (Open WebUI)"
   ```
   и там же 

   ```py
    CHAT_RESPONSE_STREAM_DELTA_CHUNK_SIZE = 20
   ```

3. В `backend/open_webui/retrieval/loaders/mistral.py`:

   Поставить таймаут `3600` секунд в конструкторе класса - иначе OCR будет падать на больших файлах 

4. Обновить зависимости(пока что не нужно, оставил на будущее, если оно поломоется):

   ```bash
   pip install strenum
   ```

5. В `backend/open_webui/utils/plugin.py`:

   Добавить `return` в начале двух последних функций.
   Отключает автоапдейт некоторых пакетов, иначе система будет вместо запуска пытаться установить пакеты 

6. В `backend/open_webui/retrieval/vector/type.py`:
    Пока тоже не нужно
   ```py
   try:
       from enum import StrEnum  # Python 3.11+
   except ImportError:
       from strenum import StrEnum  # Backport for older Python
   ```

7. Заменить изображения в на изображения из папки в backend:

   - `static/`
   - `static/static`
   - `backend/open_webui/static`

   И заменить `Open WebUI` на `Geomas` в `index.html`.

8. Выполнить сборку фронтенда:
   yarn предпочтительнее npm

   ```bash
   yarn install
   yarn add @internationalized/date
   yarn run build
   ```

9. Убрать в `backend/open_webui/utils/tools.py`: -[ не надо!]

    - `view_file`
    - `view_knowledge_file`

10. В `src/lib/components/layout/Sidebar.svelte` добавить кнопку "Manual" (ссылка на мануал), ведущую на `http://87.228.65.110:8505/`:

    В блок импортов иконок добавить:
    ```svelte
    import HelpCircleIcon from './Sidebar/icons/HelpCircle.svelte';
    ```

    В свёрнутом (collapsed) виде сайдбара, рядом с остальными верхними иконками:
    ```svelte
    <div>
        <Tooltip content={$i18n.t('Manual')} placement="right">
            <a
                class=" cursor-pointer flex size-8 items-center justify-center transition group"
                href="http://87.228.65.110:8505/"
                target="_blank"
                rel="noopener noreferrer"
                draggable="false"
                aria-label={$i18n.t('Manual')}
            >
                <div
                    class="self-center flex size-[calc(30px*var(--app-text-scale,1))] items-center justify-center rounded-lg transition group-hover:bg-gray-100 dark:group-hover:bg-gray-900"
                >
                    <HelpCircleIcon className="size-4" strokeWidth="1.5" />
                </div>
            </a>
        </Tooltip>
    </div>
    ```

    В развёрнутом виде сайдбара, рядом с остальными нижними пунктами меню:
    ```svelte
    <div class="px-1 flex justify-center text-gray-700 dark:text-gray-300">
        <a
            id="sidebar-manual-button"
            class="group grow flex items-center space-x-2 rounded-xl px-2 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-900 transition outline-none"
            href="http://87.228.65.110:8505/"
            target="_blank"
            rel="noopener noreferrer"
            draggable="false"
            aria-label={$i18n.t('Manual')}
        >
            <div class="self-center flex size-4 shrink-0 items-center justify-center">
                <HelpCircleIcon strokeWidth="1.5" className="size-4" />
            </div>

            <div class="flex flex-1 self-center translate-y-[0.5px]">
                <div class=" self-center text-[0.8125rem] leading-5">{$i18n.t('Manual')}</div>
            </div>
        </a>
    </div>
    ```

    Адрес `87.228.65.110:8505` — захардкожен, поменять при смене сервера мануала.

## Обряды запуска

Необязательно - если в контейнере, где уже есть все зависимости
```bash
cd backend
python3.10 -m venv venv
./venv/bin/python3.10 -m pip install -r requirements.txt
```

ВСЕГДА ГЕНЕРИРОВАТЬ КЛЮЧ!!
```bash
echo "$(head -c 12 /dev/random | base64)" > .webui_secret_key


Тестовые запуск
PYTHONPATH=. WEBUI_SECRET_KEY="$(cat .webui_secret_key)" ./venv/bin/python3.11 -m uvicorn open_webui.main:app --host=212.41.21.72 --port 8503 --reload


ПРОД ЗАПУСК!!
export PYTHONPATH=. && export WEBUI_SECRET_KEY="$(cat .webui_secret_key)" && export RAG_SYSTEM_CONTEXT=True && export PYTHONUNBUFFERED=1 && exec ./venv/bin/python3.11 -u -m uvicorn open_webui.main:app --host 212.41.21.72 --port 8503 --reload > webui.log 2>&1


export PYTHONPATH=. && export WEBUI_SECRET_KEY="$(cat .webui_secret_key)" && export RAG_SYSTEM_CONTEXT=True && export PYTHONUNBUFFERED=1 && exec python3.11 -u -m uvicorn open_webui.asgi:app --host 87.228.65.110 --port 8503 --reload > webui.log 2>&1


export PYTHONPATH=. && export WEBUI_SECRET_KEY="$(cat .webui_secret_key)" && export RAG_SYSTEM_CONTEXT=True && export PYTHONUNBUFFERED=1 && exec python3.11 -u -m uvicorn open_webui.asgi:app --host 87.228.65.110 --port 9503 --reload 



ТЕСТ - ЗАПУСК В КОНТЕЙНЕРЕ, ПОКА НЕ ОТЛАЖЕНО СОВСЕМ
./venv/bin/python3.10 -m pip install youtube-transcript-api scholarly habanero arxiv openrouteservice pygments yfinance>=0.2.66 pandas>=2.2.0 pydantic>=2.0.0 requests>=2.28.0

docker compose -f _docker-compose.local.yml restart
docker compose -f _docker-compose.local.yml up --build
```

`// background`

**RUN INSIDE CONTAINER!!**

docker run -it --name balabanov_open_web --net=host -v /home/balabanov/:/home/ python:3.11 bash -f

python-docx openpyxl python-pptx aiohttp pdflatex weasyprint




