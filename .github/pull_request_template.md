## 改动内容

<!-- 一句话说明：改了什么、为什么 -->

## 关联阶段 / 目录

- [ ] Phase-0（pipeline / capture / ue5 / report）
- [ ] Phase-1（llm_drone：orchestrator / sim / safety / ue5_mission / msdk_bridge）
- [ ] 文档（docs / README）
- [ ] 仓库工程（.github / scripts / data samples）

## 如何验证

<!-- 贴命令与关键输出；涉及 UE5 请附 validation*.json 结果 -->

```powershell
cd llm_drone
python -m unittest discover -s tests -v
python logs\lead\verify_acceptance.py --port 8766
```

## 风险与回滚

<!-- 是否影响 spec / 安全层 / 工具契约？如何回滚？ -->

## 检查清单

- [ ] 已阅读并遵循 [CONTRIBUTING.md](../CONTRIBUTING.md)
- [ ] 未提交大文件（data/、Binaries/、Intermediate/、日志、venv）
- [ ] 如改动协议/工具/错误码，已同步 `llm_drone/spec/` 与测试
- [ ] 如改动安全层，已补对抗测试
- [ ] 如改动数据契约，已更新 `shared/CONVENTIONS.md` / `data/README.md`
