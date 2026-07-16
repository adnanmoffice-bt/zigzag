# ZigZag workeri — jedan image za sva tri procesa.
# Svaki Railway/Fly servis koristi isti image, samo mijenja start komandu:
#   listener:  python -m listener.telegram_listener
#   parser:    python -m parser.claude_parser
#   executor:  python -m executor.mt5_executor
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

# default proces; Railway servisi ga override-uju kroz Custom Start Command
CMD ["python", "-m", "listener.telegram_listener"]
