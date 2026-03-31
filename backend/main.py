import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from llm.provider_factory import get_llm_provider, get_embedding_provider

load_dotenv()

logger = logging.getLogger("eia")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    llm = get_llm_provider()
    emb = get_embedding_provider()
    logger.info(f"LLM provider: {llm.provider_name}")
    logger.info(f"Embedding provider: {emb.provider_name}")
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


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_provider": app.state.llm_provider.provider_name,
        "embedding_provider": app.state.embedding_provider.provider_name,
    }


@app.post("/api/run")
def run_pipeline(req: RunRequest):
    # TODO: Wire up the real LangGraph pipeline here
    return {
        "project_name": req.project_name,
        "coordinates": req.coordinates,
        "description": req.description,
        "pipeline_status": {
            "project_parser": "pending",
            "environmental_data": "pending",
            "regulatory_screening": "pending",
            "impact_analysis": "pending",
            "report_synthesis": "pending",
        },
        "impact_matrix": [],
        "regulations": [],
    }
