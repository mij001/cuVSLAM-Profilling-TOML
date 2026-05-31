# Paper-benchmark dataset coverage

This maps every dataset benchmarked in the cuVSLAM technical report
([arXiv:2506.04359](https://arxiv.org/abs/2506.04359), Tables 2 & 3) to a ready
config in `configs/`. The runner's evaluation reports the **same metrics the
paper uses** — `avgRTE %`, `avgRE deg`, `RMSE APE` (EVO-style: timestamp
association + alignment, with Sim3 scale for monocular).

| Paper mode | Dataset | Config | Source | Eval (GT) | Status |
|---|---|---|---|---|---|
| Mono-Depth | AR-table (Chen 2023) | `artable_rgbd.toml` | image_folder (rgb+depth) | TUM (template) | config — set paths/intrinsics |
| Mono-Depth | ICL-NUIM (Handa 2014) | `iclnuim_rgbd.toml` | tum | TUM `.gt.freiburg` | config — verify intrinsics |
| Mono-Depth | TUM RGB-D (Sturm 2012) | `tum_rgbd.toml` | tum | TUM `groundtruth.txt` | ✓ runnable + eval |
| Stereo | EuRoC (Burri 2016) | `euroc_v1_eval.toml` | euroc | EuRoC GT | **validated** (ATE 7.78 cm) |
| Stereo | KITTI (Geiger 2013) | `kitti_stereo.toml` | image_folder | KITTI poses* | **validated** (tracks seq06) |
| Stereo-Inertial | EuRoC (Burri 2016) | `euroc_inertial.toml` | euroc | EuRoC GT | **validated** (runs V1_01) |
| Stereo-Inertial | TUM-VI (Schubert 2018) | `tumvi_room_inertial.toml` | image_folder + imu | mocap0 (EuRoC fmt) | config — verify camchain |
| Multi-Stereo | TartanAir V2 (Wang 2023) | `tartanair_v2_multicam.toml` | edex | — (tracking) | config — convert via tool |
| Multi-Stereo | TartanGround (Patel 2025) | `tartan_multicam.toml` | edex | — (tracking) | ✓ rig parses (12 cams) |
| Multi-Stereo | R2B (NVIDIA, proprietary) | `r2b_multicam.toml` | edex (jsonl) | — (tracking) | config (data is private) |

\* KITTI ground-truth poses (`poses/<seq>.txt`) are a separate download from the
odometry images; add an `[eval]` block with `gt_format = "kitti"` once you have them.

## Status legend
- **validated** — actually run here against the cu13 wheel with real data.
- **✓** — runs/parses with the data present; format confirmed.
- **config** — schema-valid config provided; fill in the dataset path and verify
  the calibration against your specific download (intrinsics/extrinsics/depth
  scale vary per sequence and per dataset release).

## How each mode is driven
- **Mono-Depth (RGBD)** — one camera + aligned `uint16` depth. `tum` source when
  the dataset ships `rgb.txt`/`depth.txt`; `image_folder` (with a `depth` glob)
  for parallel rgb/depth folders. Set `[odometry.rgbd].depth_scale_factor`.
- **Stereo** — `euroc` (builds rig+calibration from the dataset yaml) or
  `image_folder` with an explicit `[rig]` (KITTI).
- **Stereo-Inertial** — add an IMU: `euroc` (EuRoC) or `image_folder` +
  `[input.imu]` + an explicit `[rig.imu]` (TUM-VI).
- **Multi-Stereo** — `edex`: rig (intrinsics+extrinsics for N cameras) from a
  `.edex` JSON, frames from per-camera folders (`layout = "folders"`) or a
  `frame_metadata.jsonl` manifest (`layout = "jsonl"`, R2B).

## Notes
- The "config" rows ship correct wiring and published calibration where known,
  but calibration must be confirmed against your exact download — the runner
  cannot infer intrinsics for `image_folder`/`video` sources.
- Multi-stereo GT (TartanAir/TartanGround) uses per-camera NED pose files; a
  frame-converting GT loader isn't wired, so those configs track without `[eval]`.
  EuRoC/TUM/KITTI GT formats are fully supported for ATE/RPE.
