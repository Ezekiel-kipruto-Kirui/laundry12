from .base import *

DEBUG = env.bool('DJANGO_DEBUG',default=False)

NPM_BIN_PATH = env("NPM_BIN_PATH", default=None)
ALLOWED_HOSTS = []
