# cuvslam_runner — run cuVSLAM from a single TOML file

A small, config-driven system that runs the `cuvslam` Python module end-to-end.
**The only input is one TOML file.** It declares the input source (dataset
folder, multi-camera rig, live camera, …), the camera/IMU rig, every Odometry
and SLAM knob, and where to write the output trajectory/map.

```
python run.py configs/kitti_stereo.toml            # run it
python run.py configs/kitti_stereo.toml --check     # validate config only (no cuvslam needed)
# or, as a module:
python -m cuvslam_runner configs/euroc_inertial.toml
```

## Install

```bash
pip install -r requirements.txt
# plus the cuVSLAM wheel itself:
pip install cuvslam-*.whl
```

`--check` works without `cuvslam` installed — it parses the TOML, wires the
input source, resolves the rig, and counts frames. Useful for validating a
config before launching a real run.

## How it fits together

```
TOML ─► config.py ─► specs (plain dataclasses, no cuvslam)
                         │
        sources/* ───────┤ (image_folder | euroc | tum | edex | realsense)
        produce FrameEvent / ImuEvent streams + an optional RigSpec
                         │
        builders.py ─────► turns specs into live cuvslam objects (only file importing cuvslam)
                         │
        runner.py ───────► Tracker loop ─► trajectory.py (TUM file) + viz.py (rerun)
```

The split means dataset parsing and config validation are fully testable
without a compiled cuVSLAM wheel; only `builders.py`/`runner.py` import `cuvslam`.

## Modes × inputs

| `[input].type`  | Drives                                   | Typical `odometry_mode`            | Rig from           |
|-----------------|-------------------------------------------|------------------------------------|--------------------|
| `image_folder`  | KITTI, TartanGround, RobotCar, arbitrary | `Multicamera` / `Mono` / `RGBD`    | explicit `[rig]`   |
| `euroc`         | EuRoC MAV (ASL)                          | `Inertial` / `Multicamera` / `Mono`| dataset yaml       |
| `tum`           | TUM RGB-D                                | `RGBD`                             | rig yaml (+`[rig]`)|
| `edex`          | TartanGround / R2B Galileo               | `Multicamera`                     | `.edex` JSON       |
| `realsense`     | live Intel RealSense stereo              | `Multicamera`                     | device             |

The four cuVSLAM odometry modes (`Multicamera`, `Inertial`, `RGBD`, `Mono`) and
the SLAM layer are all selected purely through the TOML — see `configs/`.

## TOML reference

### `[run]`
| key | default | meaning |
|---|---|---|
| `verbosity` | `0` | `cuvslam.set_verbosity` (0 silent … 3 info) |
| `warm_up_gpu` | `false` | call `warm_up_gpu()` before tracking |
| `start_index` | `0` | skip the first N frame events |
| `max_frames` | `0` | stop after N tracked frames (0 = all) |
| `sleep_ms` | `0` | pause between frames (helps async SLAM catch up) |

### `[input]`
`type` selects the source; remaining keys are source-specific (documented at the
top of each file in `cuvslam_runner/sources/`). The generic `image_folder`:

```toml
[input]
type = "image_folder"
root = "dataset/sequences/06"     # optional prefix for all globs
  [[input.cameras]]
  images = "image_0/*.png"        # required glob, sorted = frame order
  depth  = "depth_0/*.png"        # optional (uint16), enables depths input
  mask   = "mask_0/*.png"         # optional dynamic masks
  bayer  = "GBRG"                 # optional raw-Bayer demosaic
  bgr    = true                   # RGB->BGR on load (default true)
  [input.timestamps]
  mode = "file"                   # index | fps | file | filename
  path = "times.txt"              # for mode=file
  unit = "s"                      # s | ms | us | ns
  # fps = 30                      # for mode=fps
```

### `[[rig.cameras]]` and `[rig.imu]`
Explicit calibration. If omitted, the source supplies it (euroc/tum/edex/realsense).
A camera:

```toml
[[rig.cameras]]
size = [1241, 376]                # [width, height]
focal = [718.856, 718.856]        # [fx, fy]
principal = [607.19, 185.22]      # [cx, cy]
  [rig.cameras.rig_from_camera]   # extrinsics (camera -> rig)
  rotation = [0,0,0,1]            # quaternion x,y,z,w
  translation = [0.537,0,0]
  [rig.cameras.distortion]
  model = "Pinhole"               # Pinhole|Fisheye|Brown|Polynomial
  parameters = []
# border_top/bottom/left/right    # static feature masks (pixels)
```

```toml
[rig.imu]                         # required for odometry_mode = "Inertial"
gyroscope_noise_density = 1.0e-4
accelerometer_noise_density = 1.0e-3
gyroscope_random_walk = 1.0e-6
accelerometer_random_walk = 1.0e-5
frequency = 200.0
  [rig.imu.rig_from_imu]
  translation = [0,0,0]
```

### `[odometry]`
`odometry_mode` (`Multicamera`|`Inertial`|`RGBD`|`Mono`), `multicam_mode`
(`Performance`|`Moderate`|`Precision`), `use_gpu`, `async_sba`,
`use_motion_model`, `use_denoising`, `rectified_stereo_camera`,
`enable_observations_export`, `enable_landmarks_export`,
`enable_final_landmarks_export`, `max_frame_delta_s`, and nested
`[odometry.rgbd]` (`depth_scale_factor`, `depth_camera_id`,
`enable_depth_stereo_tracking`). Omitted optional knobs keep the library default.

### `[slam]`
Presence of this table enables SLAM. `map_cache_path`, `use_gpu`, `sync_mode`,
`enable_reading_internals`, `planar_constraints`, `gt_align_mode`,
`map_cell_size`, `max_landmarks_distance`, `max_map_size`, `throttling_time_ms`,
plus optional `[slam.localize]` (`map_path`, `[slam.localize.guess]`, search
radii/steps) to localize in an existing map before tracking.

### `[output]`
`trajectory` (TUM-format path), `pose_source` (`auto`|`odometry`|`slam`),
`timestamp_unit` (`s`|`ms`|`us`|`ns`), `save_map` (folder, SLAM only),
`visualize` (rerun), `print_every`.

## Notes
- Only debug knobs (`debug_dump_directory`, `debug_imu_mode`) are intentionally
  not exposed.
- Trajectory output is `timestamp tx ty tz qx qy qz qw` (TUM format).
- The example configs use paths relative to this directory pointing at the
  repository's `../examples/*/dataset/...`; adjust to your data.
