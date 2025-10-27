# # from twilio.rest import Client
# # account_sid = 'ACfc9ecbb175421404e332998629ac2f7d'
# # auth_token = '[AuthToken]'
# # client = Client(account_sid, auth_token)
# # message = client.messages.create(
# #   messaging_service_sid='MG18ea6033e13457302b919d53c946d2b2',
# #   body='Hellow this is Clean page Laundry',
# #   to='+254701396967'
# # )
# # print(message.sid)
# from django.core.management.base import BaseCommand
# from LaundryApp.models import shoptype

# class Command(BaseCommand):
#     help = "Seed default shop types if they don't exist"

#     def handle(self, *args, **kwargs):
#         defaults = ["Shop A", "Shop B", "Hotel"]
#         for name in defaults:
#             obj, created = shoptype.objects.get_or_create(shoptype=name)
#             if created:
#                 self.stdout.write(self.style.SUCCESS(f"✅ Created: {name}"))
#             else:
#                 self.stdout.write(f"⚙️ Already exists: {name}")
# works with both python 2 and 3
from __future__ import print_function

import africastalking

class SMS:
  def __init__(self):
  # Set your app credentials
    self.username = "sandbox"
    self.api_key = "atsk_90e649b03ad0b6f1558119b0ef987f9b9b9b2fac81a93adef2d225feac871803fb4752fe"

      # Initialize the SDK
    africastalking.initialize(self.username, self.api_key)

      # Get the SMS service
    self.sms = africastalking.SMS

  def send(self):
          # Set the numbers you want to send to in international format
      recipients = ["+254701396967"]

      # Set your message
      message = "I'm a lumberjack and it's ok, I sleep all night and I work all day";

      # Set your shortCode or senderId
      sender = ""
      try:
  # Thats it, hit send and we'll take care of the rest.
          response = self.sms.send(message, recipients, sender)
          print (response)
      except Exception as e:
          print ('Encountered an error while sending: %s' % str(e))

if __name__ == '__main__':
    SMS().send()
