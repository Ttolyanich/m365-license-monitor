FROM python:3.12-slim

# Установка рабочей директории
WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода приложения
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY Export-M365UsersInfo.ps1 .

# FastAPI порт
EXPOSE 8000

# Запуск приложения
# СУБД SQLite (monitor.db) создается в директории /app/backend.
# Для сохранения данных при перезапуске контейнера рекомендуется монтировать volume на /app/backend
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
