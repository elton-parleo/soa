import os
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.routers import studies, entities, cycles, metrics, scope
from app.auth import verify_token

app = FastAPI(
    title="SoA Platform API",
    description=(
        "Agent Commerce Command Center — "
        "Share of Algorithm measurement"
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Apply JWT verification to all routes in these routers.
# /api/health (defined directly on app below) remains public.
app.include_router(
    studies.router,
    prefix="/api",
    dependencies=[Depends(verify_token)],
)
app.include_router(
    entities.router,
    prefix="/api",
    dependencies=[Depends(verify_token)],
)
app.include_router(
    cycles.router,
    prefix="/api",
    dependencies=[Depends(verify_token)],
)
app.include_router(
    metrics.router,
    prefix="/api",
    dependencies=[Depends(verify_token)],
)
app.include_router(
    scope.router,
    prefix="/api",
    dependencies=[Depends(verify_token)],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve built React frontend in production
_web_dist  = os.path.join(os.path.dirname(__file__), "../web/dist")
_on_vercel = os.getenv('VERCEL') == '1'
if os.path.exists(_web_dist) and not _on_vercel:
    app.mount(
        "/assets",
        StaticFiles(directory=f"{_web_dist}/assets"),
        name="assets",
    )

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        return FileResponse(os.path.join(_web_dist, "index.html"))
