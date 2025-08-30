from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def send_sms(to_number, body_text):
    """
    Sends an SMS message using the Twilio API and provides detailed feedback.
    
    Returns a tuple: (success, message)
    - success (bool): True if the message was queued successfully, False otherwise.
    - message (str): A success message or a detailed error message.
    """
    try:
        # Get Twilio credentials from settings
        account_sid = settings.TWILIO_ACCOUNT_SID
        auth_token = settings.TWILIO_AUTH_TOKEN
        twilio_number = settings.TWILIO_PHONE_NUMBER
        
        # Initialize the Twilio client
        client = Client(account_sid, auth_token)
        
        # Create and send the message
        message = client.messages.create(
            to=to_number,
            from_=twilio_number,
            body=body_text
        )
        logger.info(f"SMS queued successfully to {to_number}. SID: {message.sid}")
        return True, f"SMS queued successfully. SID: {message.sid}"
    
    except TwilioRestException as e:
        error_message = f"Twilio API Error (Code {e.code}): {e.msg}"
        logger.error(error_message)
        return False, error_message
        
    except Exception as e:
        error_message = f"Unexpected error sending SMS: {e}"
        logger.error(error_message)
        return False, error_message