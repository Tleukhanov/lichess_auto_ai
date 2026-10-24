FROM python:3.12-slim
WORKDIR /app
COPY whatsapp_auto/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY whatsapp_auto/ ./whatsapp_auto/
# backend нужен api-контейнеру для синка результатов турниров (announce.py)
COPY backend/lichess_auto/ ./backend/lichess_auto/
COPY backend/db/results.py backend/db/members.py ./backend/db/
EXPOSE 5000
CMD ["python", "-m", "whatsapp_auto.bot"]
