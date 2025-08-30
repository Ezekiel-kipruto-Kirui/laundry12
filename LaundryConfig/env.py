import environ
from pathlib import Path

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Initialise environment variables
env = environ.Env(
    DEBUG=(bool, False)   # Default False if not set in .env
)

# Read from .env file in BASE_DIR
environ.Env.read_env(BASE_DIR / ".env")
