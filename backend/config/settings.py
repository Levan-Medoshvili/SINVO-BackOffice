"""SimplePOS settings. Secrets and deployment choices come from the environment."""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from .database import database_config

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get("SIMPLEPOS_DEBUG", "0") == "1"
SECRET_KEY = os.environ.get("SIMPLEPOS_SECRET_KEY", "")
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("Set SIMPLEPOS_SECRET_KEY to a random value of at least 50 characters.")
ALLOWED_HOSTS = [v.strip() for v in os.environ.get("SIMPLEPOS_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if v.strip()]
CSRF_TRUSTED_ORIGINS = [v.strip() for v in os.environ.get("SIMPLEPOS_CSRF_ORIGINS", "").split(",") if v.strip()]
DATA_DIR = Path(os.environ.get("SIMPLEPOS_DATA_DIR", BASE_DIR / "var"))
DATABASES = {"default": database_config(os.environ, DATA_DIR)}
AUTH_USER_MODEL = "users.User"
AUTHENTICATION_BACKENDS = ['commerce.directory.LocalBackend', 'commerce.directory.DirectoryBackend']
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "rest_framework", "users", "commerce", "backoffice",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages", "django.template.context_processors.i18n", "backoffice.access.shell"]}}]
WSGI_APPLICATION = "config.wsgi.application"
AUTH_PASSWORD_VALIDATORS = [{"NAME": "django.contrib.auth.password_validation." + name} for name in [
    "UserAttributeSimilarityValidator", "MinimumLengthValidator", "CommonPasswordValidator", "NumericPasswordValidator"]]
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("ka", "ქართული")]
TIME_ZONE = "Asia/Tbilisi"
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / "locale"]
STATIC_URL = "/static/"
STATIC_ROOT = Path(os.environ.get("SIMPLEPOS_STATIC_ROOT", DATA_DIR / "static"))
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"}}
MEDIA_URL = "/media/"
MEDIA_ROOT = DATA_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
REST_FRAMEWORK = {"DEFAULT_AUTHENTICATION_CLASSES": ["commerce.authentication.RegisterAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["commerce.authentication.IsRegister"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"]}
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
SECURE_SSL_REDIRECT = os.environ.get("SIMPLEPOS_HTTPS", "0" if DEBUG else "1") == "1"
SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = int(os.environ.get("SIMPLEPOS_HSTS_SECONDS", "0"))
SIMPLEPOS_BRAND = os.environ.get("SIMPLEPOS_BRAND", "SimplePOS")
SIMPLEPOS_BUILD_REVISION = os.environ.get("SIMPLEPOS_BUILD_REVISION", "development")
SIMPLEPOS_SETUP_TOKEN = os.environ.get("SIMPLEPOS_SETUP_TOKEN", "")
LOGIN_URL = "/login/"

SIMPLEPOS_OFFLINE_LOGIN_DAYS = int(os.environ.get("SIMPLEPOS_OFFLINE_LOGIN_DAYS", "7"))
if not 1 <= SIMPLEPOS_OFFLINE_LOGIN_DAYS <= 30:
    raise ImproperlyConfigured("SIMPLEPOS_OFFLINE_LOGIN_DAYS must be between 1 and 30.")
SIMPLEPOS_ALLOW_LEGACY_SALES = os.environ.get("SIMPLEPOS_ALLOW_LEGACY_SALES", "0") == "1"
SIMPLEPOS_RELEASE_DIR = Path(os.environ.get("SIMPLEPOS_RELEASE_DIR", DATA_DIR / "cashier-releases"))

SIMPLEPOS_RELEASE_PUBLIC_KEY = Path(os.environ.get("SIMPLEPOS_RELEASE_PUBLIC_KEY", "/etc/pos-erp/cashier-release-public.pem"))
