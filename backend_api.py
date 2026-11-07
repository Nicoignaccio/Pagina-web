from fastapi import FastAPI

app = FastAPI(
    title="**Backend API**",
    description="**API interna de productos y órdenes**"
)

@app.get("**health**")
def health():
    return {"status": "ok", "service": "Backend API"}

@app.get("**products**")
def get_products():
    return {
        "products": [
            {"id": 1, "name": "**Notebook**", "price": **900000**},
            {"id": 2, "name": "**Monitor**", "price": **250000**}
        ]
    }

@app.get("**orders**")
def get_orders():
    return {
        "orders": [
            {"id": 1001, "status": "**paid**"},
            {"id": 1002, "status": "**pending**"}
        ]
    }