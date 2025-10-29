from .base import *

DEBUG = env.bool('DJANGO_DEBUG',default=False)

# NPM_BIN_PATH = env("NPM_BIN_PATH", default=None)
ALLOWED_HOSTS = ['www.cleanpage.shop','cleanpage.shop','elite-laundry0010.onrender.com']
CSRF_TRUSTED_ORIGINS = [
    'https://www.cleanpage.shop',
    'https://cleanpage.shop',
    'https://elite-laundry0010.onrender.com'
]
DATABASES = {
    'default': dj_database_url.config(
        default=os.getenv('DATABASE_URL'),
        conn_max_age=600,
    )
}

