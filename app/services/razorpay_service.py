import os
from dotenv import find_dotenv, load_dotenv
import razorpay

load_dotenv(find_dotenv())

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
    raise RuntimeError("Missing RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET in environment variables.")

client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


def create_razorpay_order(amount_rupees: float, receipt: str):
    amount_paise = round(amount_rupees * 100)

    data = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": receipt
    }

    return client.order.create(data=data)
