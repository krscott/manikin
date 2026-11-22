"""SAM 3D Body backend: loads the model on demand and unloads it when idle."""

import contextlib
import gc
import io
import logging
import threading
import time
import warnings
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch

from manikin.mhr import (
    Array,
    MhrState,
    check_skeleton,
    joint_positions,
    pose_from_mhr,
    project,
)
from manikin.pose import EstimateError, Joint, Pose, Vec2

log = logging.getLogger(__name__)

BACKEND_NAME = "sam-3d-body-vith"
HF_REPO = "facebook/sam-3d-body-vith"
HF_REVISION = "f7f4ba4f67739e297f291639afb7c59041745367"
MODEL_FILES = ("model.ckpt", "model_config.yaml", "assets/mhr_model.pt")


def missing_weights_error(model_dir: Path) -> str | None:
    missing = [name for name in MODEL_FILES if not (model_dir / name).is_file()]
    if not missing:
        return None
    return (
        f"SAM 3D Body weights are missing from {model_dir} ({', '.join(missing)}).\n"
        f"Request access at https://huggingface.co/{HF_REPO}, then download them "
        "(see 'Model weights' in the README):\n"
        f"  hf download {HF_REPO} --revision {HF_REVISION} --local-dir {model_dir}"
    )


@dataclass(frozen=True, kw_only=True)
class _Loaded:
    estimator: Any  # sam_3d_body.SAM3DBodyEstimator
    rest: MhrState


class SamBackend:
    """Thread-safe pose estimation with a lazily loaded model."""

    name = BACKEND_NAME

    def __init__(
        self,
        *,
        model_dir: Path,
        idle_timeout: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._model_dir = model_dir
        self._idle_timeout = idle_timeout
        self._clock = clock
        self._lock = threading.Lock()
        self._loaded: _Loaded | None = None
        self._last_used = 0.0

    @property
    def loaded(self) -> bool:
        return self._loaded is not None

    def estimate(self, image: np.ndarray) -> Pose | EstimateError:
        """Estimate the pose of the person in an upright RGB image."""
        with self._lock:
            oom_detail = ""
            try:
                result = self._load_and_estimate(image)
            except RuntimeError as e:
                # CUDA context and cuBLAS failures report OOM as a plain RuntimeError.
                if not isinstance(e, torch.OutOfMemoryError) and (
                    "out of memory" not in str(e)
                ):
                    raise
                result = None
                oom_detail = str(e)
            finally:
                self._last_used = self._clock()
            if result is None:
                # Freed outside the except block, whose traceback would keep the
                # failed frames' tensors alive.
                _free_gpu_memory()
                log.warning("Out of GPU memory while estimating a pose: %s", oom_detail)
                return EstimateError(
                    "Not enough free GPU memory (manikin needs about 4 GB). "
                    "Close other GPU apps and try again."
                )
            return result

    def _load_and_estimate(self, image: np.ndarray) -> Pose | EstimateError:
        if self._loaded is None:
            loaded = self._load()
            if isinstance(loaded, EstimateError):
                return loaded
            self._loaded = loaded
        return _estimate(self._loaded, image)

    def unload_if_idle(self) -> bool:
        with self._lock:
            if self._loaded is None:
                return False
            if self._clock() - self._last_used < self._idle_timeout:
                return False
            self._loaded = None
            _free_gpu_memory()
            log.info("Unloaded the pose model after %.0f s idle", self._idle_timeout)
            return True

    def _load(self) -> _Loaded | EstimateError:
        error = missing_weights_error(self._model_dir)
        if error is not None:
            return EstimateError(error)

        log.info("Loading the pose model from %s", self._model_dir)
        start = time.monotonic()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # Upstream warns about optional deps.
            from sam_3d_body import SAM3DBodyEstimator, load_sam_3d_body

        if not torch.cuda.is_available():
            return EstimateError("CUDA is not available; SAM 3D Body needs a GPU")

        model: Any
        model_cfg: Any
        with _quiet():
            model, model_cfg = load_sam_3d_body(
                checkpoint_path=str(self._model_dir / "model.ckpt"),
                mhr_path=str(self._model_dir / "assets" / "mhr_model.pt"),
            )
            estimator = SAM3DBodyEstimator(model, model_cfg)
        head: Any = model.head_pose

        parents = head.mhr.character_torch.skeleton.joint_parents.cpu().numpy()
        skeleton_error = check_skeleton(parents)
        if skeleton_error is not None:
            return EstimateError(
                f"{skeleton_error}. manikin supports {HF_REPO} "
                f"revision {HF_REVISION}."
            )

        def zeros(n: int) -> Any:
            return torch.zeros(1, n, device="cuda")

        with torch.no_grad():
            _, keypoints, joints, rotations = head.mhr_forward(
                global_trans=zeros(3),
                global_rot=zeros(3),
                body_pose_params=zeros(133),
                hand_pose_params=zeros(108),
                scale_params=zeros(28),
                shape_params=zeros(45),
                expr_params=zeros(72),
                return_keypoints=True,
                return_joint_coords=True,
                return_joint_rotations=True,
            )
        rest = MhrState(
            joints=_numpy(joints),
            rotations=_numpy(rotations),
            keypoints=_numpy(keypoints)[:70],
        )
        log.info("Loaded the pose model in %.1f s", time.monotonic() - start)
        return _Loaded(estimator=estimator, rest=rest)


def _estimate(loaded: _Loaded, image: np.ndarray) -> Pose | EstimateError:
    height, width = image.shape[:2]
    with _quiet():
        # The first pass covers the whole photo. The second re-runs on the person's
        # bounds, so a small figure in a large photo still fills the model input.
        first = loaded.estimator.process_one_image(image, inference_type="body")
        if not first:
            return EstimateError("No person found in the photo")
        bbox = _bounds(first[0]["pred_keypoints_2d"], width=width, height=height)
        outputs = loaded.estimator.process_one_image(
            image, bboxes=bbox, inference_type="body"
        )
    if not outputs:
        return EstimateError("No person found in the photo")
    out = outputs[0]

    flip = np.array([1.0, -1.0, -1.0])  # SAM 3D Body camera frame -> MHR frame.
    posed = MhrState(
        joints=out["pred_joint_coords"].astype(np.float64) * flip,
        rotations=out["pred_global_rots"].astype(np.float64),
        keypoints=out["pred_keypoints_3d"].astype(np.float64) * flip,
    )
    positions = joint_positions(posed)
    joints = list(positions)
    pixels = project(
        np.stack([positions[j] for j in joints]),
        focal_length=float(out["focal_length"]),
        cam_t=out["pred_cam_t"].astype(np.float64),
        image_size=(width, height),
    )
    image_points: dict[Joint, Vec2] = {
        joint: (float(x), float(y)) for joint, (x, y) in zip(joints, pixels)
    }
    return pose_from_mhr(
        posed=posed,
        rest=loaded.rest,
        image_points=image_points,
        image_size=(width, height),
    )


def _bounds(points: Array, *, width: int, height: int) -> Array:
    low = np.clip(points.min(axis=0), 0, [width, height])
    high = np.clip(points.max(axis=0), 0, [width, height])
    return np.array([[low[0], low[1], high[0], high[1]]])


def _numpy(tensor: Any) -> Array:
    array: Array = tensor[0].float().cpu().numpy().astype(np.float64)
    return array


@contextlib.contextmanager
def _quiet() -> Generator[None]:
    """Send upstream print(), warning, and log noise to the debug log."""
    buffer = io.StringIO()
    # Upstream loads with strict=False and logs every buffer the checkpoint
    # omits; those buffers come from mhr_model.pt instead.
    checkpoint_log = logging.getLogger("sam_3d_body.utils.checkpoint")
    level = checkpoint_log.level
    checkpoint_log.setLevel(logging.ERROR)
    try:
        with contextlib.redirect_stdout(buffer), warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            yield
    finally:
        checkpoint_log.setLevel(level)
    for line in buffer.getvalue().splitlines():
        log.debug("sam-3d-body: %s", line)


def _free_gpu_memory() -> None:
    gc.collect()
    torch.cuda.empty_cache()
