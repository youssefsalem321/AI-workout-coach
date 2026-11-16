"""Squat form analysis from a SIDE-VIEW video.

Two layers on purpose:
  1. `analyze_frames` - pure Python/NumPy-free math on landmark coordinates (unit-testable, no ML needed):
     knee angle -> rep counting -> depth / torso lean / tempo -> 0-100 score + issue codes.
  2. `extract_landmarks` - runs MediaPipe Pose on a video file and returns the frames for layer 1.

The LLM is not involved: the verdict comes from geometry, so it is explainable and repeatable.
"""
from __future__ import annotations

import math
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- thresholds (degrees / seconds)
STAND_ANGLE = 160.0      # knee angle that counts as "standing"
START_ANGLE = 150.0      # leaving this angle downward starts a rep
MIN_BOTTOM = 135.0       # a rep must bend at least this much to count
DEPTH_GOOD = 100.0       # hip-knee-ankle angle at the bottom: good depth
DEPTH_OK = 115.0
LEAN_MAX = 55.0          # torso angle from vertical
MIN_DESCENT_S = 0.8      # faster than this = dropping, not controlling
MIN_VISIBILITY = 0.5

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
             "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task")

# MediaPipe pose landmark indices: left / right
_IDX = {"shoulder": (11, 12), "hip": (23, 24), "knee": (25, 26), "ankle": (27, 28)}


class FormAnalysisError(Exception):
    """Raised for problems the user can fix (bad video, body not visible, missing dependency)."""


@dataclass
class Frame:
    t: float                                   # seconds
    pts: dict[str, tuple[float, float]]        # shoulder/hip/knee/ankle -> (x, y), image coords (y down)
    visibility: float = 1.0


@dataclass
class RepMetrics:
    start_t: float
    bottom_t: float
    end_t: float
    min_knee_angle: float
    max_lean: float
    descent_s: float
    score: float


@dataclass
class FormReport:
    rep_count: int
    score: float                               # 0-100 (mean over reps)
    reps: list[RepMetrics] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)   # [{"code": "shallow", "count": 2}, ...]
    angle_series: list[tuple[float, float]] = field(default_factory=list)  # (t, knee angle)


# --------------------------------------------------------------------------- geometry
def angle_at(b: tuple[float, float], a: tuple[float, float], c: tuple[float, float]) -> float:
    """Angle ABC in degrees (vertex at b)."""
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 == 0 or n2 == 0:
        return 180.0
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cos))


def torso_lean(hip: tuple[float, float], shoulder: tuple[float, float]) -> float:
    """Angle of the hip->shoulder line from vertical (0 = upright)."""
    dx, dy = shoulder[0] - hip[0], shoulder[1] - hip[1]
    return math.degrees(math.atan2(abs(dx), -dy)) if dy < 0 else 90.0 + math.degrees(math.atan2(dy, abs(dx)))


def _smooth(values: list[float], window: int = 5) -> list[float]:
    half = window // 2
    out = []
    for i in range(len(values)):
        seg = values[max(0, i - half): i + half + 1]
        out.append(sum(seg) / len(seg))
    return out


# --------------------------------------------------------------------------- scoring
def _depth_score(min_angle: float) -> float:
    if min_angle <= DEPTH_GOOD:
        return 100.0
    if min_angle <= 130.0:
        return 100.0 - (min_angle - DEPTH_GOOD) * (50.0 / 30.0)
    return 40.0


def _lean_score(lean: float) -> float:
    if lean <= LEAN_MAX:
        return 100.0
    return max(40.0, 100.0 - (lean - LEAN_MAX) * (60.0 / 25.0))


def _tempo_score(descent_s: float) -> float:
    if descent_s >= MIN_DESCENT_S:
        return 100.0
    return 75.0 if descent_s >= 0.4 else 50.0


# --------------------------------------------------------------------------- analysis
def analyze_frames(frames: list[Frame]) -> FormReport:
    if len(frames) < 10:
        raise FormAnalysisError("not_enough_frames")
    if sum(f.visibility for f in frames) / len(frames) < MIN_VISIBILITY:
        raise FormAnalysisError("body_not_visible")

    angles = _smooth([angle_at(f.pts["knee"], f.pts["hip"], f.pts["ankle"]) for f in frames])
    leans = [torso_lean(f.pts["hip"], f.pts["shoulder"]) for f in frames]
    times = [f.t for f in frames]

    reps: list[RepMetrics] = []
    i, n = 0, len(angles)
    while i < n:
        if angles[i] >= START_ANGLE:
            i += 1
            continue
        start = max(0, i - 1)                      # descent began just before leaving START_ANGLE
        j = i
        while j < n and angles[j] < STAND_ANGLE:   # until the lifter is standing again
            j += 1
        if j >= n:                                 # video ended mid-rep: do not count it
            break
        bottom = min(range(start, j + 1), key=lambda k: angles[k])
        if angles[bottom] < MIN_BOTTOM:
            descent = max(0.0, times[bottom] - times[start])
            max_lean = max(leans[k] for k in range(start, j + 1))
            score = round(0.5 * _depth_score(angles[bottom]) + 0.35 * _lean_score(max_lean)
                          + 0.15 * _tempo_score(descent), 1)
            reps.append(RepMetrics(times[start], times[bottom], times[j], round(angles[bottom], 1),
                                   round(max_lean, 1), round(descent, 2), score))
        i = j + 1

    issues = []
    shallow = sum(1 for r in reps if r.min_knee_angle > DEPTH_OK)
    partial = sum(1 for r in reps if DEPTH_GOOD < r.min_knee_angle <= DEPTH_OK)
    lean = sum(1 for r in reps if r.max_lean > LEAN_MAX)
    fast = sum(1 for r in reps if r.descent_s < MIN_DESCENT_S)
    if shallow:
        issues.append({"code": "shallow", "count": shallow})
    if partial:
        issues.append({"code": "almost_parallel", "count": partial})
    if lean:
        issues.append({"code": "lean", "count": lean})
    if fast:
        issues.append({"code": "fast", "count": fast})
    if reps and not issues:
        issues.append({"code": "clean", "count": len(reps)})

    score = round(sum(r.score for r in reps) / len(reps), 1) if reps else 0.0
    return FormReport(len(reps), score, reps, issues, list(zip(times, angles)))


# --------------------------------------------------------------------------- video -> frames
def ensure_model(model_dir: str = "data/models") -> Path:
    """Download the MediaPipe pose model once (needed by newer MediaPipe versions)."""
    path = Path(model_dir) / "pose_landmarker_lite.task"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(MODEL_URL, path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise FormAnalysisError(f"model_download_failed: {exc}. Download {MODEL_URL} manually into {path}") from exc
    return path


class _PoseBackend:
    """Wraps either the legacy `mp.solutions.pose` API or the newer Tasks API."""

    def __init__(self, model_dir: str = "data/models"):
        try:
            import mediapipe as mp
        except ImportError as exc:
            raise FormAnalysisError("mediapipe_missing") from exc
        self.mp = mp
        self.legacy = hasattr(mp, "solutions") and hasattr(getattr(mp, "solutions"), "pose")
        if self.legacy:
            self.pose = mp.solutions.pose.Pose(static_image_mode=False, model_complexity=1,
                                               min_detection_confidence=0.5, min_tracking_confidence=0.5)
        else:
            from mediapipe.tasks.python import BaseOptions, vision
            opts = vision.PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(ensure_model(model_dir))),
                running_mode=vision.RunningMode.VIDEO, num_poses=1,
                min_pose_detection_confidence=0.5, min_pose_presence_confidence=0.5, min_tracking_confidence=0.5)
            self.pose = vision.PoseLandmarker.create_from_options(opts)

    def landmarks(self, rgb, t_ms: int):
        """Returns a list of 33 landmarks (x, y, visibility) or None."""
        if self.legacy:
            res = self.pose.process(rgb)
            if not res.pose_landmarks:
                return None
            return [(p.x, p.y, p.visibility) for p in res.pose_landmarks.landmark]
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        res = self.pose.detect_for_video(image, t_ms)
        if not res.pose_landmarks:
            return None
        return [(p.x, p.y, p.visibility) for p in res.pose_landmarks[0]]

    def close(self):
        try:
            self.pose.close()
        except Exception:
            pass


def _frame_from_landmarks(t: float, lms) -> Frame:
    """Pick the body side that MediaPipe sees best (side-view video) and build a Frame."""
    best_side, best_vis = 0, -1.0
    for side in (0, 1):
        vis = sum(lms[_IDX[name][side]][2] for name in _IDX) / len(_IDX)
        if vis > best_vis:
            best_side, best_vis = side, vis
    pts = {name: lms[_IDX[name][best_side]][:2] for name in _IDX}
    return Frame(t, pts, best_vis)


def extract_landmarks(video_path: str, max_seconds: float = 40.0, backend=None, target_width: int = 640) -> list[Frame]:
    """Read a video with OpenCV and run pose estimation. `backend` can be injected for tests."""
    try:
        import cv2
    except ImportError as exc:
        raise FormAnalysisError("opencv_missing") from exc

    own_backend = backend is None
    backend = backend or _PoseBackend()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FormAnalysisError("cannot_open_video")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames: list[Frame] = []
    idx = 0
    try:
        while True:
            ok, bgr = cap.read()
            if not ok or idx / fps > max_seconds:
                break
            t = idx / fps
            idx += 1
            h, w = bgr.shape[:2]
            if w > target_width:
                bgr = cv2.resize(bgr, (target_width, int(h * target_width / w)))
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            lms = backend.landmarks(rgb, int(t * 1000))
            if lms is not None:
                frames.append(_frame_from_landmarks(t, lms))
    finally:
        cap.release()
        if own_backend:
            backend.close()
    if not frames:
        raise FormAnalysisError("no_person_detected")
    return frames


def analyze_video(video_path: str, **kwargs) -> FormReport:
    return analyze_frames(extract_landmarks(video_path, **kwargs))
