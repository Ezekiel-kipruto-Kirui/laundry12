from twilio.rest import Client
account_sid = 'ACfc9ecbb175421404e332998629ac2f7d'
auth_token = '[AuthToken]'
client = Client(account_sid, auth_token)
message = client.messages.create(
  messaging_service_sid='MG18ea6033e13457302b919d53c946d2b2',
  body='Hellow this is Clean page Laundry',
  to='+254701396967'
)
print(message.sid)