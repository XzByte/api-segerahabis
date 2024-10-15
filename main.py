from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Path, Form
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
    id: int
    customer_id: int
    product_id: int
    order_status: str

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
    
    # Update the product
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
@app.post("/cart/", dependencies=[Depends(get_current_user)])
def create_order(order: Order, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Orders (id, customer_id, product_id, order_status) VALUES (%s, %s, %s, %s)",
        (order.id, order.customer_id, order.product_id, order.order_status)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "Order created"}

@app.get("/cart/{order_id}", dependencies=[Depends(get_current_user)])
def get_cart(order_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Orders WHERE id = %s", (order_id,))
    order = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if order:
        return {"id": order[0], "customer_id": order[1], "product_id": order[2], "order_status": order[3]}
    raise HTTPException(status_code=404, detail="Order not found")

@app.post("/cart/{user_uuid}/checkout", dependencies=[Depends(get_current_user)])
def checkout_cart(user_uuid: str, current_user: dict = Depends(get_current_user)):
    if user_uuid != current_user["sub"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch cart items
    cursor.execute("SELECT product_id, quantity FROM CartItem WHERE user_uuid = %s", (user_uuid,))
    cart_items = cursor.fetchall()

    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # Create order
    order_uuid = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO `Order` (uuid, user_uuid, created_at) VALUES (%s, %s, %s)",
        (order_uuid, user_uuid, datetime.now(datetime.timezone.utc))
    )
    conn.commit()

    # Add items to order and calculate total
    total_amount = 0
    for item in cart_items:
        product_id, quantity = item
        cursor.execute("SELECT price FROM Product WHERE id = %s", (product_id,))
        product = cursor.fetchone()
        if product:
            price = product[0]
            total_amount += price * quantity
            cursor.execute(
                "INSERT INTO OrderItem (order_uuid, product_id, quantity, price) VALUES (%s, %s, %s, %s)",
                (order_uuid, product_id, quantity, price)
            )
        else:
            raise HTTPException(status_code=404, detail=f"Product with id {product_id} not found")

    conn.commit()

    # Clear cart
    cursor.execute("DELETE FROM CartItem WHERE user_uuid = %s", (user_uuid,))
    conn.commit()

    cursor.close()
    conn.close()

    # Generate receipt
    receipt = {
        "order_uuid": order_uuid,
        "user_uuid": user_uuid,
        "total_amount": total_amount,
        "items": [{"product_id": item[0], "quantity": item[1]} for item in cart_items],
        "created_at": datetime.now(timezone.utc)
    }

    return receipt


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