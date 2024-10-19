from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Path, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import mysql.connector
import os
from dotenv import load_dotenv
import bcrypt
import uuid
import jwt
from datetime import datetime, timedelta, timezone
from fastapi.middleware.cors import CORSMiddleware
import base64
from external.payment import get_payment_url
import random
origins = [
    "http://localhost:3000",
]
app = FastAPI()
load_dotenv()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]

)
SECRET_KEY = os.getenv("SECRET_KEY")
db_config = {
    "host": os.getenv("DB_URL"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "port": os.getenv("DB_PORT")
}

class Customer(BaseModel):
    userName: str
    email: str
    password: str

    
class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    
class Product(BaseModel):
    name: str
    description: str
    price: float
    availableItem: int
    
class Order(BaseModel):
    product_id: int
    quantity: int
    total_amount: float
    

class Shipment(BaseModel):
    id: int
    order_id: int
    shipment_status: str

class OrderLog(BaseModel):
    id: int
    order_id: int
    order_status: str

class ShipmentLog(BaseModel):
    id: int
    shipment_id: int
    shipment_status: str

class CustomerEditRequest(BaseModel):
    name: str = None
    shippingAddress: str = None
    email: str = None
    phone: str = None

class ShoppingCartItemResponse(BaseModel):
    product_id: int
    name: str
    quantity: int
    price: float
    
def get_db_connection():
    return mysql.connector.connect(**db_config)

def create_access_token(data: dict, expires_delta: timedelta = timedelta(days=30)):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm="HS256")
    return encoded_jwt, expire

async def get_current_user(x_token: str = Header(...)):
    payload = verify_token(x_token)
    return payload

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
def is_token_blacklisted(token: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM TokenBlacklist WHERE token = %s", (token))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result is not None


@app.post("/customers/")
def create_customer(customer: Customer):
    hashed_password = bcrypt.hashpw(customer.password.encode('utf-8'), bcrypt.gensalt())
    customer_uuid = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Customer (uuid, userName, email, password) VALUES (%s, %s, %s, %s)",
        (customer_uuid, customer.userName, customer.email, hashed_password.decode('utf-8'))
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "Customer created", "uuid": customer_uuid}

@app.post("/login", response_model=TokenResponse)
def login(login_request: LoginRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT uuid, password FROM Customer WHERE email = %s", (login_request.email,))
    customer = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if customer and bcrypt.checkpw(login_request.password.encode('utf-8'), customer[1].encode('utf-8')):
        access_token, expire = create_access_token(data={"sub": customer[0]})
        
        # Store the token in the Token table
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO Token (token, user_uuid, expiration_time) VALUES (%s, %s, %s)",
            (access_token, customer[0], expire)
        )
        conn.commit()
        cursor.close()
        conn.close()
        
        return {"access_token": access_token, "token_type": "bearer"}
    else:
        raise HTTPException(status_code=401, detail="Invalid email or password")

@app.put("/customer/{user_uuid}/edit", dependencies=[Depends(get_current_user)])
async def edit_customer(user_uuid: str, customer_edit: CustomerEditRequest, current_user: dict = Depends(get_current_user)):
    if current_user["sub"] != user_uuid:
        raise HTTPException(status_code=403, detail="You do not have permission to edit this user")

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        update_fields = []
        update_values = []

        if customer_edit.name is not None:
            update_fields.append("name = %s")
            update_values.append(customer_edit.name)

        if customer_edit.shippingAddress is not None:
            update_fields.append("shippingAddress = %s")
            update_values.append(customer_edit.shippingAddress)

        if customer_edit.email is not None:
            update_fields.append("email = %s")
            update_values.append(customer_edit.email)

        if customer_edit.phone is not None:
            update_fields.append("phone = %s")
            update_values.append(customer_edit.phone)

        if update_fields:
            update_values.append(user_uuid)
            update_query = f"UPDATE Customer SET {', '.join(update_fields)} WHERE uuid = %s"
            cursor.execute(update_query, tuple(update_values))
            conn.commit()

    except mysql.connector.Error as err:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {err}")
    finally:
        cursor.close()
        conn.close()

    return {"message": "Customer information updated successfully"}

@app.post("/logout", dependencies=[Depends(get_current_user)])
async def logout(x_token: str = Header(...), current_user: dict = Depends(get_current_user)):
    if is_token_blacklisted(x_token):
        raise HTTPException(status_code=401, detail="Token is already busted")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO TokenBlacklist (token, uuid) VALUES (%s, %s)",
        (x_token, current_user["sub"])
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "Successfully logged out"}
   
@app.get("/customers/{customer_uuid}", dependencies=[Depends(get_current_user)])
def get_customer(customer_uuid: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT uuid, userName, email FROM Customer WHERE uuid = %s", (customer_uuid,))
    customer = cursor.fetchone()
    cursor.close()
    conn.close()
    if customer:
        return {"uuid": customer[0], "userName": customer[1], "email": customer[2]}
    else:
        raise HTTPException(status_code=404, detail="Customer not found")


@app.post("/products/", dependencies=[Depends(get_current_user)])
async def create_product(
    name: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    image: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    image_data = await image.read()
    owner_uuid = current_user["sub"]
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Product (name, description, price, image, owner_uuid) VALUES (%s, %s, %s, %s, %s)",
        (name, description, price, image_data, owner_uuid)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "Product created"}

@app.get("/products/{product_id}", dependencies=[Depends(get_current_user)])
def get_product(product_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, description, price, availableItemCount, categoryId, owner_uuid, image FROM Product WHERE id = %s", (product_id,))
    product = cursor.fetchone()
    cursor.close()
    conn.close()
    if product:
        return {
            "id": product[0],
            "name": product[1],
            "description": product[2],
            "price": product[3],
            "availableItem": product[4],
            "categoryId": product[5],
            "owner": {
                "uuid": product[6]
            },
            "image": base64.b64encode(product[7]).decode('utf-8') if product[7] else None
        }
    else:
        raise HTTPException(status_code=404, detail="Product not found")
    
    
@app.put("/products/edit/{product_id}", dependencies=[Depends(get_current_user)])
async def edit_product(
    product_id: int,
    name: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    availableItem: int = Form(...),
    categoryIds: str = Form(...),  # Accept categoryIds as a comma-separated string
    image: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    image_data = await image.read()
    owner_uuid = current_user["sub"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT owner_uuid FROM Product WHERE id = %s", (product_id,))
    product = cursor.fetchone()
    if not product:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")
    
    if product[0] != owner_uuid:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=403, detail="You do not have permission to edit this product")
    
    cursor.execute(
        "UPDATE Product SET name = %s, description = %s, price = %s, availableItemCount = %s, image = %s WHERE id = %s",
        (name, description, price, availableItem, image_data, product_id)
    )
    
    # Update product-category mappings
    cursor.execute("DELETE FROM ProductCategoryMapping WHERE product_id = %s", (product_id,))
    try:
        category_ids = [int(cid) for cid in categoryIds.split(',')]
    except ValueError:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid category ID format")
    
    for category_id in category_ids:
        cursor.execute(
            "INSERT INTO ProductCategoryMapping (product_id, category_id) VALUES (%s, %s)",
            (product_id, category_id)
        )
    
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "Product updated successfully"}

@app.get("/allproducts")
def get_all_products():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Product")
    products = cursor.fetchall()
    cursor.close()
    conn.close()
    
    product_list = []
    for product in products:
        product_list.append({
            "id": product[0],
            "name": product[1],
            "description": product[2],
            "price": product[3],
            "availableItem": product[4],
            "categoryId": product[5],
            "owner": {
                "uuid": product[6]
            },
            "image": base64.b64encode(product[7]).decode('utf-8') if product[7] else None
        })
    
    return product_list

# Order endpoints
@app.post("/cart/add", dependencies=[Depends(get_current_user)])
async def add_to_cart(
    product_id: int = Form(...),
    quantity: int = Form(...),
    current_user: dict = Depends(get_current_user)
):
    user_uuid = current_user["sub"]

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if the user already has a cart
    cursor.execute("SELECT cartId FROM ShoppingCart WHERE owner = %s", (user_uuid,))
    cart = cursor.fetchone()

    if not cart:
        # Create a new cart for the user
        cursor.execute("INSERT INTO ShoppingCart (owner) VALUES (%s)", (user_uuid,))
        conn.commit()
        cart_id = cursor.lastrowid
    else:
        cart_id = cart[0]

    # Add item to the cart
    cursor.execute(
        "INSERT INTO ShoppingCartItem (cartId, productId, quantity) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)",
        (cart_id, product_id, quantity)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "Item added to cart"}

@app.get("/cart/", response_model=list[ShoppingCartItemResponse], dependencies=[Depends(get_current_user)])
async def get_cart(current_user: dict = Depends(get_current_user)):
    user_uuid = current_user["sub"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
    SELECT 
        sci.productId AS product_id, 
        p.name, 
        sci.quantity, 
        p.price
    FROM 
        ShoppingCartItem sci
    JOIN 
        Product p ON sci.productId = p.id
    WHERE 
        sci.cartId = (SELECT cartId FROM ShoppingCart WHERE owner = %s)
    """

    cursor.execute(query, (user_uuid,))
    cart_items = cursor.fetchall()

    cursor.close()
    conn.close()

    if not cart_items:
        raise HTTPException(status_code=404, detail="Cart is empty")

    return cart_items

@app.post("/cart/checkout", dependencies=[Depends(get_current_user)], response_class=HTMLResponse)
async def checkout_cart(cartId: int = Form(...), current_user: dict = Depends(get_current_user)):
    user_uuid = current_user["sub"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Get cart items
        cursor.execute("""
        SELECT 
            sci.productId AS product_id, 
            p.name, 
            p.price, 
            sci.quantity
        FROM 
            ShoppingCartItem sci
        JOIN 
            Product p ON sci.productId = p.id
        WHERE 
            sci.cartId = %s AND sci.cartId = (SELECT cartId FROM ShoppingCart WHERE owner = %s)
        """, (cartId, user_uuid))
        cart_items = cursor.fetchall()

        if not cart_items:
            cursor.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Cart is empty")

        # Convert Decimal to float
        for item in cart_items:
            item['price'] = float(item['price'])

        # Calculate total amount
        total_amount = sum(item['price'] * item['quantity'] for item in cart_items)

        # Generate a unique 5-digit order number
        while True:
            order_number = random.randint(10000, 99999)
            cursor.execute("SELECT 1 FROM CustomerOrder WHERE orderNumber = %s", (order_number,))
            if not cursor.fetchone():
                break

        # Create order
        cursor.execute(
            "INSERT INTO CustomerOrder (orderNumber, total_amount, status, customer) VALUES (%s, %s, %s, %s)",
            (order_number, total_amount, 'Pending', user_uuid)
        )
        order_id = cursor.lastrowid

        # Add items to orderItems
        for item in cart_items:
            cursor.execute(
                "INSERT INTO orderItems (orderId, productId, quantity, price) VALUES (%s, %s, %s, %s)",
                (order_id, item['product_id'], item['quantity'], item['price'])
            )

        # Clear the cart
        cursor.execute("DELETE FROM ShoppingCartItem WHERE cartId = %s", (cartId,))
        conn.commit()

        # Get customer details
        cursor.execute("SELECT userName, email, phone FROM Customer WHERE uuid = %s", (user_uuid,))
        customer = cursor.fetchone()

    except mysql.connector.Error as err:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {err}")
    finally:
        cursor.close()
        conn.close()

    customer_details = {
        "first_name": customer['userName'].split()[0],
        "last_name": " ".join(customer['userName'].split()[1:]),
        "email": customer['email'],
        "phone": customer['phone']
    }

    # Get payment URL from Midtrans
    payment_url = get_payment_url(order_number, total_amount, customer_details)

    # Generate HTML receipt
    receipt_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Receipt</title>
        <style>
            body {{ font-family: Arial, sans-serif; }}
            .receipt-container {{ max-width: 600px; margin: auto; padding: 20px; border: 1px solid #ccc; }}
            .receipt-header {{ text-align: center; }}
            .receipt-details {{ margin-top: 20px; }}
            .receipt-details table {{ width: 100%; border-collapse: collapse; }}
            .receipt-details th, .receipt-details td {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
            .receipt-footer {{ margin-top: 20px; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="receipt-container">
            <div class="receipt-header">
                <h1>Receipt</h1>
                <p>Order Number: {order_number}</p>
                <p>Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
            <div class="receipt-details">
                <h2>Customer Details</h2>
                <p>Name: {customer['userName']}</p>
                <p>Email: {customer['email']}</p>
                <p>Phone: {customer['phone']}</p>
                <h2>Order Details</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Product</th>
                            <th>Quantity</th>
                            <th>Price</th>
                            <th>Total</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(f"<tr><td>{item['name']}</td><td>{item['quantity']}</td><td>{item['price']}</td><td>{item['price'] * item['quantity']}</td></tr>" for item in cart_items)}
                    </tbody>
                </table>
                <h2>Total Amount: {total_amount}</h2>
            </div>
            <div class="receipt-footer">
                <p>Thank you for your purchase!</p>
                <p><a href="{payment_url}" target="_blank">Proceed to Payment</a></p>
            </div>
        </div>
    </body>
    </html>
    """

    return HTMLResponse(content=receipt_html)

# Shipment endpoints
@app.post("/shipments/", dependencies=[Depends(get_current_user)])
def create_shipment(shipment: Shipment, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Shipment (id, order_id, shipment_status) VALUES (%s, %s, %s)",
        (shipment.id, shipment.order_id, shipment.shipment_status)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "Shipment created"}



@app.get("/shipments/{shipment_id}", dependencies=[Depends(get_current_user)])
def get_shipment(shipment_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Shipment WHERE id = %s", (shipment_id,))
    shipment = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if shipment:
        return {"id": shipment[0], "order_id": shipment[1], "shipment_status": shipment[2]}
    raise HTTPException(status_code=404, detail="Shipment not found")

# OrderLog endpoints
@app.post("/orderlogs/", dependencies=[Depends(get_current_user)])
def create_orderlog(order_log: OrderLog, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO OrderLog (id, order_id, order_status) VALUES (%s, %s, %s)",
        (order_log.id, order_log.order_id, order_log.order_status)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "OrderLog created"}

@app.get("/orderlogs/{orderlog_id}", dependencies=[Depends(get_current_user)])
def get_orderlog(orderlog_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM OrderLog WHERE id = %s", (orderlog_id,))
    order_log = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if order_log:
        return {"id": order_log[0], "order_id": order_log[1], "order_status": order_log[2]}
    raise HTTPException(status_code=404, detail="OrderLog not found")

# ShipmentLog endpoints
@app.post("/shipmentlogs/", dependencies=[Depends(get_current_user)])
def create_shipmentlog(shipment_log: ShipmentLog, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO ShipmentLog (id, shipment_id, shipment_status) VALUES (%s, %s, %s)",
        (shipment_log.id, shipment_log.shipment_id, shipment_log.shipment_status)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "ShipmentLog created"}

@app.get("/shipmentlogs/{shipmentlog_id}", dependencies=[Depends(get_current_user)])
def get_shipmentlog(shipmentlog_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ShipmentLog WHERE id = %s", (shipmentlog_id,))
    shipment_log = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if shipment_log:
        return {"id": shipment_log[0], "shipment_id": shipment_log[1], "shipment_status": shipment_log[2]}
    raise HTTPException(status_code=404, detail="ShipmentLog not found")


@app.get('/api')
def api():
    return {"message": "Welcome to the API"}
if __name__ == "__main__":
    import uvicorn