import os
import midtransclient
# from dotenv import load_dotenv

# load_dotenv()

def get_payment_url(order_id, gross_amount, customer_details):
    server_key = os.getenv('SERVER_KEY')

    if not server_key:
        raise ValueError("SERVER_KEY must be set in the environment variables")

    snap = midtransclient.Snap(
        is_production=False,  # Change to False if using sandbox keys
        server_key=server_key,
    )

    param = {
        "transaction_details": {
            "order_id": order_id,
            "gross_amount": gross_amount
        },
        "credit_card": {
            "secure": True
        },
        "customer_details": customer_details
    }

    transaction = snap.create_transaction(param)
    return transaction['redirect_url']