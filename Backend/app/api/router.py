"""Aggregates all v1 routers. Routers are registered as their stage is implemented."""
from fastapi import APIRouter

from app.api.routes import (
    auth, demo, grading, health, images, inventory, listings, market, matching, orders, pricing, requirements, uploads, users,
)

api_router = APIRouter()  # mounted under /api/v1 by main.py
api_router.include_router(auth.router)
api_router.include_router(demo.router)
api_router.include_router(users.router)
api_router.include_router(images.router)
api_router.include_router(listings.router)
api_router.include_router(inventory.router)
api_router.include_router(grading.router)
api_router.include_router(market.router)
api_router.include_router(pricing.router)
api_router.include_router(requirements.router)
api_router.include_router(matching.router)
api_router.include_router(orders.router)
api_router.include_router(uploads.router)

health_router = health.router  # mounted at root: /health/*
