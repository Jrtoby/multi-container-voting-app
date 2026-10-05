FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# entrypoint.sh needs the exec bit. Git does not reliably record it on Windows,
# so set it here rather than relying on the checkout mode.
RUN chmod +x entrypoint.sh

EXPOSE 5000

# Migrations and the poll seed run before the server binds, so the schema is real
# by the time /health answers and the worker is allowed to start.
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
