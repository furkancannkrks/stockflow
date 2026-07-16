import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from django.db import OperationalError


pytestmark = pytest.mark.django_db
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def settings_process(settings_module, **overrides):
    environment = os.environ.copy()
    for name in [
        "DJANGO_SECRET_KEY",
        "DJANGO_DEBUG",
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "DB_HOST",
        "DB_PORT",
    ]:
        environment.pop(name, None)
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": settings_module,
            "DJANGO_LOAD_DOTENV": "False",
            **overrides,
        }
    )
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import django; django.setup(); "
                "from django.conf import settings; "
                "print(settings.DEBUG, settings.SECRET_KEY, "
                "settings.SECURE_SSL_REDIRECT, "
                "settings.SESSION_COOKIE_SECURE, "
                "settings.CSRF_COOKIE_SECURE)"
            ),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def production_environment():
    return {
        "DJANGO_SECRET_KEY": "production-test-secret-" + ("abcdef123456" * 4),
        "DJANGO_ALLOWED_HOSTS": "stockflow.example.com",
        "DB_NAME": "stockflow",
        "DB_USER": "stockflow",
        "DB_PASSWORD": "not-a-real-production-password",
        "DB_HOST": "db",
    }


def test_health_check_reports_database_readiness(client):
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_check_returns_503_when_database_is_unavailable(client):
    with patch(
        "config.urls.connection.cursor",
        side_effect=OperationalError("database unavailable"),
    ):
        response = client.get("/health/")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "database": "unavailable",
    }


def test_development_settings_keep_local_defaults():
    result = settings_process("config.settings")

    assert result.returncode == 0
    assert "True django-insecure-stockflow-development-key-change-me" in result.stdout


def test_production_settings_require_secret_key():
    result = settings_process(
        "config.settings_production",
        **{
            key: value
            for key, value in production_environment().items()
            if key != "DJANGO_SECRET_KEY"
        },
    )

    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY is required in production" in result.stderr


def test_production_settings_use_secure_defaults():
    result = settings_process(
        "config.settings_production",
        **production_environment(),
    )

    assert result.returncode == 0
    assert result.stdout.startswith("False production-test-secret-")
    assert result.stdout.rstrip().endswith("True True True")


def test_production_settings_reject_debug_true():
    result = settings_process(
        "config.settings_production",
        **production_environment(),
        DJANGO_DEBUG="True",
    )

    assert result.returncode != 0
    assert "DJANGO_DEBUG must be false in production" in result.stderr
