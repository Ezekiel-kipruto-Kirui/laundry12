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


# MPESA_ENVIRONMENT=sandbox

# MPESA_CONSUMER_KEY=isvuex4rkXsWv9QGJMGPGKqXEjnu2i00G00kEbvPKaTTEjkd

# MPESA_CONSUMER_SECRET=AkaRAOmowCKpBy1Zg0CRpGOcplLlGr2wmgviWqcfhAQ6hBv9mWvFrECioKsUKGl1

# MPESA_SHORTCODE=174379

# MPESA_EXPRESS_SHORTCODE=174379

# MPESA_SHORTCODE_TYPE=paybill

# MPESA_PASSKEY=bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919

# MPESA_INITIATOR_USERNAME=testapi

# MPESA_INITIATOR_SECURITY_CREDENTIAL=YutuOLLUeK/X9G5+qDOzS4YNnnq9Sr8OUFFz/g1htmyF8bridFC8wK/myBPPhMwca8YucIhxhkPiubrFvB4DzJ7C5LrogBjOw0dRU1glpobcMcx459bBZzrpK6iY1zfQk9CFUdZW4Omeor/wMcyNeU9iTYTANiIMlQ6clsvXiz3ADlwhslQCzf99l5x01FTQqZyuNqtZ3VfAR8zkZETx7gr7SAS69A9kZq79w1+vo6+OwweyfGAyJiSo2VVEmKzIpX0oB+x7X1bCyG8nSNlW7D+hYH5Rf/7D8qdE3yrgCgo52+IHDjnZDLPC6R5ErfI9qE20rxfQkDi90T+FLmSqKw==

