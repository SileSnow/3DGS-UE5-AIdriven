#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_sample_kmz.py — 用 Python 标准库生成一个最小可用的 DJI WPML KMZ 样例。

用途：给 docs/research/10_KMZ_WPML航线格式与任务下发.md 提供可复现的最小样例。
说明：
  * 仅使用标准库 zipfile + xml.etree.ElementTree + 字符串模板，无第三方依赖。
  * 结构严格对照官方 WPML 文档：wpmz/template.kml + wpmz/waylines.wpml（+ res/ 目录）。
  * 本样例为「格式样例」，未在真机上验证；droneEnumValue/payloadEnumValue 为占位值
    （官方文档未给出 Mini 4 Pro 的枚举值，TODO(未确认)），禁止直接用于真实飞行任务。
  * 官方字段来源：https://developer.dji.com/doc/cloud-api-tutorial/en/api-reference/dji-wpml/overview.html
    template-kml.html / waylines-wpml.html / common-element.html（本地证据 data/dji/raw/cloudapi/）。

用法：
    python make_sample_kmz.py                    # 输出到脚本同目录 sample_mission.kmz
    python make_sample_kmz.py --out /path/x.kmz  # 指定输出路径
"""
import argparse
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile

WPML_NS = "http://www.dji.com/wpmz/1.0.2"
KML_NS = "http://www.opengis.net/kml/2.2"
KMZ_ROOT = "wpmz"
TEMPLATE_NAME = "template.kml"
WAYLINES_NAME = "waylines.wpml"

# ---- 任务参数（与 llm_drone/spec/sample_mission.json 的约定保持一致：相对起飞点 40m，5m/s） ----
CENTER_LAT, CENTER_LON = 39.9042, 116.4074      # 北京（仅示例坐标）
ALT_REL_M = 40.0
SPEED_MPS = 5.0
GIMBAL_PITCH = -45.0
TAKE_OFF_SECURITY_HEIGHT = 20.0
GLOBAL_TRANSITIONAL_SPEED = 5.0

# 6 个航点：3 列 x 2 行网格，间距约 20m（0.00018 度 ≈ 20m）
WAYPOINTS = [
    (CENTER_LAT - 0.00018, CENTER_LON - 0.00018),
    (CENTER_LAT - 0.00018, CENTER_LON + 0.00018),
    (CENTER_LAT - 0.00018, CENTER_LON + 0.00054),
    (CENTER_LAT + 0.00018, CENTER_LON - 0.00018),
    (CENTER_LAT + 0.00018, CENTER_LON + 0.00018),
    (CENTER_LAT + 0.00018, CENTER_LON + 0.00054),
]


def build_action_group(group_id: int, index: int) -> str:
    """航点动作：先云台转 -45°（绝对角），再单拍。字段名全部来自官方 common-element 页。"""
    return f"""      <wpml:actionGroup>
        <wpml:actionGroupId>{group_id}</wpml:actionGroupId>
        <wpml:actionGroupStartIndex>{index}</wpml:actionGroupStartIndex>
        <wpml:actionGroupEndIndex>{index}</wpml:actionGroupEndIndex>
        <wpml:actionGroupMode>sequence</wpml:actionGroupMode>
        <wpml:actionTrigger>
          <wpml:actionTriggerType>reachPoint</wpml:actionTriggerType>
        </wpml:actionTrigger>
        <wpml:action>
          <wpml:actionId>0</wpml:actionId>
          <wpml:actionActuatorFunc>gimbalRotate</wpml:actionActuatorFunc>
          <wpml:actionActuatorFuncParam>
            <wpml:gimbalRotateMode>absoluteAngle</wpml:gimbalRotateMode>
            <wpml:gimbalPitchRotateEnable>1</wpml:gimbalPitchRotateEnable>
            <wpml:gimbalPitchRotateAngle>{GIMBAL_PITCH:g}</wpml:gimbalPitchRotateAngle>
            <wpml:gimbalRollRotateEnable>0</wpml:gimbalRollRotateEnable>
            <wpml:gimbalRollRotateAngle>0</wpml:gimbalRollRotateAngle>
            <wpml:gimbalYawRotateEnable>0</wpml:gimbalYawRotateEnable>
            <wpml:gimbalYawRotateAngle>0</wpml:gimbalYawRotateAngle>
            <wpml:gimbalRotateTimeEnable>0</wpml:gimbalRotateTimeEnable>
            <wpml:gimbalRotateTime>0</wpml:gimbalRotateTime>
            <wpml:payloadPositionIndex>0</wpml:payloadPositionIndex>
          </wpml:actionActuatorFuncParam>
        </wpml:action>
        <wpml:action>
          <wpml:actionId>1</wpml:actionId>
          <wpml:actionActuatorFunc>takePhoto</wpml:actionActuatorFunc>
          <wpml:actionActuatorFuncParam>
            <wpml:fileSuffix>wp{index:02d}</wpml:fileSuffix>
            <wpml:payloadPositionIndex>0</wpml:payloadPositionIndex>
          </wpml:actionActuatorFuncParam>
        </wpml:action>
      </wpml:actionGroup>
"""


def build_template_kml() -> str:
    placemarks = []
    for i, (lat, lon) in enumerate(WAYPOINTS):
        placemarks.append(f"""    <Placemark>
      <Point>
        <coordinates>{lon:.8f},{lat:.8f}</coordinates>
      </Point>
      <wpml:index>{i}</wpml:index>
      <wpml:ellipsoidHeight>{ALT_REL_M:g}</wpml:ellipsoidHeight>
      <wpml:height>{ALT_REL_M:g}</wpml:height>
      <wpml:useGlobalHeight>1</wpml:useGlobalHeight>
      <wpml:useGlobalSpeed>1</wpml:useGlobalSpeed>
      <wpml:useGlobalHeadingParam>1</wpml:useGlobalHeadingParam>
      <wpml:useGlobalTurnParam>1</wpml:useGlobalTurnParam>
      <wpml:gimbalPitchAngle>{GIMBAL_PITCH:g}</wpml:gimbalPitchAngle>
{build_action_group(i, i)}    </Placemark>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="{KML_NS}" xmlns:wpml="{WPML_NS}">
  <Document>
    <!-- 创建信息 -->
    <wpml:author>sdk-docs</wpml:author>
    <wpml:createTime>1762600000000</wpml:createTime>
    <wpml:updateTime>1762600000000</wpml:updateTime>
    <!-- 任务信息 -->
    <wpml:missionConfig>
      <wpml:flyToWaylineMode>safely</wpml:flyToWaylineMode>
      <wpml:finishAction>goHome</wpml:finishAction>
      <wpml:exitOnRCLost>goContinue</wpml:exitOnRCLost>
      <wpml:executeRCLostAction>hover</wpml:executeRCLostAction>
      <wpml:takeOffSecurityHeight>{TAKE_OFF_SECURITY_HEIGHT:g}</wpml:takeOffSecurityHeight>
      <wpml:globalTransitionalSpeed>{GLOBAL_TRANSITIONAL_SPEED:g}</wpml:globalTransitionalSpeed>
      <wpml:droneInfo>
        <!-- TODO(未确认)：Mini 4 Pro 的 droneEnumValue 官方文档未列，0 仅为占位 -->
        <wpml:droneEnumValue>0</wpml:droneEnumValue>
        <wpml:droneSubEnumValue>0</wpml:droneSubEnumValue>
      </wpml:droneInfo>
      <wpml:payloadInfo>
        <wpml:payloadEnumValue>0</wpml:payloadEnumValue>
        <wpml:payloadPositionIndex>0</wpml:payloadPositionIndex>
      </wpml:payloadInfo>
    </wpml:missionConfig>
    <!-- 模板信息：航点飞行 -->
    <Folder>
      <wpml:templateType>waypoint</wpml:templateType>
      <wpml:templateId>0</wpml:templateId>
      <wpml:waylineCoordinateSysParam>
        <wpml:coordinateMode>WGS84</wpml:coordinateMode>
        <wpml:heightMode>relativeToStartPoint</wpml:heightMode>
        <wpml:positioningType>GPS</wpml:positioningType>
      </wpml:waylineCoordinateSysParam>
      <wpml:autoFlightSpeed>{SPEED_MPS:g}</wpml:autoFlightSpeed>
      <wpml:gimbalPitchMode>usePointSetting</wpml:gimbalPitchMode>
      <wpml:globalWaypointHeadingParam>
        <wpml:waypointHeadingMode>followWayline</wpml:waypointHeadingMode>
      </wpml:globalWaypointHeadingParam>
      <wpml:globalWaypointTurnMode>toPointAndStopWithDiscontinuityCurvature</wpml:globalWaypointTurnMode>
      <wpml:globalUseStraightLine>0</wpml:globalUseStraightLine>
{os.linesep.join(placemarks)}
    </Folder>
  </Document>
</kml>
"""


def build_waylines_wpml() -> str:
    placemarks = []
    for i, (lat, lon) in enumerate(WAYPOINTS):
        placemarks.append(f"""    <Placemark>
      <Point>
        <coordinates>{lon:.8f},{lat:.8f}</coordinates>
      </Point>
      <wpml:index>{i}</wpml:index>
      <wpml:executeHeight>{ALT_REL_M:g}</wpml:executeHeight>
      <wpml:waypointSpeed>{SPEED_MPS:g}</wpml:waypointSpeed>
      <wpml:waypointHeadingParam>
        <wpml:waypointHeadingMode>followWayline</wpml:waypointHeadingMode>
      </wpml:waypointHeadingParam>
      <wpml:waypointTurnParam>
        <wpml:waypointTurnMode>toPointAndStopWithDiscontinuityCurvature</wpml:waypointTurnMode>
        <wpml:waypointTurnDampingDist>0</wpml:waypointTurnDampingDist>
      </wpml:waypointTurnParam>
      <wpml:useStraightLine>0</wpml:useStraightLine>
{build_action_group(i, i)}    </Placemark>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="{KML_NS}" xmlns:wpml="{WPML_NS}">
  <Document>
    <!-- 任务信息（与 template.kml 保持一致） -->
    <wpml:missionConfig>
      <wpml:flyToWaylineMode>safely</wpml:flyToWaylineMode>
      <wpml:finishAction>goHome</wpml:finishAction>
      <wpml:exitOnRCLost>goContinue</wpml:exitOnRCLost>
      <wpml:executeRCLostAction>hover</wpml:executeRCLostAction>
      <wpml:takeOffSecurityHeight>{TAKE_OFF_SECURITY_HEIGHT:g}</wpml:takeOffSecurityHeight>
      <wpml:globalTransitionalSpeed>{GLOBAL_TRANSITIONAL_SPEED:g}</wpml:globalTransitionalSpeed>
      <wpml:droneInfo>
        <wpml:droneEnumValue>0</wpml:droneEnumValue>
        <wpml:droneSubEnumValue>0</wpml:droneSubEnumValue>
      </wpml:droneInfo>
      <wpml:payloadInfo>
        <wpml:payloadEnumValue>0</wpml:payloadEnumValue>
        <wpml:payloadPositionIndex>0</wpml:payloadPositionIndex>
      </wpml:payloadInfo>
    </wpml:missionConfig>
    <!-- 可执行航线：一个 Folder = 一条 wayline -->
    <Folder>
      <wpml:templateId>0</wpml:templateId>
      <wpml:executeHeightMode>relativeToStartPoint</wpml:executeHeightMode>
      <wpml:waylineId>0</wpml:waylineId>
      <wpml:autoFlightSpeed>{SPEED_MPS:g}</wpml:autoFlightSpeed>
{os.linesep.join(placemarks)}
    </Folder>
  </Document>
</kml>
"""


def build_kmz(out_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 目录条目（官方结构含 res/，可为空）
        zf.writestr(f"{KMZ_ROOT}/", b"")
        zf.writestr(f"{KMZ_ROOT}/{TEMPLATE_NAME}", build_template_kml().encode("utf-8"))
        zf.writestr(f"{KMZ_ROOT}/{WAYLINES_NAME}", build_waylines_wpml().encode("utf-8"))


def verify_kmz(path: str) -> None:
    """自检：zip 可打开、必需条目存在、两个 XML 可解析、waypoint 数一致。"""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert f"{KMZ_ROOT}/{TEMPLATE_NAME}" in names, names
        assert f"{KMZ_ROOT}/{WAYLINES_NAME}" in names, names
        template = ET.fromstring(zf.read(f"{KMZ_ROOT}/{TEMPLATE_NAME}"))
        waylines = ET.fromstring(zf.read(f"{KMZ_ROOT}/{WAYLINES_NAME}"))
    tag = f"{{{KML_NS}}}Placemark"
    n_t = len(template.findall(f".//{tag}"))
    n_w = len(waylines.findall(f".//{tag}"))
    assert n_t == n_w == len(WAYPOINTS), (n_t, n_w, len(WAYPOINTS))
    print(f"[OK] {path}: entries={len(names)} template_placemarks={n_t} wayline_placemarks={n_w}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a minimal DJI WPML KMZ sample (stdlib only).")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_mission.kmz"))
    args = ap.parse_args()
    build_kmz(args.out)
    verify_kmz(args.out)
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
