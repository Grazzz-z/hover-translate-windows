from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

import mss
import numpy as np


@dataclass(slots=True, frozen=True)
class CaptureRegion:
    left: int
    top: int
    width: int
    height: int


@dataclass(slots=True, frozen=True)
class CaptureFrame:
    image: np.ndarray
    region: CaptureRegion


class ScreenCapture:
    def __init__(self) -> None:
        self._lock = Lock()
        self._mss = mss.mss()

    def capture_region(
        self,
        center_x: int,
        center_y: int,
        width: int,
        height: int,
    ) -> CaptureFrame:
        width = max(20, width)
        height = max(20, height)

        with self._lock:
            monitor = self._mss.monitors[0]
            left = center_x - (width // 2)
            top = center_y - (height // 2)

            min_left = monitor["left"]
            min_top = monitor["top"]
            max_left = monitor["left"] + monitor["width"] - width
            max_top = monitor["top"] + monitor["height"] - height

            left = min(max(left, min_left), max_left)
            top = min(max(top, min_top), max_top)

            grab_region = {
                "left": int(left),
                "top": int(top),
                "width": int(width),
                "height": int(height),
            }
            frame = self._mss.grab(grab_region)

        image = np.asarray(frame)[:, :, :3]
        return CaptureFrame(
            image=image,
            region=CaptureRegion(
                left=int(left),
                top=int(top),
                width=int(width),
                height=int(height),
            ),
        )

    def close(self) -> None:
        with self._lock:
            self._mss.close()
