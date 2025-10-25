import requests

url = "https://api.ng.termii.com/api/sms/send"

payload = {
    "to": "+254701396967",   # your phone number in full international format
    "from": "Clean-page",        # or your registered sender ID if you have one
    "sms": "Hello Ezekiel, this is a Termii live test!",
    "type": "plain",
    "channel": "generic",
    "api_key": "TLUequQQJyJswOQythPnCLonRiJSscPRbUnOYJMeblsLBuHAdXotDBVBdHKgTt"  # replace this with your real key
}

headers = {
    "Content-Type": "application/json"
}

response = requests.post(url, headers=headers, json=payload)

print("Status Code:", response.status_code)
print("Response:", response.text)
