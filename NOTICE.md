# NOTICE — 第三方组件、商标与数据来源

## 1. 商标与 DJI 资料

- “DJI”、“DJI Mini”、“Mavic”、“MSDK”、“DJI Fly” 等是深圳市大疆创新科技有限公司（DJI）的商标。
  本项目为**独立技术验证**，与 DJI 无隶属或背书关系。
- `docs/research/` 中的 DJI 产品/ SDK / 发布说明内容均为**摘要与引用**，不复制官方文档原文；
  原始一手证据（`data/dji/raw/` 下的 HTML/PDF 抓取）**不纳入本仓库**，仅保留在作者本地，原因：体积 + 版权。
  全部来源 URL 见 `docs/research/references.md` 与各调研文档的“证据索引”。
- 本项目**不修改固件、不绕过地理围栏/限高/限速**；真机使用须遵守 DJI 产品使用条款与当地空域法规。

## 2. UE5 3DGS 插件

- `ue5/DJI3DGS_UE/Plugins/GaussianSplattingForUnrealEngine` 移植自
  [Italink/GaussianSplattingForUnrealEngine](https://github.com/Italink/GaussianSplattingForUnrealEngine)（MIT License），
  许可文件见 `ue5/_vendor/ItalinkGsplat/LICENSE` 与插件目录内 `LICENSE`。
- 其他调研过的插件（DazaiStudio、mlslabs、xgrids、yags 等）仅作技术对比，未纳入本仓库；
  许可见 `docs/research/01_DJI_Mini_SDK能力矩阵.md` / 报告。

## 3. 数据集与渲染内容

- `data/samples/ue5_mission_p1/`、`data/samples/synthetic_campus_v1/`：由本项目 `capture/` 与
  `llm_drone/ue5_mission/` 使用 UE5.8 **程序化生成**的合成场景渲染，可自由用于本项目协作。
- `data/samples/dji_real/Mini4Pro_FC8482_1600.jpg`：DJI Mini 4 Pro 公开样片，经降采样后仅用于技术演示；
  版权归 DJI / 原始拍摄者，不构成再分发许可。使用前请核对原始来源条款。
- `docs/research/` 中引用的第三方数据（公开数据集、论文）版权归各自作者所有。

## 4. 代码许可

- 本仓库代码采用 **MIT License**，全文见根目录 `LICENSE`；第三方组件（如 Italink UE 插件）保留各自许可。
- 文档内容同样以 MIT 提供；第三方数据/商标的引用不等于授权，见 §1–§3。

## 5. 参考

- 3D Gaussian Splatting: Kerbl et al., “3D Gaussian Splatting for Real-Time Radiance Field Rendering”, SIGGRAPH 2023.
- COLMAP: Schönberger & Frahm, “Structure-from-Motion Revisited”, CVPR 2016.
- DJI MSDK v5 官方文档 / 官方 GitHub：见 `docs/research/08` 的“证据索引”。
