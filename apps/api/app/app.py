import os
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.routers import studies, entities, cycles, metrics, scope, actions, public_lite, public_demo
from app.auth import verify_token

app = FastAPI(
    title="SoA Platform API",
    description=(
        "Agent Commerce Command Center — "
        "Share of Algorithm measurement"
    ),
    version="1.0.0",
)

_cors_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
]
# SoA Lite's public endpoints are also called cross-origin from the
# marketing site, which lives on its own domain outside this app's
# frontend — add it without touching the authed-app origins above.
_lite_origin = os.getenv("LITE_ALLOWED_ORIGIN")
if _lite_origin:
    _cors_origins.append(_lite_origin)

# audit.parleo.io migration (X1): the audit host is served by this same
# Vercel deployment, so its own /api/* calls are same-origin — this
# entry only matters if the API ever ends up served from a different
# origin than the page (e.g. local dev pointed at a remote API, or a
# future split deployment). Additive only, never removes an origin.
_cors_origins.append(os.getenv("PUBLIC_AUDIT_BASE_URL", "https://audit.parleo.io").rstrip("/"))

# X2: no cookie Domain is set anywhere in this app — SoA Lite's public
# endpoints are session-less (no login), so there's no cross-host state
# that would justify widening a cookie Domain to .parleo.io. Left
# host-scoped by default; revisit only if something genuinely needs to
# share state between audit.parleo.io and the marketing/authed hosts.

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
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
app.include_router(
    actions.router,
    prefix="/api",
    dependencies=[Depends(verify_token)],
)

# Public, unauthenticated — SoA Lite. Deliberately NO verify_token
# dependency; see app/routers/public_lite.py's module docstring.
app.include_router(
    public_lite.router,
    prefix="/api/public",
)

# Public, unauthenticated — the leadgen RequestFormModal. Same
# treatment as public_lite above (no verify_token, same /api/public
# prefix, same CORS origins already configured for this whole app).
app.include_router(
    public_demo.router,
    prefix="/api/public",
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
