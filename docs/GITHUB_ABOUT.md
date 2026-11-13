# GitHub 仓库描述与发布信息（可直接复制）

## 1. About 描述（一句话，建议填在 GitHub About 栏）

> DJI Mini 航拍 → 3DGS 重建 → UE5.8 渲染的可行性验证，以及 LLM tool-call 安全调度无人机的仿真闭环（真实本地 LLM、13/13 场景 PASS、118 单测、gsplat 加速 40×）。

英文版（可选）：

> End-to-end validation of DJI Mini → 3DGS → Unreal Engine 5.8 rendering, plus a safe LLM tool-calling drone orchestration loop (real local LLM, 13/13 scenarios, 118 tests, gsplat 40x faster).

## 2. About 长描述（可选，填在 README 顶部或仓库介绍）

这是一个**可复现的工程验证仓库**：Phase-0 验证「DJI Mini 航拍 → 3DGS 重建 → UE5.8 渲染」；Phase-1 验证「自然语言 → LLM 工具调用 → 确定性安全层 → 无人机任务 → 航拍数据 → 3DGS」。
无真机飞行：Phase-1 全程仿真 + UE5 虚拟相机；Phase-2 真机桥仅交付设计与 Kotlin 骨架。所有量化结论都有落盘证据，基线可在 3 分钟内复跑（118 tests + 27/27 黑盒验收）。

## 3. Topics（GitHub topics，建议全选或按需删减）

```
unreal-engine-5
3dgs
gaussian-splatting
gsplat
dji
dji-msdk
drone
llm
tool-calling
ollama
python
simulation
digital-twin
photogrammetry
colmap
robotics
agents
windows
cuda
pytorch
```

## 4. 首次发布说明（Release v1.0）

```
v1.0 — 两阶段可行性验证 + 3DGS/gsplat 演示闭环

Phase-0（DJI Mini × UE5 × 3DGS）
- 合成航拍数据集：175 train + 15 val @1600×1200（UE5.8 程序化场景）
- 自研 pure-PyTorch 3DGS：109,376 splat / 3000 iter / val PSNR 13.28
- Italink 3DGS 插件移植 UE5.8 编译通过；Path B 点云预览 30.8 fps
- 可行性报告 + 13 页 PPTX + 5 张图（视频与大数据不入库）

Phase-1（LLM Tool-Call 安全调度）
- 15 个工具 / 三级风险 / 飞行工具强 confirm；确定性 SafetyValidator（限高限速/围栏/禁飞区/电量/GPS/链路/审计）
- 真实本地 LLM（Ollama qwen3.5:4b）驱动：13/13 场景 PASS
- 118 单测 OK、27/27 独立黑盒验收 PASS、25 个 demo run 十件套齐全
- UE5 虚拟相机渲染真实 LLM 任务 20 帧；Phase-2 Android MSDK v5 桥设计 + 23 个 Kotlin 文件（未编译、未真机）

3DGS 演示片 v4 → v6
- v6：gsplat CUDA 后端（960×720、199,298 splat、40k iter、val PSNR 16.62 dB），
  每 iter 4.5 ms（puretorch 的 40×）、显存 260 MB；UE5 加载 PLY + 演示视频流程复现
（视频/PLY 体积大，不入库；复现命令见 docs/QUICKSTART.md）

Release 资产
- DJI3DGS_UE_Win64_Demo_v1.0.zip：UE5.8 packaged build（cooked，免安装），
  解压双击 run_demo.bat 即可实时预览 v6 3DGS 模型（约 1 GB；Path B 点云预览）
```

## 5. 上传前检查清单

- [ ] 在 GitHub 新建空仓库（不要勾选 README/LICENSE/gitignore，避免冲突）；
- [ ] `git remote add origin <url>` + `git push -u origin main`；
- [ ] 在 About 栏粘贴 §1 描述 + §3 topics；
- [ ] 确认 License 显示为 MIT（根目录 `LICENSE`）；
- [ ] 如需 CFF 引用，确认 `CITATION.cff` 的 license 为 MIT；
- [ ] 可选：在仓库 Settings 里开启 Actions（`.github/workflows/tests.yml` 会自动跑单测+验收）。
