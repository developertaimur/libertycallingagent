"""HTTP API routers."""

from app.api.endpoints.dialer import router as dialer_router
from app.api.endpoints.leads import router as leads_router
from app.api.endpoints.media_stream import router as media_stream_router
from app.api.endpoints.messaging import router as messaging_router
from app.api.endpoints.outreach import router as outreach_router
from app.api.endpoints.settings import router as settings_router
from app.api.endpoints.transfer_desk import router as transfer_desk_router
from app.api.endpoints.webhooks import router as webhooks_router

__all__ = [
    "webhooks_router",
    "dialer_router",
    "leads_router",
    "settings_router",
    "messaging_router",
    "outreach_router",
    "media_stream_router",
    "transfer_desk_router",
]
