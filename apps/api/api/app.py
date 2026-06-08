import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.routers import studies, entities, cycles

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

app.include_router(studies.router,  prefix="/api")
app.include_router(entities.router, prefix="/api")
app.include_router(cycles.router,   prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve built React frontend in production
_web_dist = os.path.join(os.path.dirname(__file__), "../web/dist")
if os.path.exists(_web_dist):
    app.mount(
        "/assets",
        StaticFiles(directory=f"{_web_dist}/assets"),
        name="assets",
    )

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        return FileResponse(os.path.join(_web_dist, "index.html"))
