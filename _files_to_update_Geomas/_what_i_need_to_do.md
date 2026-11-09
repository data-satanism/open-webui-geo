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
   NODE_OPTIONS=--max-old-space-size=8192 yarn build

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
                on:click={(e) => {
                    // свёрнутая полоса сайдбара разворачивается по любому клику
                    e.stopImmediatePropagation();
                }}
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

11. Дата-портал слева от чата (подробно — `docs/gis-portal.md`). В панели открывается Data_portal
    (`/run/media/karl/really_big_HDD/geo/Data_portal`), ассистент работает с ним инструментами `dp_*`.
    Новые файлы форка переносятся как есть:
    `src/lib/components/gis-portal/` (`GisPortalPanel.svelte`, `bridge.ts`, `bridge.test.ts`, `stores.ts`),
    `backend/open_webui/routers/gis_portal.py`, `backend/open_webui/utils/gis_portal_ticket.py` (в тикете есть `email`:
    по нему Data_portal находит аккаунт), `backend/open_webui/asgi.py`, `backend/tests/test_gis_portal_ticket.py`,
    `docs/gis-portal.md`. В чистом upstream `asgi.py` нет: файл целиком наш, он подключает роутер тикета перед SPA.
    Запускать только `open_webui.asgi:app`, `main.py` не трогать.
    В upstream-файлах вернуть швы:

    - `src/lib/constants.ts`: `export const GIS_PORTAL_URL = 'http://87.228.65.110:12000/';` рядом с `APP_NAME`.
    - `src/routes/(app)/+layout.svelte`: `import GisPortalPanel from '$lib/components/gis-portal/GisPortalPanel.svelte';`
      и `<GisPortalPanel />` внутри `{#if loaded}` прямо перед `<main class="contents">`.
    - `src/lib/components/chat/Navbar.svelte`: импорты `MapIcon` (`../icons/Map.svelte`), `GIS_PORTAL_URL`, `showGisPortal`
      и кнопка `{#if GIS_PORTAL_URL && !$mobile}` перед кнопкой Tabs (в 0.13 она заменила Controls).
    - Узкий чат рядом с порталом: импорт `gisPortalVisible` из `$lib/components/gis-portal/stores` и `px-1`
      вместо обычного отступа, пока портал открыт:
      `Messages/Message.svelte` (`px-3.5`), `MessageInput.svelte` (обёртки `px-3` и `px-2`),
      `Placeholder.svelte` (`px-1 md:@3xl:px-20` → `px-1`).
    - `src/lib/i18n/locales/ru-RU/translation.json` (и пустые в en-US): `Data portal`, `Hide data portal`,
      `Show data portal`, `Portal home`, `Linked to portal as`, `Not linked to portal`.
    - `.env.example`: закомментированный `GIS_PORTAL_SHARED_SECRET`.

    Окружение бэкенда: `GIS_PORTAL_SHARED_SECRET` — тот же, что `GEOMAS_SHARED_SECRET` в `.env` Data_portal. Без него
    панель работает, но окно портала входит по паролю. Со стороны Data_portal: `GEOMAS_ORIGINS` и `FRAME_ANCESTORS` —
    адрес Геомаса, «Email в Геомасе» у аккаунтов на `/admin`. Подключение API портала в Open WebUI
    (Admin -> External Tools: `http://87.228.65.110:12000/api/agent`, Bearer `GEOMAS_AGENT_KEY`,
    заголовок `{"X-User-Email": "{{USER_EMAIL}}"}`) — в `docs/gis-portal.md`.
12. Функции форка (geotizer, services, RAG, тесты, scripts, CI) переносятся не руками, а 3-way слиянием от чистого
    upstream. Так сделан переход 0.12.0 → 0.13.3 (коммит «Bring the fork's features from Geomas_ver_0.12.0 onto 0.13.3»):

    ```bash
    # теги upstream из локального клона open-webui (или с GitHub), имена ждёт scripts/check_upstream_footprint.py
    git fetch --depth 1 ../open-webui refs/tags/vOLD:refs/tags/upstream-vOLD refs/tags/vNEW:refs/tags/upstream-vNEW
    # theirs: ветка форка на старой версии без build/; ours: Init новой версии с шагами 1-11; база: upstream-vOLD
    git merge-tree --write-tree --name-only <Init с родителем upstream-vOLD> <форк без build/ с родителем upstream-vOLD>
    ```

    Обычный `git merge` старой ветки не работает: она уже предок `Init`, git ответит «Already up to date».
    После слияния: `scripts/upstream_ref.txt` → новая версия, `python3 scripts/check_upstream_footprint.py` зелёный,
    полный `backend/tests`. Конфликты бывают в шагах ритуала (значения взять из Init) и в швах форка в
    `routers/retrieval.py`, `tools/builtin.py`: переносить правку форка в новый код upstream, а не брать одну сторону.

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




