FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# entrypoint.sh needs the exec bit and an LF shebang. Git does not reliably
# record the mode on Windows and a CRLF checkout would make the kernel search
# for "/bin/sh\r", so normalise both here instead of trusting the checkout.
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

EXPOSE 5000

# Migrations and the poll seed run before the server binds, so the schema is real
# by the time /health answers and the worker is allowed to start.
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
