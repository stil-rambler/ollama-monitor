# Ollama Monitor

**Система мониторинга Ollama: веб-интерфейс, API-прокси, аналитика производительности LLM и мониторинг GPU.**

Помогает анализировать работу языковых моделей: скорость генерации, обработку контекста, запросы от приложений-клиентов и использование аппаратных ресурсов.

- Веб-интерфейс: `http://localhost:8881`
- Прокси Ollama API: `http://localhost:8881/api/`
- OpenAI-совместимый API: `http://localhost:8881/v1/`
- Оригинальный Ollama: `http://localhost:11434`

---
Для того что бы мониторинг работал обязательно надо пользоваться прокси то есть в настройках точки входа надо указывать http://127.0.0.1:8881/v1 а не http://localhost:11434/v1. Иначе работать не чего не будет да и откуда она возмет информацию о скорости работы. 
## Возможности
<img width="1878" height="1040" alt="image" src="https://github.com/user-attachments/assets/d7847639-ce73-4eb1-a33e-108b309696dd" />
<img width="1869" height="1033" alt="image" src="https://github.com/user-attachments/assets/e63cd1ae-55a6-474f-91e7-ce471f3b69de" />
<img width="1911" height="1043" alt="image" src="https://github.com/user-attachments/assets/df9239ff-dbc0-4861-8da3-99d2becb9e34" />

### Мониторинг запросов
Для каждого запроса через прокси собираются: дата/время, модель, IP и имя клиента, endpoint, HTTP-статус, длительность, время загрузки модели, входные/выходные токены, скорость обработки контекста и генерации, время до первого байта, ошибки. Неизвестные показатели не подменяются фиктивными значениями.

### Мониторинг GPU (NVIDIA)
Загрузка GPU, температура, энергопотребление, используемая/свободная видеопамять, частоты. Поддержка нескольких видеокарт. Чтение через NVML с резервным вариантом через `nvidia-smi`.

### Мониторинг Ollama
Проверка доступности и версии сервера, список установленных моделей, модели в памяти, активные запросы, состояние/ошибки.

### Веб-интерфейс
Тёмная тема, вкладки Dashboard / Requests / Models / GPU / Clients / Logs / Settings. Живые графики (Chart.js) обновляются через WebSocket без перезагрузки страницы. Детализация запросов, сравнение моделей, фильтры и экспорт.

### API-прокси
Прозрачный прокси для `/api/*` и OpenAI-совместимого `/v1/*`, поддержка потоковой передачи (NDJSON/SSE), корректный сбор статистики из потока.

---

## Быстрый старт

Требуется Python 3.11+ и запущенный [Ollama](https://ollama.com) на `http://127.0.0.1:11434`.

```bash
pip install -r requirements.txt
python main.py
```

Откройте `http://localhost:8881`.

На Windows можно использовать `start.bat` (создаёт `.venv` при необходимости и ставит зависимости).

## Тесты

```bash
python -m pytest tests -v
```

## Конфигурация

Настройки — в `config.yaml` (порт, адрес Ollama, интервалы мониторинга, политика хранения, тема/язык UI). Любой параметр можно переопределить переменными окружения с префиксом `OLLAMA_MONITOR_*` (например, `OLLAMA_MONITOR_SERVER__PORT`).

## Структура

```
main.py                     # Точка входа FastAPI
app/
  config.py                 # Конфигурация (config.yaml + env)
  database.py               # Модели БД, сессия SQLAlchemy (async)
  schemas.py                # Pydantic-схемы
  api/                      # Эндпоинты REST
  proxy/                    # Прозрачный прокси к Ollama, парсер потока
  monitoring/               # GPU / Ollama / система / логи
  services/                 # RequestTracker, WebSocketManager
  static/, templates/       # Веб-интерфейс
tests/                      # Автотесты (pytest)
```

Поддержи разработчика https://kolektiv2.ru/lmstudio/donate.html?app=scidata



## Лицензия

MIT

Copyright (c) 2026 <Ollama Monitor>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

