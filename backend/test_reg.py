import requests
resp = requests.post('http://127.0.0.1:8000/register', json={"username": "mudii", "email": "mudii@example.com", "password": "mudii123"})
print(resp.status_code)
print(resp.text)
