"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.routes import authors, paragraphs, search, stats, works


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    yield
    # Shutdown


app = FastAPI(
    title="Grundrisse API",
    description="REST API for the Grundrisse Marxist text corpus",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(stats.router, prefix="/api", tags=["stats"])
app.include_router(authors.router, prefix="/api/authors", tags=["authors"])
app.include_router(works.router, prefix="/api/works", tags=["works"])
app.include_router(paragraphs.router, prefix="/api/paragraphs", tags=["paragraphs"])
app.include_router(search.router, prefix="/api/search", tags=["search"])


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
