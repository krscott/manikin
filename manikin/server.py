"""HTTP app the phone talks to: upload a photo, preview the pose, accept or retake."""

import contextlib
import logging
import secrets
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import anyio
import numpy as np
from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders, UploadFile
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from manikin import __version__
from manikin.photo import Photo, PhotoError, decode_photo
from manikin.pose import (
    EstimateError,
    Pose,
    PoseBackend,
    out_of_frame_joints,
    preview_edges,
)
from manikin.saved_pose import SaveError, save_pose

log = logging.getLogger(__name__)

STATIC_DIR = Path(str(files("manikin") / "static"))
MAX_PHOTO_BYTES = 50 * 1024 * 1024
PENDING_TTL = 30 * 60.0
HOUSEKEEPING_INTERVAL = 30.0


@dataclass(frozen=True, kw_only=True)
class PendingPose:
    """A pose shown in the preview, waiting for Accept or Retake."""

    photo: Photo
    pose: Pose
    created: float


def create_app(
    *,
    backend: PoseBackend,
    out_dir: Path,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = datetime.now,
) -> Starlette:
    pending: dict[str, PendingPose] = {}

    def expire_pending() -> None:
        cutoff = clock() - PENDING_TTL
        for key in [k for k, p in pending.items() if p.created < cutoff]:
            del pending[key]

    async def index(_: Request) -> Response:
        return FileResponse(STATIC_DIR / "index.html")

    async def status(_: Request) -> Response:
        return JSONResponse({"model_loaded": backend.loaded})

    async def create_pose(request: Request) -> Response:
        # Reject oversized uploads before Starlette spools them to disk.
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_PHOTO_BYTES + 64 * 1024:
            return _error(413, "The photo is larger than 50 MB")
        async with request.form(max_files=1, max_fields=0) as form:
            upload = form.get("photo")
            if not isinstance(upload, UploadFile):
                return _error(400, "Send the photo as the 'photo' form field")
            data = await upload.read(MAX_PHOTO_BYTES + 1)
        if len(data) > MAX_PHOTO_BYTES:
            return _error(413, "The photo is larger than 50 MB")

        photo = await anyio.to_thread.run_sync(decode_photo, data)
        if isinstance(photo, PhotoError):
            return _error(400, photo.message)
        image = np.asarray(photo.image)
        # Backends serialize GPU work themselves; this keeps the event loop free.
        pose = await anyio.to_thread.run_sync(backend.estimate, image)
        if isinstance(pose, EstimateError):
            return _error(422, pose.message)

        pose_id = secrets.token_urlsafe(12)
        pending[pose_id] = PendingPose(photo=photo, pose=pose, created=clock())
        return JSONResponse({"id": pose_id, "preview": preview_json(pose)})

    async def accept_pose(request: Request) -> Response:
        expire_pending()
        pose_id = request.path_params["pose_id"]
        try:
            body: object = await request.json() if await request.body() else {}
        except ValueError:
            return _error(400, "The request body must be JSON")
        name = (
            cast(dict[str, object], body).get("name", "")
            if isinstance(body, dict)
            else ""
        )
        if not isinstance(name, str):
            return _error(400, "name must be a string")
        # Pop first so a repeated Accept cannot save the same pose twice.
        item = pending.pop(pose_id, None)
        if item is None:
            return _error(404, "This pose has expired; take the photo again")
        saved = await anyio.to_thread.run_sync(
            lambda: save_pose(
                out_dir=out_dir,
                photo=item.photo,
                pose=item.pose,
                name=name,
                now=now(),
                backend=backend.name,
                manikin_version=__version__,
            )
        )
        if isinstance(saved, SaveError):
            pending[pose_id] = item  # Keep it so Accept can be retried.
            log.error("%s", saved.message)
            return _error(500, saved.message)
        log.info("Saved pose to %s", saved)
        return JSONResponse({"saved": saved.name})

    async def discard_pose(request: Request) -> Response:
        pending.pop(request.path_params["pose_id"], None)
        return Response(status_code=204)

    async def housekeeping() -> None:
        while True:
            await anyio.sleep(HOUSEKEEPING_INTERVAL)
            expire_pending()
            await anyio.to_thread.run_sync(backend.unload_if_idle)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncGenerator[None]:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(housekeeping)
            yield
            tasks.cancel_scope.cancel()

    return Starlette(
        routes=[
            Route("/", index),
            Route("/api/status", status),
            Route("/api/poses", create_pose, methods=["POST"]),
            Route("/api/poses/{pose_id}/accept", accept_pose, methods=["POST"]),
            Route("/api/poses/{pose_id}", discard_pose, methods=["DELETE"]),
            Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
        ],
        # Nix store files all have the same mtime, so Starlette's validators can't
        # tell versions apart; never let the phone cache the page or its scripts.
        middleware=[Middleware(_NoStore)],
        lifespan=lifespan,
    )


def preview_json(pose: Pose) -> dict[str, Any]:
    outside = out_of_frame_joints(pose)
    warnings = (
        [f"Outside the photo: {', '.join(j.value for j in outside)}"] if outside else []
    )
    return {
        "joints": {j.value: list(p) for j, p in pose.joints.items()},
        "image_points": {j.value: list(p) for j, p in pose.image_points.items()},
        "image_size": list(pose.image_size),
        "edges": [[a.value, b.value] for a, b in preview_edges()],
        "warnings": warnings,
    }


class _NoStore:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_no_store)


def _error(status_code: int, message: str) -> Response:
    return JSONResponse({"error": message}, status_code=status_code)
