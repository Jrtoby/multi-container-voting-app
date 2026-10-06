import multiprocessing
import os

# Sourced from the environment so the same image can be tuned per deployment.
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:5000")
workers = int(os.getenv("GUNICORN_WORKERS", min(4, (multiprocessing.cpu_count() * 2) + 1)))
threads = int(os.getenv("GUNICORN_THREADS", "2"))
worker_class = "gthread"

# Vote submissions and the login rate limiter both wait on Redis, so a worker
# blocked there must not hold a slot indefinitely.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "30"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = 5

# Logs to stdout/stderr so Docker's json-file driver captures them unchanged.
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms "%(f)s" "%(a)s"'

preload_app = False


def when_ready(server):
    server.log.info("gunicorn ready: %s workers x %s threads on %s", workers, threads, bind)