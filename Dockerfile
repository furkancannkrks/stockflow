FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings_production

WORKDIR /app

RUN addgroup --system stockflow \
    && adduser --system --ingroup stockflow stockflow

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=stockflow:stockflow . .
RUN mkdir -p /app/staticfiles \
    && chown stockflow:stockflow /app/staticfiles

USER stockflow

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-"]
