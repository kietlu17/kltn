import requests


url = "http://localhost:3000/assistant/chat"
questions = [
    "loa bluetooth",
    "so sánh Loa Bluetooth Monster Adventurer FORCE và Loa Bluetooth Alpha Works AW-Ride",
    "Tôi đặt trên bàn học, theo bạn nên lấy mẫu nào?",
    "Nếu tôi coi trọng giá hơn thì sao?",
]
session_id = None
for turn, question in enumerate(questions, 1):
    payload = {"message": question}
    if session_id:
        payload["sessionId"] = session_id
    response = requests.post(url, json=payload, timeout=160)
    data = response.json()
    session_id = data.get("sessionId", session_id)
    print("TURN", turn, "STATUS", response.status_code, "ROUTE", data.get("route"),
          "PRODUCTS", [item.get("name") for item in data.get("products", [])], flush=True)
    print("ANSWER", data.get("answer", data.get("detail")), flush=True)
