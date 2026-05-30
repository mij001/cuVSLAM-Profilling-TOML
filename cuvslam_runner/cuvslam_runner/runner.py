"""The tracking loop: wire a FrameSource to a cuVSLAM Tracker, driven by Config."""

from __future__ import annotations

import os
import threading
import time
from typing import List, Optional

import numpy as np

from . import builders
from .config import Config
from .images import empty_image
from .sources import FrameEvent, ImuEvent, build_source
from .trajectory import TrajectoryWriter
from .viz import make_visualizer


def _resolve_pose_source(config: Config) -> str:
    if config.output.pose_source != "auto":
        return config.output.pose_source
    return "slam" if config.slam.enabled else "odometry"


def _maybe_inject_depth_scale(config: Config, source) -> None:
    """If RGBD mode is requested without an explicit scale, borrow it from the source."""
    spec = config.odometry
    if spec.odometry_mode == "RGBD" and spec.rgbd is None:
        scale = getattr(source, "depth_scale", None)
        if callable(scale):
            scale = None
        if scale:
            from .specs import RGBDSpec
            spec.rgbd = RGBDSpec(depth_scale_factor=float(scale))


def _build_imu_measurement(event: ImuEvent):
    import cuvslam
    return cuvslam.ImuMeasurement(
        timestamp_ns=int(event.timestamp_ns),
        linear_accelerations=np.asarray(event.linear_accelerations, dtype=np.float64),
        angular_velocities=np.asarray(event.angular_velocities, dtype=np.float64),
    )


def _localize(tracker, config: Config, first_frame: FrameEvent) -> bool:
    """Run localization in an existing map before the main loop. Returns success."""
    loc = config.slam.localize
    settings = builders.build_localization_settings(loc)
    guess = builders.build_pose(loc.guess)
    sync = bool(config.slam.sync_mode)

    done = threading.Event()
    result = {"pose": None}

    def callback(pose, error_message):
        result["pose"] = pose
        print(f"[localize] result={pose}, message={error_message!r}")
        done.set()

    ts = int(first_frame.timestamp_ns)
    tracker.track(ts, first_frame.images)
    tracker.localize_in_map(loc.map_path, guess, first_frame.images, settings, callback)

    if sync:
        return result["pose"] is not None

    deadline = time.time() + 10.0
    while not done.wait(timeout=0.5) and time.time() < deadline:
        ts += 1_000_000  # 1 ms steps; keeps timestamps strictly increasing
        tracker.track(ts, first_frame.images)
    return result["pose"] is not None


def run(config: Config) -> dict:
    """Execute a full tracking run described by ``config``. Returns a summary dict."""
    import cuvslam

    if config.run.verbosity:
        cuvslam.set_verbosity(config.run.verbosity)
    if config.run.warm_up_gpu:
        cuvslam.warm_up_gpu()

    source = build_source(config.input)
    _maybe_inject_depth_scale(config, source)

    rig_spec = config.rig or source.build_rig_spec()
    if rig_spec is None:
        raise ValueError(
            f"Input type {config.input['type']!r} does not provide calibration; "
            "define an explicit [rig] with [[rig.cameras]] in the TOML."
        )
    if source.num_cameras and len(rig_spec.cameras) != source.num_cameras:
        print(
            f"[runner] warning: rig has {len(rig_spec.cameras)} cameras but source "
            f"produces {source.num_cameras} image streams."
        )

    rig = builders.build_rig(rig_spec)
    odom_cfg = builders.build_odometry_config(config.odometry)
    slam_cfg = builders.build_slam_config(config.slam)
    tracker = cuvslam.Tracker(rig, odom_cfg, slam_cfg)

    inertial = (config.odometry.odometry_mode == "Inertial") and rig_spec.imu is not None
    pose_source = _resolve_pose_source(config)
    n_cams = len(rig_spec.cameras)

    writer = TrajectoryWriter(config.output.trajectory, config.output.timestamp_unit) \
        if config.output.trajectory else None
    viz = make_visualizer(config.output.visualize)

    events = iter(source)

    # Optional: localize in an existing map first.
    pending_first: Optional[FrameEvent] = None
    if config.slam.enabled and config.slam.localize and config.slam.localize.map_path:
        for ev in events:
            if isinstance(ev, ImuEvent):
                if inertial:
                    tracker.register_imu_measurement(0, _build_imu_measurement(ev))
                continue
            ok = _localize(tracker, config, ev)
            print(f"[localize] {'succeeded' if ok else 'failed/timed out'}")
            pending_first = ev  # re-track in the main loop for continuity
            break

    frames_tracked = 0
    frames_seen = 0
    failures = 0
    start_index = config.run.start_index
    max_frames = config.run.max_frames
    print_every = config.output.print_every

    def handle_frame(event: FrameEvent) -> None:
        nonlocal frames_tracked, failures
        images = _aligned(event.images, n_cams, empty_image())
        depths = _aligned(event.depths, n_cams, _empty_depth()) if event.depths else None
        masks = _aligned(event.masks, n_cams, empty_image()) if event.masks else None

        pose_estimate, slam_pose = tracker.track(event.timestamp_ns, images, masks, depths)
        valid = pose_estimate.world_from_rig is not None
        if not valid:
            failures += 1
            return
        frames_tracked += 1

        odom_pose = pose_estimate.world_from_rig.pose
        chosen = slam_pose if (pose_source == "slam" and slam_pose is not None) else odom_pose
        if writer is not None and chosen is not None:
            writer.add(event.timestamp_ns, chosen.translation, chosen.rotation)

        if viz.enabled:
            obs = tracker.get_last_observations(0) if config.odometry.enable_observations_export else None
            img0 = images[0] if images and images[0].size else None
            viz.log_frame(event.meta.get("frame", frames_tracked), event.timestamp_ns,
                          chosen if chosen is not None else odom_pose, image=img0, observations=obs)

    try:
        if pending_first is not None:
            frames_seen += 1
            if frames_seen > start_index:
                handle_frame(pending_first)

        for ev in events:
            if isinstance(ev, ImuEvent):
                if inertial:
                    tracker.register_imu_measurement(0, _build_imu_measurement(ev))
                continue

            frames_seen += 1
            if frames_seen <= start_index:
                continue

            handle_frame(ev)

            if print_every and frames_tracked and frames_tracked % print_every == 0:
                print(f"[runner] tracked {frames_tracked} frames "
                      f"({failures} failures so far)")
            if config.run.sleep_ms > 0:
                time.sleep(config.run.sleep_ms / 1000.0)
            if max_frames and frames_tracked >= max_frames:
                break
    finally:
        source.close()

    if writer is not None and len(writer):
        writer.save()
        print(f"[runner] wrote {len(writer)} poses to {config.output.trajectory}")

    if config.output.save_map and slam_cfg is not None:
        _save_map(tracker, config.output.save_map)

    summary = {
        "frames_tracked": frames_tracked,
        "track_failures": failures,
        "pose_source": pose_source,
        "slam_enabled": config.slam.enabled,
    }
    print(f"[runner] done: {summary}")
    return summary


def _aligned(items: Optional[List[np.ndarray]], n: int, filler: np.ndarray) -> List[np.ndarray]:
    """Pad/trim a per-camera list to exactly ``n`` entries using ``filler``."""
    items = list(items) if items else []
    if len(items) < n:
        items = items + [filler] * (n - len(items))
    return items[:n]


def _empty_depth() -> np.ndarray:
    return np.empty((0, 0), dtype=np.uint16)


def _save_map(tracker, folder: str) -> None:
    saved = threading.Event()
    state = {"ok": False}

    def cb(success):
        state["ok"] = success
        saved.set()

    os.makedirs(folder, exist_ok=True)
    tracker.save_map(folder, cb)
    if saved.wait(timeout=30.0):
        print(f"[runner] map saved to {folder}: {'ok' if state['ok'] else 'FAILED'}")
    else:
        print(f"[runner] map save to {folder} timed out")
