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

| `[input].type`  | Drives                                   | Recorded / Realtime | Modes it can drive                       | Rig from           |
|-----------------|-------------------------------------------|---------------------|------------------------------------------|--------------------|
| `image_folder`  | KITTI, TartanGround, RobotCar, arbitrary | recorded            | `Multicamera` / `Mono` / `RGBD` / **`Inertial`** (with `[input.imu]`) | explicit `[rig]`   |
| `euroc`         | EuRoC MAV (ASL)                          | recorded            | `Inertial` / `Multicamera` / `Mono`      | dataset yaml       |
| `tum`           | TUM RGB-D                                | recorded            | `RGBD`                                   | rig yaml (+`[rig]`)|
| `edex`          | TartanGround / R2B Galileo (rosbag→EDEX) | recorded            | `Multicamera`                            | `.edex` JSON       |
| `video`         | webcam, RTSP/HTTP stream, video file     | **both**            | `Multicamera` (sbs/tb split) / `Mono`    | explicit `[rig]`   |
| `realsense`     | Intel RealSense stereo                   | realtime            | `Multicamera`                            | device             |

**Any generic dataset, recorded or realtime, is covered:**

- *Recorded, any layout* → `image_folder` (one glob per camera; optional `depth`,
  `mask`, Bayer; timestamps from a file/filename/fps/index; optional `[input.imu]`
  CSV for `Inertial`). This single source spans all four odometry modes.
- *Recorded video files* (mp4/avi/…) → `video` with a file path.
- *Realtime cameras/streams* → `video` ("0" device index, `rtsp://`/`http://`
  URL, or a side-by-side stereo device via `split`) or `realsense`.
- *ROS bags* → convert offline with the Isaac ROS EDEX extractor and load via
  `edex` (the Python wheel does not read bags directly; live ROS uses the
  separate Isaac ROS node).

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

  [input.imu]                     # optional -> enables odometry_mode = "Inertial"
  path = "imu0/data.csv"
  format = "euroc"                # euroc | generic
  # generic:
  #   columns = ["timestamp","gx","gy","gz","ax","ay","az"]
  #   timestamp_unit = "ns"       # s|ms|us|ns
  #   angular_unit = "rad"        # rad|deg
  #   delimiter = ","; skip_header = true
```

The generic OpenCV **`video`** source (recorded files or realtime devices/streams):

```toml
[input]
type = "video"
  [[input.cameras]]
  source = "0"                    # device index | "rtsp://..."/"http://..." | "clip.mp4"
  split = "sbs"                   # none | sbs | tb  (split one stereo frame into two)
  grayscale = true                # convert to mono8 (default false -> BGR passthrough)
  [input.timing]
  mode = "auto"                   # auto | wallclock (realtime) | fps | index
  fps = 30
```
IMU samples (image_folder) require a `[rig.imu]` table for the IMU calibration;
the CSV supplies the samples, `[rig.imu]` supplies the noise model + extrinsics.

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
