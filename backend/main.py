import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from llm.provider_factory import get_llm_provider, get_embedding_provider
from pipeline import stream_eia_pipeline, cancel_pipeline

load_dotenv()

# Explicit stdout handler on the eia logger so it survives Uvicorn's dictConfig
# override and is always visible in Render/container logs.
_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setLevel(logging.DEBUG)
_stdout_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")
)
_eia_logger = logging.getLogger("eia")
_eia_logger.setLevel(logging.DEBUG)
_eia_logger.addHandler(_stdout_handler)
_eia_logger.propagate = False  # prevent double-printing via root logger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eia")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[LIFESPAN] Initialising LLM providers…", flush=True, file=sys.stdout)
    try:
        llm = get_llm_provider()
        emb = get_embedding_provider()
    except Exception as exc:
        print(f"[LIFESPAN] PROVIDER INIT FAILED: {exc}", flush=True, file=sys.stdout)
        raise
    logger.info("LLM provider: %s", llm.provider_name)
    logger.info("Embedding provider: %s", emb.provider_name)
    print(f"[LIFESPAN] LLM={llm.provider_name}  Embedding={emb.provider_name}", flush=True, file=sys.stdout)
    app.state.llm_provider = llm
    app.state.embedding_provider = emb
    yield


app = FastAPI(title="EIA Multi-Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    project_name: str
    coordinates: str
    description: str


@app.post("/api/cancel")
def cancel_run():
    cancel_pipeline()
    return {"status": "cancelled"}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_provider": app.state.llm_provider.provider_name,
        "embedding_provider": app.state.embedding_provider.provider_name,
    }


@app.post("/api/run")
def run_pipeline(req: RunRequest):
    return StreamingResponse(
        stream_eia_pipeline(
            project_name=req.project_name,
            coordinates=req.coordinates,
            description=req.description,
            llm=app.state.llm_provider,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
