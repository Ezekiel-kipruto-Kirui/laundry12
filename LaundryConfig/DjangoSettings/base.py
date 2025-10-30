"""
Django settings for LaundryConfig project (production-ready).

Adapted from your original settings with production hardening:
 - env-driven configuration (SECRET_KEY, DEBUG, DATABASE_URL, ALLOWED_HOSTS)
 - secure cookie, HSTS and SSL settings
 - whitenoise + compressed manifest static storage
 - single DATABASES definition (dj_database_url)
 - SMTP email config enabled only if env vars present
 - improved logging and ADMINS
"""

import os
from pathlib import Path
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from LaundryConfig.env import BASE_DIR, env  # you already have this env helper
import dj_database_url

# Base dir (keep your existing BASE_DIR from LaundryConfig.env if that is set)
# If BASE_DIR isn't provided by LaundryConfig.env, fallback:
if not globals().get('BASE_DIR'):
    BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Core - secrets & debug
# ---------------------------------------------------------------------------
SECRET_KEY = env('SECRET_KEY')  # MUST be set in environment (no default)

# Default to False in production. Allow opt-in via env var.
DEBUG = env.bool('DJANGO_DEBUG', default=False)

# ALLOWED_HOSTS: provide as comma-separated env var, fallback to your domains.
_allowed_hosts = os.getenv(
    'ALLOWED_HOSTS',
    'www.cleanpage.shop,cleanpage.shop,elite-laundry0010.onrender.com'
)
ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts.split(',') if h.strip()]

# CSRF trusted origins: accept HTTPS versions of hosts by default if not provided
_csrf_origins = os.getenv(
    'CSRF_TRUSTED_ORIGINS',
    ','.join([f'https://{h}' for h in ALLOWED_HOSTS if h and not h.startswith('http')])
)
CSRF_TRUSTED_ORIGINS = [u.strip() for u in _csrf_origins.split(',') if u.strip()]

# ---------------------------------------------------------------------------
# Database (single canonical configuration)
# ---------------------------------------------------------------------------
DATABASES = {
    'default': dj_database_url.config(
        default=os.getenv('DATABASE_URL'),  # IMPORTANT: set DATABASE_URL in environment
        conn_max_age=int(os.getenv('CONN_MAX_AGE', 600)),
        ssl_require=(os.getenv('DATABASE_SSL_REQUIRE', 'True').lower() in ('true', '1', 'yes')),
    )
}

# ---------------------------------------------------------------------------
# Applications & middleware
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    # Whitenoise (for static files)
    'whitenoise.runserver_nostatic',

    # Third-party apps
    'multiselectfield',
    'rest_framework',
    'unfold',
    'django_registration',
    'tailwind',           # if you use it in production
    'crispy_forms',
    'import_export',
    'django_daraja',
    'compressor',
    'widget_tweaks',

    # Django builtins
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    # Your apps
    'LaundryApp',
    'HotelApp',
    'theme',
    # Optional: OpenSSL if needed
    'OpenSSL',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Put whitenoise middleware high in the list so it can serve static files
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # Your custom middleware
    'LaundryApp.middleware.ActiveShopMiddleware',
]

# ---------------------------------------------------------------------------
# Auth & accounts
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = 'LaundryApp.UserProfile'
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'select_shop'
LOGOUT_REDIRECT_URL = '/accounts/login/'

ACCOUNT_ACTIVATION_DAYS = 7  # set appropriate activation window if you use django_registration
REGISTRATION_OPEN = True

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'LaundryApp.context_processors.active_shop',
            ],
            'builtins': [
                'django.contrib.humanize.templatetags.humanize',
            ],
        },
    },
]

ROOT_URLCONF = 'LaundryConfig.urls'
WSGI_APPLICATION = 'LaundryConfig.wsgi.application'

# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]

# ---------------------------------------------------------------------------
# Internationalization & timezone
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media (production)
# ---------------------------------------------------------------------------
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Keep local static dir for development/collectstatic discovery
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]

# Whitenoise compressed manifest storage (recommended for production)
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Optional: staticfiles finders for compressor if you use django-compressor
STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    'compressor.finders.CompressorFinder',
]

# ---------------------------------------------------------------------------
# Security hardening (HTTPS, cookies, HSTS, XSS protection)
# ---------------------------------------------------------------------------
# If running behind a proxy/load balancer that sets X-Forwarded-Proto
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Force HTTPS
SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'True').lower() in ('true', '1', 'yes')

# Cookies secure in production
SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'True').lower() in ('true', '1', 'yes')
CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', 'True').lower() in ('true', '1', 'yes')

# HSTS - enable and tune via env var
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', 60))  # start low while testing (60), increase to 31536000 once stable
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'True').lower() in ('true', '1', 'yes')
SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', 'False').lower() in ('true', '1', 'yes')

# Other headers
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'  # or SAMEORIGIN if you need framing for specific hosts

# ---------------------------------------------------------------------------
# Email (SMTP) - only active if credentials provided
# ---------------------------------------------------------------------------
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')

EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 'yes')
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', None)
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', None)
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER or 'webmaster@localhost')

# If EMAIL_HOST_USER or EMAIL_HOST_PASSWORD is missing, consider fallback to console backend (only for testing)
if not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD:
    # In production you should set EMAIL_HOST_USER and EMAIL_HOST_PASSWORD.
    # If absent, we fall back to console backend to avoid sending errors.
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# ---------------------------------------------------------------------------
# Django-rest-framework & third-party minimal settings (if used)
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    # Add production-safe defaults (adjust per your app)
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ],
}

# ---------------------------------------------------------------------------
# Defaults and misc
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = os.getenv('DEFAULT_AUTO_FIELD', 'django.db.models.BigAutoField')

# TAILWIND (only relevant if used)
TAILWIND_APP_NAME = os.getenv('TAILWIND_APP_NAME', 'theme')
TAILWIND_CONFIG_FILE = os.getenv('TAILWIND_CONFIG_FILE', 'tailwind.config.js')
TAILWIND_CSS_INPUT_FILE = os.getenv('TAILWIND_CSS_INPUT_FILE', 'src/input.css')
TAILWIND_CSS_OUTPUT_FILE = os.getenv('TAILWIND_CSS_OUTPUT_FILE', 'css/output.css')

CRISPY_ALLOWED_TEMPLATE_PACKS = "tailwind"
CRISPY_TEMPLATE_PACK = "tailwind"

# ---------------------------------------------------------------------------
# Admins / managers (for error emails & site owner contact)
# ---------------------------------------------------------------------------
ADMINS = [
    ('Admin', os.getenv('ADMIN_EMAIL', 'admin@cleanpage.shop')),
]
MANAGERS = ADMINS

# ---------------------------------------------------------------------------
# Logging - keep console output for Render/Heroku-like platforms
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '[{levelname}] {asctime} {name}: {message}', 'style': '{'},
        'simple': {'format': '[{levelname}] {message}', 'style': '{'},
    },
    'handlers': {
        'console': {
            'level': LOG_LEVEL,
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'LaundryApp': {
            'handlers': ['console'],
            'level': os.getenv('LAUNDRYAPP_LOG_LEVEL', 'DEBUG'),
            'propagate': False,
        },
    },
}

# ---------------------------------------------------------------------------
# Any other app-specific settings
# ---------------------------------------------------------------------------
# Context processors, template builtins and other settings remain as earlier
# If you need to keep any earlier custom settings, re-add below.

# ---------------------------------------------------------------------------
# Helpful runtime checks (optional) - raise if obviously insecure in production
# ---------------------------------------------------------------------------
if not DEBUG:
    if SECRET_KEY in (None, ''):
        raise RuntimeError('SECRET_KEY must be set in environment for production.')
    if 'localhost' in ALLOWED_HOSTS or '127.0.0.1' in ALLOWED_HOSTS:
        # It's OK to include localhost for testing but prefer actual domain names in production.
        pass

# End of settings
