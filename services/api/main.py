from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import products, conversations
from dependencies.auth import get_current_tenant

app = FastAPI(title="Commerce Ops Core API", description="Síncrona REST")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Ajustar a dominio en produccion
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products.router, prefix="/api/v1/products")
app.include_router(conversations.router, prefix="/api/v1/conversations")

@app.get("/health")
def health_check():
    return {"status": "ok"}\n