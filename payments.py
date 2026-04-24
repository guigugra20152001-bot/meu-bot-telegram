import os, requests
from database import Database

db = Database()

class PaymentManager:
    def __init__(self):
        self.token = os.getenv("MERCADO_PAGO_TOKEN", "")
        self.base_url = "https://api.mercadopago.com"

    def create_pix_payment(self, amount: float, user_id: int) -> dict | None:
        if not self.token:
            return None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": f"pix-{user_id}-{int(amount*100)}-{os.urandom(4).hex()}"
        }
        payload = {
            "transaction_amount": amount,
            "payment_method_id": "pix",
            "description": "Recarga de saldo - Loja Digital",
            "payer": {"email": f"user{user_id}@lojadigital.com"}
        }
        try:
            r = requests.post(f"{self.base_url}/v1/payments", json=payload, headers=headers, timeout=15)
            data = r.json()
            if r.status_code in (200, 201):
                pix_data = data["point_of_interaction"]["transaction_data"]
                payment_id = str(data["id"])
                db.create_payment(user_id, amount, payment_id)
                return {
                    "payment_id": payment_id,
                    "qr_code": pix_data.get("qr_code"),
                    "qr_code_base64": pix_data.get("qr_code_base64"),
                    "amount": amount
                }
        except Exception as e:
            print(f"Erro PIX: {e}")
        return None

    def check_payment(self, payment_id: str, user_id: int) -> dict:
        if not self.token:
            return {"status": "error"}
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            r = requests.get(f"{self.base_url}/v1/payments/{payment_id}", headers=headers, timeout=10)
            data = r.json()
            status = data.get("status", "pending")
            if status == "approved":
                pay = db.complete_payment(payment_id)
                if pay:
                    return {"status": "approved", "amount": pay["amount"]}
            return {"status": status}
        except Exception as e:
            print(f"Erro check: {e}")
            return {"status": "error"}

    def process_webhook(self, data: dict):
        if data.get("type") == "payment":
            payment_id = str(data.get("data", {}).get("id", ""))
            if payment_id:
                db.complete_payment(payment_id)
