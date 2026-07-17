"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import (
    auth,
    cleanup,
    preview,
    recorder,
    recordings,
    settings as settings_api,
    status,
    ticket,
    webdav,
)
from app.config import get_settings
from app.db.engine import init_engine
from app.db.migrate import init_db
from app.services.cleanup_service import CleanupService
from app.services.convert_queue import ConvertQueue
from app.services.recorder_service import RecorderService
from app.services.ticket_service import TicketService
from app.services.webdav_service import WebDAVService
from app.workers.scheduler import AppScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("wss-recorder-arm")

WEB_DIR = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    data_dir = settings.resolve_path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    settings.resolve_path(settings.recording.output_dir).mkdir(parents=True, exist_ok=True)

    init_engine(settings)
    await init_db()

    cleanup_service = CleanupService(settings)
    convert_queue = ConvertQueue(settings, cleanup_service=cleanup_service)
    ticket_service = TicketService(settings)
    await ticket_service.ensure_row()
    webdav_service = WebDAVService(settings, cleanup_service=cleanup_service)
    loop = asyncio.get_running_loop()
    recorder_service = RecorderService(settings, ticket_service, convert_queue, loop=loop)
    scheduler = AppScheduler(settings, webdav_service, cleanup=cleanup_service)

    app.state.settings = settings
    app.state.convert_queue = convert_queue
    app.state.ticket_service = ticket_service
    app.state.webdav_service = webdav_service
    app.state.cleanup_service = cleanup_service
    app.state.recorder_service = recorder_service
    app.state.scheduler = scheduler

    await convert_queue.start()
    scheduler.start()
    # initial cleanup pass
    try:
        await cleanup_service.run_all()
    except Exception:
        logger.exception("startup cleanup failed")

    # auto-start recording if enabled and ticket present
    if settings.recording.auto_start:
        try:
            result = await recorder_service.start()
            logger.info("auto_start recorder: %s", result)
        except Exception:
            logger.exception("auto_start recorder failed")

    logger.info("wss-recorder-arm %s started", __version__)
    yield
    await recorder_service.stop()
    await convert_queue.stop()
    scheduler.stop()
    logger.info("shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(title="wss-recorder-arm", version=__version__, lifespan=lifespan)

    app.include_router(auth.router)
    app.include_router(status.router)
    app.include_router(ticket.router)
    app.include_router(recorder.router)
    app.include_router(recordings.router)
    app.include_router(preview.router)
    app.include_router(webdav.router)
    app.include_router(settings_api.router)
    app.include_router(cleanup.router)

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

        @app.get("/")
        async def index():
            return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app()
