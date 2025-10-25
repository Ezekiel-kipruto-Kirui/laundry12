import requests
import json
import logging
from django.conf import settings
from LaundryConfig.env import env

logger = logging.getLogger(__name__)

TERMII_SMS_URL = "https://api.ng.termii.com/api/sms/send"

def send_sms(to_number, message):
    """
    Send SMS via Termii API
    """
    try:
        api_key = env("TERMII_API_KEY")
        sender_id = env("TERMII_SENDER_ID")       
        if not api_key:
            raise ValueError("⚠️ Missing TERMII_API_KEY in Django settings")

        payload = {
            "to": to_number,
            "from": sender_id,
            "sms": message,
            "type": "plain",
            "channel": "generic",  # Can be 'dnd', 'whatsapp', or 'generic'
            "api_key": api_key,
        }

        headers = {"Content-Type": "application/json"}

        logger.info(f"📤 Sending SMS to {to_number}: {message}")

        response = requests.post(
            TERMII_SMS_URL,
            headers=headers,
            data=json.dumps(payload),
            timeout=20
        )

        # Parse the response
        if response.status_code in [200, 201]:
            data = response.json()
            if data.get("code") == "ok":
                logger.info(f"✅ SMS sent successfully to {to_number}")
                return True, f"SMS sent successfully to {to_number}"
            else:
                logger.error(f"❌ SMS failed: {data}")
                return False, f"Failed to send SMS: {data}"
        else:
            logger.error(f"❌ HTTP Error ({response.status_code}): {response.text}")
            return False, f"HTTP Error {response.status_code}: {response.text}"

    except requests.exceptions.Timeout:
        logger.error("⏰ Request to Termii API timed out")
        return False, "Request timeout"
    except Exception as e:
        logger.error(f"⚠️ Unexpected error sending SMS via Termii: {e}")
        return False, str(e)
