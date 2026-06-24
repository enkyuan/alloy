"""Aggregate API v1 routers."""

from fastapi import APIRouter

from kaji_serve.server.v1 import auth, health, providers, sessions, tools, voice

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(voice.router)
api_router.include_router(providers.router)
api_router.include_router(tools.router)
api_router.include_router(sessions.router)
