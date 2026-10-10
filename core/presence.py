"""
Presence — knows when its owner sits down, and notices when someone else does.

Opt-in and local. Nothing here runs until the user enrols their face AND turns
presence on. After that, a background check opens the webcam for about a
second every so often, looks for faces, and closes it again:

  * owner returns after being away   → a [PRESENCE] note so JARVIS can greet them
  * unknown face while owner is away → a [SYSTEM_ALERT] security note

Faces are found with YuNet and compared with SFace, both OpenCV Zoo models run
by OpenCV's own DNN module (no extra pip packages). The models (~37 MB) are
downloaded on first enrolment and checked against pinned SHA-256 hashes.
What is stored is a 128-number face embedding in config/owner_face.npy: no
photo is ever written to disk or sent anywhere.

Config keys (config/api_keys.json): "presence_enabled" (default false).
"""
from __future__ import annotations

import hashlib
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
_MODEL_DIR = _ROOT / "config" / "models"
_OWNER_PATH = _ROOT / "config" / "owner_face.npy"

_MODELS = {
    "detector": ("face_detection_yunet_2023mar.onnx",
                 "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
                 "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "recognizer": ("face_recognition_sface_2021dec.onnx",
                   "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
                   "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
}

# SFace cosine-similarity threshold recommended by the model's authors.
_MATCH = 0.363
_MIN_FACE_PX = 60           # ignore faces too small/far to judge reliably

_CHECK_AWAY = 15.0          # seconds between looks while the owner is away
_CHECK_HERE = 60.0          # …and while they are at the desk
_AWAY_AFTER = 2             # consecutive misses before "away"
_GREET_AFTER = 300.0        # only greet after being away at least this long
_STRANGER_COOLDOWN = 1800.0


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def models_ready() -> bool:
    return all((_MODEL_DIR / name).exists() for name, _, _ in _MODELS.values())


def download_models(log=print) -> None:
    """Fetch and verify the two ONNX models. Raises on a bad hash."""
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, url, sha in _MODELS.values():
        dest = _MODEL_DIR / name
        if dest.exists() and _sha256(dest) == sha:
            continue
        log(f"Downloading {name}…")
        tmp = dest.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        got = _sha256(tmp)
        if got != sha:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"{name} failed its integrity check — not installed.")
        tmp.replace(dest)


def _config() -> dict:
    try:
        from memory.config_manager import load_api_keys
        return load_api_keys()
    except Exception:
        return {}


def _set_config(key: str, value) -> None:
    from actions.screen_processor import _save_config_key
    _save_config_key(key, value)


class Presence:
    def __init__(self):
        self._lock = threading.Lock()
        self._det = None
        self._rec = None
        self._owner: np.ndarray | None = None
        self._here: bool | None = None       # None = not yet known
        self._misses = 0
        self._away_since: float | None = None
        self._last_look = 0.0
        self._last_stranger = 0.0
        self.last_error = ""
        self._listeners = []          # fn(event) with event in ("arrive", "leave")

    def on_event(self, fn) -> None:
        """Subscribe to 'arrive' / 'leave' (used by protocol triggers)."""
        self._listeners.append(fn)

    def _emit(self, event: str) -> None:
        for fn in list(self._listeners):
            try:
                fn(event)
            except Exception as e:
                print(f"[Presence] listener failed: {e}")

    # ── setup ────────────────────────────────────────────────────────────────
    def enabled(self) -> bool:
        return bool(_config().get("presence_enabled", False))

    def enrolled(self) -> bool:
        return _OWNER_PATH.exists()

    def _load(self) -> None:
        import cv2
        if self._det is None:
            self._det = cv2.FaceDetectorYN.create(
                str(_MODEL_DIR / _MODELS["detector"][0]), "", (320, 320), 0.8, 0.3, 50)
            self._rec = cv2.FaceRecognizerSF.create(
                str(_MODEL_DIR / _MODELS["recognizer"][0]), "")
        if self._owner is None and _OWNER_PATH.exists():
            self._owner = np.load(_OWNER_PATH)

    def _grab(self, frames: int = 1, warmup: int = 6, gap: float = 0.0) -> list:
        import cv2
        from actions.screen_processor import _cv2_backend, _get_camera_index
        cap = cv2.VideoCapture(_get_camera_index(), _cv2_backend())
        if not cap.isOpened():
            cap.release()
            raise RuntimeError("the camera could not be opened")
        try:
            for _ in range(warmup):
                cap.read()
            out = []
            for _ in range(frames):
                ok, frame = cap.read()
                if ok and frame is not None:
                    out.append(frame)
                if gap:
                    time.sleep(gap)
            return out
        finally:
            cap.release()

    def _faces(self, frame) -> list:
        """[(embedding, width_px)] for every usable face in the frame."""
        h, w = frame.shape[:2]
        self._det.setInputSize((w, h))
        _, found = self._det.detect(frame)
        out = []
        for row in (found if found is not None else []):
            if row[2] < _MIN_FACE_PX:
                continue
            aligned = self._rec.alignCrop(frame, row)
            emb = self._rec.feature(aligned).flatten().astype(np.float32)
            out.append((emb / (np.linalg.norm(emb) + 1e-9), float(row[2])))
        return out

    def enroll(self, log=print) -> str:
        """Learn the owner's face from a few seconds of video."""
        with self._lock:
            if not models_ready():
                download_models(log)
            self._load()
            frames = self._grab(frames=10, warmup=10, gap=0.3)
            embs = []
            for f in frames:
                faces = self._faces(f)
                if len(faces) == 1:
                    embs.append(faces[0][0])
            if len(embs) < 4:
                return ("I could not get a clear look — I need exactly one face, facing the "
                        f"camera, in good light (usable frames: {len(embs)} of {len(frames)}).")
            owner = np.mean(embs, axis=0)
            owner /= np.linalg.norm(owner) + 1e-9
            _OWNER_PATH.parent.mkdir(parents=True, exist_ok=True)
            np.save(_OWNER_PATH, owner)
            self._owner = owner
            self._here, self._misses, self._away_since = True, 0, None
            return f"Face enrolled from {len(embs)} frames."

    def forget(self) -> str:
        with self._lock:
            _OWNER_PATH.unlink(missing_ok=True)
            self._owner = None
            _set_config("presence_enabled", False)
            return "Owner face deleted and presence turned off."

    def set_enabled(self, on: bool) -> str:
        if on and not self.enrolled():
            return "Presence needs your face enrolled first."
        _set_config("presence_enabled", bool(on))
        return f"Presence {'on' if on else 'off'}."

    def status(self) -> str:
        if not self.enrolled():
            return "Presence: not set up (no face enrolled)."
        where = {True: "at the desk", False: "away", None: "unknown yet"}[self._here]
        away = ""
        if self._here is False and self._away_since:
            away = f" for {int((time.time() - self._away_since) // 60)} min"
        err = f" Last camera problem: {self.last_error}." if self.last_error else ""
        return (f"Presence: {'on' if self.enabled() else 'off'}; owner {where}{away}.{err}")

    def verify_owner(self) -> bool | None:
        """Look now: True if the owner's face is in front of the camera,
        False if not, None if presence cannot check (not set up / no camera)."""
        if not (self.enrolled() and models_ready()):
            return None
        with self._lock:
            try:
                self._load()
                frames = self._grab(frames=4, warmup=6, gap=0.15)
            except Exception as e:
                self.last_error = str(e)
                return None
            return any(float(emb @ self._owner) >= _MATCH
                       for f in frames for emb, _ in self._faces(f))

    # ── background ───────────────────────────────────────────────────────────
    def due(self) -> bool:
        gap = _CHECK_HERE if self._here else _CHECK_AWAY
        return time.monotonic() - self._last_look >= gap

    def check(self) -> str | None:
        """One look. Returns a message for the model, or None."""
        if not (self.enabled() and self.enrolled() and models_ready()):
            return None
        if not self._lock.acquire(blocking=False):
            return None                      # an enrolment is running
        try:
            self._last_look = time.monotonic()
            self._load()
            try:
                frames = self._grab(frames=1)
                self.last_error = ""
            except Exception as e:
                self.last_error = str(e)
                return None
            if not frames:
                return None
            faces = self._faces(frames[0])
            owner_seen = any(float(emb @ self._owner) >= _MATCH for emb, _ in faces)
            strangers = sum(1 for emb, _ in faces if float(emb @ self._owner) < _MATCH)
            now = time.time()

            if owner_seen:
                from core.access import get_guard
                get_guard().exit_guest("owner recognised on the webcam")
                was_away = self._here is False
                away_for = (now - self._away_since) if (was_away and self._away_since) else 0.0
                self._here, self._misses, self._away_since = True, 0, None
                if was_away:
                    self._emit("arrive")
                if was_away and away_for >= _GREET_AFTER:
                    mins = int(away_for // 60)
                    return (f"[PRESENCE] The user has just sat back down at the computer after "
                            f"about {mins} minutes away (recognised on the webcam). Welcome them "
                            f"back in one short, natural sentence in their language; mention "
                            f"anything time-sensitive you know of. Call no tools.")
                return None

            self._misses += 1
            if self._here is not False and self._misses >= _AWAY_AFTER:
                was_here = self._here is True
                self._here, self._away_since = False, now
                if was_here:
                    self._emit("leave")

            if strangers and self._here is False:
                from core.access import get_guard
                get_guard().enter_guest("unrecognised person at the computer")
            if strangers and self._here is False \
                    and now - self._last_stranger >= _STRANGER_COOLDOWN:
                self._last_stranger = now
                return (f"[SYSTEM_ALERT] Security: the webcam shows {strangers} person(s) at the "
                        f"computer who {'is' if strangers == 1 else 'are'} not the owner, while "
                        f"the owner is away. State it calmly in one sentence in the user's "
                        f"language.")
            return None
        finally:
            self._lock.release()


_instance: Presence | None = None
_inst_lock = threading.Lock()


def get_presence() -> Presence:
    global _instance
    with _inst_lock:
        if _instance is None:
            _instance = Presence()
        return _instance
