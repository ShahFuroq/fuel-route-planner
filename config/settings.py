"""Django settings for the fuel route planner."""

import os
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> None:
    """Read KEY=value lines from .env into the environment, without overriding it."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


load_env_file(BASE_DIR / ".env")


def env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes"}


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "routing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Django's default ("same-origin") stops the browser sending a Referer to other
# sites. OpenStreetMap's tile servers require one, so the map page needs this.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"


def database_config() -> dict:
    """SQLite by default; set DATABASE_URL=postgres://user:pass@host:5432/name for PostgreSQL."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
    parsed = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
    }


DATABASES = {"default": database_config()}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

if os.environ.get("REDIS_URL"):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": os.environ["REDIS_URL"],
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "routing.errors.api_exception_handler",
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True
STATIC_URL = "static/"

# --- Route planner settings -------------------------------------------------

FUEL_PRICES_CSV = BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"
PLACES_FILE = BASE_DIR / "data" / "geonames_us_postal_codes.txt"

OSRM_BASE_URL = os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org")
OSRM_TIMEOUT_SECONDS = float(os.environ.get("OSRM_TIMEOUT_SECONDS", "15"))

VEHICLE_RANGE_MILES = 500.0
VEHICLE_MPG = 10.0

# Stations within this distance of the route count as "along the route". If a
# stretch has no reachable station, the search is retried once at the wider value.
CORRIDOR_MILES = 5.0
CORRIDOR_FALLBACK_MILES = 15.0

# With an empty tank the trip begins at the cheapest station within this distance
# of the start point (or the nearest station, if none is that close).
START_STATION_RADIUS_MILES = 10.0

# Dollar cost assigned to making a stop. It steers the optimizer away from many
# tiny purchases; it is never added to the reported fuel cost.
DEFAULT_STOP_PENALTY = float(os.environ.get("DEFAULT_STOP_PENALTY", "5"))

ROUTE_CACHE_SECONDS = 60 * 60 * 24
MAX_ROUTE_GEOJSON_POINTS = 1500
