# Servidor do webhook de DM (docs/DM.md). A publicação continua no Actions;
# isto é só o processo que precisa ficar sempre no ar.
FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir "PyYAML>=6.0"

COPY poster/ poster/
COPY dm/ dm/

ENV PYTHONUNBUFFERED=1 \
    DM_DB=/data/dm.sqlite3 \
    PORT=8080
EXPOSE 8080

CMD ["python", "-m", "poster.dm"]
