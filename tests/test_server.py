from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from starlette.testclient import TestClient

from manikin.pose import EstimateError, Pose
from manikin.server import PENDING_TTL, create_app


class FakeBackend:
    name = "fake"

    def __init__(self, result: Pose | EstimateError) -> None:
        self.result = result
        self.images: list[np.ndarray] = []

    @property
    def loaded(self) -> bool:
        return bool(self.images)

    def estimate(self, image: np.ndarray) -> Pose | EstimateError:
        self.images.append(image)
        return self.result

    def unload_if_idle(self) -> bool:
        return False


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


def client(backend: FakeBackend, out_dir: Path, clock: Clock) -> TestClient:
    app = create_app(
        backend=backend,
        out_dir=out_dir,
        clock=clock,
        now=lambda: datetime(2026, 11, 21, 12, 0, 0),
    )
    return TestClient(app)


def upload(c: TestClient, data: bytes) -> dict[str, object]:
    response = c.post("/api/poses", files={"photo": ("p.jpg", data, "image/jpeg")})
    body: dict[str, object] = response.json()
    body["status"] = response.status_code
    return body


def test_index_and_status(tmp_path: Path, sample_pose: Pose, clock: Clock) -> None:
    with client(FakeBackend(sample_pose), tmp_path, clock) as c:
        index = c.get("/")
        assert "<title>manikin</title>" in index.text
        assert index.headers["cache-control"] == "no-store"
        script = c.get("/static/app.js")
        assert script.status_code == 200
        assert script.headers["cache-control"] == "no-store"
        assert c.get("/api/status").json() == {"model_loaded": False}


def test_preview_then_accept(
    tmp_path: Path, sample_pose: Pose, jpeg_bytes: bytes, clock: Clock
) -> None:
    backend = FakeBackend(sample_pose)
    with client(backend, tmp_path, clock) as c:
        body = upload(c, jpeg_bytes)
        assert body["status"] == 200
        preview = body["preview"]
        assert isinstance(preview, dict)
        assert preview["image_size"] == [64, 48]
        assert preview["warnings"] == []
        assert backend.images[0].shape == (48, 64, 3)

        accepted = c.post(f"/api/poses/{body['id']}/accept", json={"name": "Kick"})
        assert accepted.json() == {"saved": "20261121-120000-kick"}
        assert (tmp_path / "20261121-120000-kick" / "pose.json").is_file()

        again = c.post(f"/api/poses/{body['id']}/accept", json={})
        assert again.status_code == 404


def test_retake_discards(
    tmp_path: Path, sample_pose: Pose, jpeg_bytes: bytes, clock: Clock
) -> None:
    with client(FakeBackend(sample_pose), tmp_path, clock) as c:
        body = upload(c, jpeg_bytes)
        assert c.delete(f"/api/poses/{body['id']}").status_code == 204
        assert c.post(f"/api/poses/{body['id']}/accept").status_code == 404
    assert not tmp_path.exists() or not any(tmp_path.iterdir())


def test_pending_poses_expire(
    tmp_path: Path, sample_pose: Pose, jpeg_bytes: bytes, clock: Clock
) -> None:
    with client(FakeBackend(sample_pose), tmp_path, clock) as c:
        body = upload(c, jpeg_bytes)
        clock.now += PENDING_TTL + 1
        assert c.post(f"/api/poses/{body['id']}/accept").status_code == 404


def test_errors(tmp_path: Path, jpeg_bytes: bytes, clock: Clock) -> None:
    backend = FakeBackend(EstimateError("No person found in the photo"))
    with client(backend, tmp_path, clock) as c:
        assert upload(c, jpeg_bytes) == {
            "error": "No person found in the photo",
            "status": 422,
        }
        bad = upload(c, b"nope")
        assert bad["status"] == 400 and "Unsupported" in str(bad["error"])
        missing = c.post("/api/poses", data={"other": "x"})
        assert missing.status_code == 400


def test_failed_save_keeps_the_pose(
    tmp_path: Path, sample_pose: Pose, jpeg_bytes: bytes, clock: Clock
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("")
    with client(FakeBackend(sample_pose), blocker / "poses", clock) as c:
        body = upload(c, jpeg_bytes)
        for _ in range(2):  # Still pending after the first failure.
            failed = c.post(f"/api/poses/{body['id']}/accept", json={})
            assert failed.status_code == 500
            assert "Cannot write to" in failed.json()["error"]


def test_accept_rejects_invalid_json(
    tmp_path: Path, sample_pose: Pose, jpeg_bytes: bytes, clock: Clock
) -> None:
    with client(FakeBackend(sample_pose), tmp_path, clock) as c:
        body = upload(c, jpeg_bytes)
        bad = c.post(f"/api/poses/{body['id']}/accept", content=b"{nope")
        assert bad.status_code == 400
        assert c.post(f"/api/poses/{body['id']}/accept").status_code == 200
