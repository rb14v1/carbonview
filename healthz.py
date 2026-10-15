# Mount this router in your FastAPI app: app.include_router(router)
from fastapi import APIRouter

router = APIRouter()

@router.get("/healthz")
def healthz():
    return {"status": "ok"}
