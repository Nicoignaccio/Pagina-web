from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from contextlib import asynccontextmanager

MONGODB_URI = "mongodb://localhost:27017"
DB_NAME = "fukusuke_delivery"
COLL_NAME = "productos"

client: AsyncIOMotorClient = None
db = None
coll = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client, db, coll
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DB_NAME]
    coll = db[COLL_NAME]
    yield
    client.close()


app = FastAPI(
    title="Fukusuke Sushi API",
    version="1.0.0",
    lifespan=lifespan
)



class ProductoBase(BaseModel):
    nombre: str = Field(min_length=1, description="Nombre del roll o producto")
    precio: float = Field(gt=0, description="Precio mayor a 0")
    tags: List[str] = Field(default_factory=list, description="Categorías: rolls, handrolls, etc.")
    activo: bool = True

class ProductoIn(ProductoBase):
    pass

class ProductoOut(ProductoBase):
    id: str

# Función auxiliar de transformación 
def doc_to_producto_out(doc: dict) -> ProductoOut:
    return ProductoOut(
        id=str(doc["_id"]),
        nombre=doc["nombre"],
        precio=doc["precio"],
        tags=doc.get("tags", []),
        activo=doc.get("activo", True)
    )




@app.get("/health", tags=["Sistema"])
def health():
    return {"status": "ok"}


@app.get("/productos", response_model=List[ProductoOut], tags=["Productos"])
async def listar_productos(
    q: Optional[str] = Query(None, description="Filtrar por nombre que contenga q"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200)
):
    query = {}
    if q:
        query["nombre"] = {"$regex": q, "$options": "i"}

    cursor = coll.find(query).skip(skip).limit(limit)
    productos: List[ProductoOut] = []
    async for doc in cursor:
        productos.append(doc_to_producto_out(doc))
    return productos


@app.post("/productos", response_model=ProductoOut, status_code=201, tags=["Productos"])
async def crear_producto(item: ProductoIn):
    nuevo_doc = item.model_dump()
    resultado = await coll.insert_one(nuevo_doc)
    nuevo_doc["_id"] = resultado.inserted_id
    return doc_to_producto_out(nuevo_doc)