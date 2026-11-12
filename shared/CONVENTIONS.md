# 跨 Agent 数据契约与坐标约定（Lead 维护，2026-11-08）

## 1. 合成/真实采集数据集格式（capture-synth 产出 → gs-pipeline 消费）

文件布局：
```
data/synthetic/capture/
  images/0001.png ...          # 训练视角（PNG）
  metadata.json                # 每帧相机内外参 + DJI 风格元数据
data/synthetic/val/
  images/val_0001.png ...      # 留出验证视角（不参与训练）
  metadata_val.json            # 同 schema
```

metadata.json（UTF-8，单位：像素 / 厘米 / 度）：
```json
{
  "dataset": "synthetic_dji_mini4pro_campus_v1",
  "camera_model": "DJI Mini 4 Pro (simulated)",
  "width": 1600, "height": 1200,
  "fx": 1148.3429, "fy": 1148.3429, "cx": 800.0, "cy": 600.0,
  "coord_system": "UE_LHS_Zup_cm",
  "origin_wgs84": {"lat": 39.9042, "lon": 116.4074, "alt": 43.0},
  "frames": [
    {
      "file": "images/0001.png",
      "c2w": [16 floats row-major camera-to-world in UE world (cm)],
      "gps": {"lat": 39.9042, "lon": 116.4074, "alt": 73.0},
      "gimbal_deg": {"yaw": 0.0, "pitch": -45.0, "roll": 0.0},
      "timestamp": 0.0
    }
  ]
}
```
- UE 相机轴：+X 前、+Y 右、+Z 上（左手系）；c2w 的旋转部分为相机轴在 UE 世界中的朝向。
- 验证视角允许与训练视角同格式，但不得出现在训练集。

## 2. 3DGS PLY 契约（gs-pipeline 产出 → ue5-splat 消费）

标准 3DGS PLY（binary_little_endian 1.0），每个 gaussian 顶点含：
- x y z（世界坐标，与训练数据集同一坐标系/尺度，合成数据为 UE cm）
- nx ny nz（可全 0）
- f_dc_0 f_dc_1 f_dc_2（SH DC 项）
- f_rest_0..44（SH 1-3 阶 45 个；本项目导出固定写满 45 项，不可省略，下游按字段名解析）
- opacity（sigmoid 前的 logit）
- scale_0 scale_1 scale_2（log 尺度）
- rot_0 rot_1 rot_2 rot_3（四元数 w,x,y,z 顺序，未归一化）
UE 端读取后按 3DGS 标准公式解码；坐标系与训练数据一致，scale 解码为世界单位（cm）。

## 3. 坐标系换算（UE ↔ COLMAP）

UE 世界：X 前、Y 右、Z 上，cm，左手系。
COLMAP 相机：X 右、Y 下、Z 前，右手系。
转换参考实现（pipeline 端 pipeline/colmap_io.py 落地并用投影误差验证）：
1) 世界转右手：p_w = (x_ue, -y_ue, z_ue)（翻转 Y）
2) UE 相机轴在右手世界：fwd=(1,0,0), right=(0,-1,0), up=(0,0,1)
3) R_wc = [right_w; -up_w; fwd_w] = [[0,-1,0],[0,0,-1],[1,0,0]]
4) R_cw = R_wc^T, t_cw = -R_cw * p_w；COLMAP qvec 由 R_cw 转四元数。
验证：把 3D 点投影回像素，重投影误差 < 1px 才算对。

## 4. 输出命名
- 训练输出：data/trained/<dataset>/<run>/gaussians.ply，同目录 train_log.txt、eval.json、renders/。
- UE 性能结果：ue5/results/<run>/metrics.json + screenshots/。
- 任何“声称的数字”必须能在 logs/ 或 RESULTS.md 找到原始出处。

## 5. 机器资源协调（Lead 统一调度）
- GPU 8GB，当前被 Ollama 占用约 3.6GB；如确需释放可 POST http://localhost:11434/api/generate body {"model":"qwen35-16k:latest","keep_alive":0}（非破坏性，下次调用会重载）。先检查 nvidia-smi 再决定。
- UE 编辑器 RHI 渲染（capture-synth / ue5-splat）必须串行：使用前给 lead 发消息确认。
- 训练/编译可并行，但注意 16GB RAM；出现 OOM 降低 batch/分辨率。
