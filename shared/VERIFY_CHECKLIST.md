# 最终验收检查清单（Lead 用）

## 证据完整性
- docs/research/: 6 个文件 + references.md 存在，关键结论含 URL；SUMMARY.md <=80 行。
- pipeline/: ENV.md、RESULTS.md、run_pipeline.ps1、01-05 脚本；data/trained/ 有 PLY + eval.json + renders。
- ue5/: RESULTS.md、metrics.json、screenshots、可编译工程；插件/组件源码。
- capture/: README.md、RESULTS.md、run_capture.ps1；data/synthetic/capture 有 images + metadata.json。
- report/: 最终报告 + 图 + 复现命令。

## 可复现性
- [ ] 从空目录按 README 步骤能重建 pipeline 环境（venv）。
- [ ] UE 工程可编译（Build.ps1）并有日志。
- [ ] 训练脚本有 CLI 且用固定 seed。
- [ ] 合成数据生成脚本可重跑。

## 事实核查
- [ ] SDK 支持矩阵与官方页面/仓库一致（Mini 4 Pro/MSDK v5.20.1；Mini 5 Pro 不支持）。
- [ ] Terra 3DGS 结论引自官方 Release Notes PDF。
- [ ] UE5.8 无内置 GS 插件（本机搜索证据）。
- [ ] 性能数字与 nvidia-smi/UE stat 日志一致。

## 交付物
- [ ] 最终报告 md（中文，含图表与证据链接）。
- [ ] 可选：PPTX 简报 / 演示视频 / docx 版本。
- [ ] 项目 README 索引更新。