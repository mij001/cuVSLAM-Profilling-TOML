"""Smoke tests that exercise config parsing + source wiring without cuvslam.

Run with:  python -m pytest tests/  (from the cuvslam_runner directory)
or simply: python tests/test_smoke.py
"""

from __future__ import annotations

import os
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cuvslam_runner.config import load_config
from cuvslam_runner.sources import build_source
from cuvslam_runner.sources.base import FrameEvent
from cuvslam_runner.images import load_image, load_depth


def _make_dataset(root: str, n: int = 4) -> None:
    for cam in ("image_0", "image_1"):
        os.makedirs(os.path.join(root, cam), exist_ok=True)
        for i in range(n):
            arr = (np.random.rand(8, 12) * 255).astype(np.uint8)
            Image.fromarray(arr, mode="L").save(os.path.join(root, cam, f"{i:06d}.png"))
    with open(os.path.join(root, "times.txt"), "w") as handle:
        for i in range(n):
            handle.write(f"{i * 0.1:.6f}\n")


def _write_config(path: str, root: str) -> None:
    with open(path, "w") as handle:
        handle.write(f"""
[run]
verbosity = 0

[input]
type = "image_folder"
root = "{root}"
  [[input.cameras]]
  images = "image_0/*.png"
  [[input.cameras]]
  images = "image_1/*.png"
  [input.timestamps]
  mode = "file"
  path = "times.txt"
  unit = "s"

[odometry]
odometry_mode = "Multicamera"
multicam_mode = "Performance"
rectified_stereo_camera = true

[[rig.cameras]]
size = [12, 8]
focal = [10.0, 10.0]
principal = [6.0, 4.0]

[[rig.cameras]]
size = [12, 8]
focal = [10.0, 10.0]
principal = [6.0, 4.0]
  [rig.cameras.rig_from_camera]
  translation = [0.5, 0.0, 0.0]

[output]
trajectory = "out/traj.txt"
""")


def test_config_and_source():
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "seq")
        _make_dataset(root, n=4)
        cfg_path = os.path.join(tmp, "cfg.toml")
        _write_config(cfg_path, root)

        config = load_config(cfg_path)
        assert config.input["type"] == "image_folder"
        assert config.odometry.odometry_mode == "Multicamera"
        assert config.rig is not None and len(config.rig.cameras) == 2

        source = build_source(config.input)
        assert source.num_cameras == 2
        assert len(source) == 4

        events = list(source)
        assert len(events) == 4
        assert all(isinstance(e, FrameEvent) for e in events)
        # timestamps strictly increasing, in ns, from the 0.1s steps
        ts = [e.timestamp_ns for e in events]
        assert ts == sorted(ts) and ts[1] - ts[0] == 100_000_000
        # two images per frame, correct dtype/shape
        for e in events:
            assert len(e.images) == 2
            for img in e.images:
                assert img.dtype == np.uint8 and img.shape == (8, 12)
    print("test_config_and_source: OK")


def test_timestamp_modes():
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "seq")
        _make_dataset(root, n=3)
        # fps mode via direct dict
        src = build_source({
            "type": "image_folder",
            "root": root,
            "cameras": [{"images": "image_0/*.png"}],
            "timestamps": {"mode": "fps", "fps": 10.0},
        })
        ts = [e.timestamp_ns for e in src]
        assert ts == [0, 100_000_000, 200_000_000]
    print("test_timestamp_modes: OK")


def test_unknown_key_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = os.path.join(tmp, "bad.toml")
        with open(cfg_path, "w") as handle:
            handle.write('[input]\ntype = "image_folder"\n\n[odometry]\nbogus_key = 1\n')
        try:
            load_config(cfg_path)
        except Exception as exc:  # noqa: BLE001
            assert "bogus_key" in str(exc)
            print("test_unknown_key_rejected: OK")
            return
        raise AssertionError("expected ConfigError for unknown key")


def test_image_helpers():
    with tempfile.TemporaryDirectory() as tmp:
        # RGB -> BGR ordering
        rgb = np.zeros((4, 4, 3), dtype=np.uint8)
        rgb[..., 0] = 10  # R
        rgb[..., 2] = 30  # B
        p = os.path.join(tmp, "c.png")
        Image.fromarray(rgb, "RGB").save(p)
        bgr = load_image(p, bgr=True)
        assert bgr.shape == (4, 4, 3) and bgr[0, 0, 0] == 30 and bgr[0, 0, 2] == 10

        # depth as uint16
        d = (np.arange(16).reshape(4, 4) * 100).astype(np.uint16)
        dp = os.path.join(tmp, "d.png")
        Image.fromarray(d).save(dp)
        depth = load_depth(dp)
        assert depth.dtype == np.uint16 and depth.shape == (4, 4)
    print("test_image_helpers: OK")


if __name__ == "__main__":
    test_config_and_source()
    test_timestamp_modes()
    test_unknown_key_rejected()
    test_image_helpers()
    print("\nAll smoke tests passed.")
