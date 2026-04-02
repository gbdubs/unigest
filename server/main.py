from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.config import get_settings
from server.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Unigest", version="0.1.0", lifespan=lifespan)

settings = get_settings()
if settings.DEV_MODE:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Register routers
from server.routes.jobs import router as jobs_router
from server.routes.worker import router as worker_router
from server.routes.hitl import router as hitl_router
from server.routes.extractors import router as extractors_router

app.include_router(jobs_router)
app.include_router(worker_router)
app.include_router(hitl_router)
app.include_router(extractors_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
