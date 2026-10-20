# English walkthrough of the Chinese interface

Start `python app.py`, keep the terminal running and use the browser tab opened by the local service. Two synthetic examples are included for practice before selecting experimental data.

| Interface label | Meaning |
| --- | --- |
| 时间序列 → 视频 | Time series to video |
| 两种三维重构 | Two 3D viewing methods |
| 使用说明 | In-app guide |
| 选择本机 ND2 / OME-TIFF | Choose an image file; creates a local upload copy |
| 大文件：直接读取本机路径 | Read a full local path without copying a large input |
| 固定采集维度 | Fix other acquisition dimensions |
| 通道与显示 | Enable channels; set display limits, background and gates |
| 校准与高级参数 | Calibration overrides and advanced settings |
| 更新当前帧显示 | Apply display settings to the current frame |
| 将视频当前位置载入上方原生帧 | Load the native frame nearest the preview's current position |
| 起始帧 / 终止帧（包含） | Start frame / end frame, inclusive |
| 以当前帧为 t = 0 | Set time zero to the current native frame |
| 播放倍速 | Playback speed |
| 输出最长边 | Optional maximum output side; zero/native size avoids downsizing |
| 导出选定区间 | Export the selected interval |
| 生成两种三维视图与原生数据包 | Generate native-position and isosurface views with original data references |
| 处理进度 / 取消当前任务 | Progress / cancel current job |

## Time series

1. Select the time-series tab and open a complete ND2 or calibrated OME-TIFF. Check fixed position/Z and enabled channels.
2. Let the full-field preview finish. Use the native-frame slider, or load the frame corresponding to the preview video position.
3. Draw a rectangular ROI. Move it or resize its corners; native x/y/width/height fields provide exact coordinates. The rectangle stays fixed over time.
4. Drag the time-range endpoints or enter inclusive start/end frame numbers. Assign time zero independently, including outside the selected interval.
5. Export. Full-field and cropped GIF/MP4 files share the same timing and fixed display mapping. Open the saved frame CSV to review the exact mapping.

## 3D stack

1. Select the 3D tab, open a Z stack and fix time/position as needed.
2. Verify physical XY scale and the source of Z coordinates. Set channel backgrounds and excess-intensity gates using acquired slices.
3. Generate both methods. Open the standalone result viewer to rotate the data, adjust channel opacity, toggle gold same-sample overlap and inspect acquired planes.
4. Use native backups and `native_overlap.csv` for numerical results. Mesh contact by itself is not a quantitative overlap measurement.

See [METHODS.md](METHODS.md) for the definitions and [OUTPUTS.md](OUTPUTS.md) for provenance files.
