# pyright: reportArgumentType=false, reportCallIssue=false, reportAssignmentType=false
import logging
from datetime import timedelta

import environ
import structlog
from kombu import Queue

root = environ.Path(__file__) - 2

env = environ.Env(DEBUG=(bool, False))

env.read_env(root("../../.env"), overwrite=False)

ENV = env("ENV")


SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost"])
ROOT_URLCONF = "project.urls"
WSGI_APPLICATION = "project.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


INSTALLED_APPS = [
    "django_prometheus",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_extensions",
    "django_probes",
    "django_structlog",
    "abstract_block_dumper",
    "project.core",
    "apps.notifications",
    "apps.extrinsics",
    "apps.metagraph",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_structlog.middlewares.RequestMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [root("project/templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


DATABASES = {"default": env.db_url("DATABASE_URL")}


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_L10N = True
USE_TZ = True


STATIC_URL = env("STATIC_URL", default="/static/")
STATIC_ROOT = env("STATIC_ROOT", default=root("static"))
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
MEDIA_URL = env("MEDIA_URL", default="/media/")
MEDIA_ROOT = env("MEDIA_ROOT", default=root("media"))

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if CORS_ENABLED := env.bool("CORS_ENABLED", default=True):
    INSTALLED_APPS.append("corsheaders")
    MIDDLEWARE = ["corsheaders.middleware.CorsMiddleware", *MIDDLEWARE]
    CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
    CORS_ALLOWED_ORIGIN_REGEXES = env.list("CORS_ALLOWED_ORIGIN_REGEXES", default=[])
    CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=False)

REDIS_HOST = env("REDIS_HOST")
REDIS_PORT = env.int("REDIS_PORT")
REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}"

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_RESULT_EXPIRES = int(timedelta(days=1).total_seconds())
CELERY_MESSAGE_COMPRESSION = "gzip"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"

CELERY_TASK_CREATE_MISSING_QUEUES = False
CELERY_TASK_QUEUES = (Queue("celery"), Queue("metagraph"))
CELERY_TASK_ANNOTATIONS = {"*": {"acks_late": True, "reject_on_worker_lost": True}}
CELERY_TASK_ROUTES = {
    "apps.metagraph.block_tasks.store_metagraph": {"queue": "metagraph"},
    "*": {"queue": "celery"},
}
CELERY_TASK_TIME_LIMIT = int(timedelta(minutes=5).total_seconds())
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = env.bool("CELERY_TASK_EAGER_PROPAGATES", default=False)

CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_SEND_SENT_EVENT = True
CELERY_WORKER_PREFETCH_MULTIPLIER = env.int("CELERY_WORKER_PREFETCH_MULTIPLIER", default=1)
CELERY_BROKER_POOL_LIMIT = env.int("CELERY_BROKER_POOL_LIMIT", default=50)
CELERY_WORKER_MAX_TASKS_PER_CHILD = env.int("CELERY_WORKER_MAX_TASKS_PER_CHILD", default=50)


DJANGO_STRUCTLOG_CELERY_ENABLED = True

LOG_LEVEL = env("LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "main": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.dev.ConsoleRenderer(),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "main",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "level": LOG_LEVEL,
            "propagate": True,
        },
        "django_structlog": {
            "level": LOG_LEVEL,
            "propagate": True,
        },
        "celery": {
            "level": LOG_LEVEL,
            "propagate": True,
        },
        "psycopg.pq": {
            "propagate": False,
        },
        "parso": {
            "level": "INFO",
        },
        "websockets": {
            "level": "WARNING",
        },
    },
}


def configure_structlog():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


configure_structlog()


SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration, ignore_logger
    from sentry_sdk.integrations.redis import RedisIntegration

    SENTRY_ENVIRONMENT = env("SENTRY_ENVIRONMENT", default=ENV)
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=SENTRY_ENVIRONMENT,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            RedisIntegration(),
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR,
            ),
        ],
    )
    ignore_logger("django.security.DisallowedHost")
    ignore_logger("django_structlog.celery.receivers")


PROMETHEUS_EXPORT_MIGRATIONS = env.bool("PROMETHEUS_EXPORT_MIGRATIONS", default=True)

# Bittensor / Block Dumper

BITTENSOR_NETWORK = env.str("BITTENSOR_NETWORK", default="finney")
PYLON_URL = env("PYLON_URL", default="http://localhost:8090")

BLOCK_DUMPER_START_FROM_BLOCK = "current"
BLOCK_DUMPER_POLL_INTERVAL = 5
BLOCK_TASK_RETRY_BACKOFF = 1
BLOCK_DUMPER_MAX_ATTEMPTS = 3
BLOCK_TASK_MAX_RETRY_DELAY_MINUTES = 1440

# Metagraph
METAGRAPH_NETUIDS: list[int] | None = env.list("METAGRAPH_NETUIDS", default=[], cast=int) or None
METAGRAPH_LITE = env.bool("METAGRAPH_LITE", default=False)


SENTINEL_STORAGES = {
    "local": {
        "BACKEND_NAME": "fsspec-local",
        "OPTIONS": {"base_path": str(MEDIA_ROOT)},
    },
    "s3": {
        "BACKEND_NAME": "fsspec-s3",
        "OPTIONS": {
            "bucket": env("SENTINEL_STORAGE_S3_BUCKET", default=""),
            "base_path": env("SENTINEL_STORAGE_S3_BASE_PATH", default=""),
            "aws_region": env("SENTINEL_STORAGE_S3_AWS_REGION", default=None),
            "aws_access_key_id": env("SENTINEL_STORAGE_S3_AWS_ACCESS_KEY_ID", default=None),
            "aws_secret_access_key": env("SENTINEL_STORAGE_S3_AWS_SECRET_ACCESS_KEY", default=None),
        },
    },
}

# Debug toolbar (dev only)
if DEBUG_TOOLBAR := env.bool("DEBUG_TOOLBAR", default=False):
    INTERNAL_IPS = ["127.0.0.1"]
    DEBUG_TOOLBAR_CONFIG = {"SHOW_TOOLBAR_CALLBACK": lambda _request: True}
    INSTALLED_APPS.append("debug_toolbar")
    MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware", *MIDDLEWARE]
