"""
Vercel ASGI entry point.

Vercel's Python runtime invokes the ASGI app defined here. No uvicorn.run()
needed. The 'app' name is the convention Vercel looks for in api/index.py.
"""
from api.app import app  # noqa: F401
