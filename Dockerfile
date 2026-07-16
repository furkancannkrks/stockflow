FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system stockflow \
    && adduser --system --ingroup stockflow stockflow

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=stockflow:stockflow . .

USER stockflow

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
