# 显微图像工作台 Microscopy Workbench

面向 iGEM 队伍及其他研究人员的本地显微图像处理工具。它提供两种三维观察方法，以及可交互选择固定视野、时间区间和计时零点的 GIF／MP4 导出，并保存能够重算的参数与来源记录。

[English](README.md) · [处理方法与解释范围](docs/METHODS.md) · [验证范围](docs/VALIDATION.md) · [输出文件说明](docs/OUTPUTS.md) · [下载发布版](https://github.com/xuanyuelingwu/microscopy-workbench/releases)

浏览器界面连接本机 `127.0.0.1` 上的 Python 服务，图像不上传到外部服务器。HTML 是交互界面，ND2 解析和计算由本地 Python 完成；不能只双击 HTML 而跳过服务。

## 能力范围

| 功能 | 实现内容 | 解释边界 |
| --- | --- | --- |
| 原生位置三维显示 | 按标定后的真实采样 XYZ 显示合格像素，分别调整通道不透明度，查看原生层切片与同位置共现 | 点显示可以明确抽样，重叠统计仍使用全部原生像素。 |
| 强度等值面 | Marching cubes 表面、旋转观察、保留非均匀 Z 坐标、导出 PLY | 表面是在采样点之间定位的插值结果，不增加实测空间分辨率。 |
| 时间序列导出 | 先生成全视野预览，在任意原生帧选固定 ROI，独立设置区间和计时零点 | 整片固定显示映射，不自动追踪或校正漂移。 |
| GIF 与 MP4 | 同时导出全视野和局部视野，时间与比例尺放在独立页脚 | 按原记录时序编码，精度受 GIF／MP4 格式和播放器限制。 |
| 参数重放 | 保存源文件 SHA-256、参数、软件与代码版本、帧映射和校验清单 | 默认要求匹配原文件；用于新文件时需要显式指定。 |

## 安装与启动

使用 **Python 3.12**，主要依赖版本固定在 [requirements.txt](requirements.txt)，另保留[Windows／Python 3.12 的完整新装环境快照](requirements-lock-windows-py312.txt)。首次安装需要联网；依赖装好后可离线计算，Plotly JavaScript 已本地打包。

Windows 用户可下载发布 ZIP 并解压，依次运行 `install.bat`、`start.bat`，保留服务窗口运行。也可手动执行：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

Linux／macOS 可使用：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

默认端口为 8876；被占用时依次尝试后续端口。程序打开带本地会话令牌的页面。命令行加 `--no-browser` 可只启动服务。

当前交互界面为中文，另附[英文操作对照](docs/QUICKSTART_EN.md)。首版在 Windows 开发并核查了交互操作，GitHub CI 对 Windows 和 Linux 运行可移植测试；是否通过以实际检查结果为准。macOS 的命令不代表已完成该平台验证。

## 输入要求

- Nikon ND2：灰度通道，逐原生采集帧读取，可明确固定位置、时间或 Z 等其他维度。
- OME-TIFF：单个 series、明确的灰度轴定义和物理标定。示例包含非等间距 Z 与不等间隔时间。
- 三维任务至少需要两层 Z；视频任务至少需要两个时间点。元数据不足时，仅填写已知的实际标定或时间参数。

不支持 RGB 相机 ND2、轴含义不明确的 Q／I／S TIFF、多 series OME-TIFF 以及未下载完整的文件。不能直接输入普通图片文件夹、CZI、LIF 或任意视频。转换 TIFF 时应保留 OME 的维度、单位和时间信息，程序不根据数组形状猜测。

## 快速操作

1. 运行本地服务，选择 ND2／OME-TIFF；大文件可输入完整本机路径，避免额外复制。文件选择功能会复制到本地 `workspace/uploads`。
2. 检查采集维度、通道和物理标定，设置统一显示范围、背景与阈值。
3. 时间序列先生成完整全视野预览。在任意原生帧画框、移动／缩放固定 ROI，设包含终止帧的时间区间；计时零点可位于区间之外。导出全视野与局部 GIF／MP4。
4. 三维任务明确固定时间和位置，生成原生位置点与等值面。分别调整通道透明度，并用原生切片核查金色同位置共现。

## 合成示例与复算

[examples/](examples/) 中两个 OME-TIFF 都明确标为 **SYNTHETIC**，用于软件演示，不是实验结果。另有生成脚本、配置与独立参考数值。

```sh
python replay.py --source examples/SYNTHETIC_nonuniform_Z.ome.tif --settings examples/volume_settings.json --output demo_volume
python replay.py --source examples/SYNTHETIC_irregular_time.ome.tif --settings examples/video_settings.json --output demo_video
```

打开 `demo_volume/viewer.html` 观察两种三维方法；视频示例产生全视野和局部 GIF／MP4。

重放自己的结果：

```sh
python replay.py --source original.nd2 --settings saved_result/settings.json --output replayed_result
```

默认要求源文件 SHA-256 一致；对新文件使用相同协议需加 `--allow-different-source`。输出目录须不存在或为空。数值、ROI、原生帧映射和参数可以复算，不承诺不同系统的有损视频二进制完全一致。

每次结果包括参数、源文件标识、软件／代码指纹、方法说明、数值表与校验清单。结果 ZIP 不含原始 ND2，但来源记录会保留本机源路径，分享结果前请核对。详见[输出文件说明](docs/OUTPUTS.md)。

## 科研使用边界

共现指标反映实测采样位置上、阈值条件下的空间关系，不等价于分子结合、绝对浓度、材料液态性质或处理间生物学显著性。合并比例保留通道增益与标记等因素的权重。界面中的默认阈值只是可调整起点，不能视为不同实验的通用规则。

当前版本不做去卷积、超分辨率、自动细胞／细胞核分割、液滴追踪、FRAP 模型拟合、通道配准或自动漂移校正。三维积分为原生强度扣背景后乘 XY 像素面积、跨实测层求和，**不是连续空间体积积分**；不将不同 Z 层投影的交叠当作同层共现。

三维仍需在内存中组装选定体数据，密集表面或大体积可能超过工作站和浏览器的能力。减少显示点不改变原生像素统计。详细定义见[方法文件](docs/METHODS.md)。

## 验证与社区贡献

```sh
python -m unittest discover -s tests -p "test_*.py" -v
```

原先十项数值和合成端到端测试覆盖门限边界、重叠积分、真实点坐标、非均匀 Z 表面、计时量化、奇数尺寸、固定 LUT 与 TIFF 轴处理。公开版增加发布包内容测试。项目内还使用三个真实 ND2 核查读入、备份、表面与时间导出，并检查浏览器交互；这些实验原图不随代码分发。

该工具来自 NucleArk 项目的显微图像工作，把实际使用的三维与视频计算核心、配置与验证示例交付其他队伍复用。当前不宣称已完成独立实验室验证、适配所有显微镜，或已被外部队伍采用。证据范围见[验证说明](docs/VALIDATION.md)。

## 许可与引用

自有代码和文档使用 [MIT 许可](LICENSE)，依赖库保留各自许可，见 [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt) 与 [third_party_licenses/](third_party_licenses/)。欢迎 iGEM 队伍和其他研究人员使用、修改和贡献。

使用时通过 GitHub 的 Cite this repository 或 [CITATION.cff](CITATION.cff) 引用，并在方法中记录实际版本、处理参数与源文件身份。问题反馈和改进建议见 [CONTRIBUTING.md](CONTRIBUTING.md)。
