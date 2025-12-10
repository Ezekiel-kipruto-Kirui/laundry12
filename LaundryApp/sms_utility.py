import logging
from django.conf import settings
from twilio.rest import Client
from LaundryConfig.env import env

logger = logging.getLogger(__name__)

def send_sms(to_number, message):
    """
    Send SMS via Twilio API
    """
    try:
        account_sid = env("TWILIO_ACCOUNT_SID")
        auth_token = env("TWILIO_AUTH_TOKEN")
        messaging_service_sid = env("TWILIO_MESSAGING_SERVICE_SID")

        if not account_sid or not auth_token or not messaging_service_sid:
            raise ValueError("⚠️ Missing Twilio credentials in environment variables")

        client = Client(account_sid, auth_token)

        logger.info(f"📤 Sending SMS to {to_number}: {message}")

        message_obj = client.messages.create(
            messaging_service_sid=messaging_service_sid,
            body=message,
            to=to_number   # Must be in +E164 format (+2547...)
        )

        logger.info(f"✅ SMS sent successfully to {to_number}, SID: {message_obj.sid}")
        return True, f"SMS sent successfully ({message_obj.sid})"

    except Exception as e:
        logger.error(f"❌ Twilio SMS send failed: {e}")
        return False, str(e)
