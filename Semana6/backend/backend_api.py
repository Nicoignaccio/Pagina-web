from fastapi import FastAPI

app = FastAPI(
    title="Backend API",
    description="API interna de productos y clientes (Fukusuke)"
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "Backend API"}


@app.get("/productos")
def get_productos():
    return {
        "productos": [
            {"id": 1, "nombre": "Roll California", "categoria": "Sushi", "precio": 6500, "disponible": True},
            {"id": 2, "nombre": "Ramen Tonkotsu", "categoria": "Sopas", "precio": 7200, "disponible": True}
        ]
    }

@app.get("/clientes")
def get_clientes():
    return {
        "clientes": [
            {"run": "12345678-9", "nombreCompleto": "Juan Pérez", "email": "juan@example.com", "comuna": "Providencia"}
        ]
    }