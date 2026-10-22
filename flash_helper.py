#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vivo Xplay6 (PD1610) 9008 刷机辅助脚本
=====================================

把手工刷机中最容易出错的几个环节自动化：

  1. 环境自检   —— adb / QFIL / 9008 驱动 / 固件完整性
  2. 进入 EDL   —— 用 `adb shell reboot edl`（绕过 adb 的 root 检查）
  3. 合并分区表 —— rawprogram0~5.xml → rawprogram_all.xml（QFIL 的 Load XML 是替换不是追加）
  4. 校验 LUN   —— 合并结果的分区分布是否与机型匹配
  5. 操作指引   —— 打印 QFIL 里每一项该填什么

最后一步「点 Download」无法自动化：QFIL 不提供命令行接口。

用法
----
    python flash_helper.py check  --firmware "F:\\rom\\PD1610_D_1.18.2_..."
    python flash_helper.py merge  --firmware "F:\\rom\\PD1610_D_1.18.2_..."
    python flash_helper.py edl
    python flash_helper.py all    --firmware "F:\\rom\\PD1610_D_1.18.2_..."

仅依赖 Python 3.8+ 标准库，无需 pip 安装任何东西。

作者：<mitcarlsonlin>
许可：MIT
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

# ----------------------------------------------------------------------------
# 机型配置
# ----------------------------------------------------------------------------

MODEL = "PD1610"
DEVICE_NAME = "vivo Xplay6"

# UFS 逻辑单元(LUN)数量 -> 期望的 program 条目数
# 数据来自实测固件 PD1610_D_1.18.2
EXPECTED_LUN_DISTRIBUTION = {0: 16, 1: 3, 2: 3, 3: 6, 4: 36, 5: 6}

# 9008 端口的设备 ID
EDL_VID_PID = "VID_05C6&PID_9008"

QFIL_DEFAULT_PATHS = [
    r"C:\Program Files (x86)\Qualcomm\QPST\bin\QFIL.exe",
    r"C:\Program Files\Qualcomm\QPST\bin\QFIL.exe",
]

# 固件包里必须存在的文件（相对路径 -> 说明）
REQUIRED_FILES = {
    "prog_ufs_firehose_8996_ddr.elf": "firehose programmer (UFS)",
    "rawprogram0.xml": "LUN0 分区表",
    "rawprogram4.xml": "LUN4 分区表（含 system）",
    "patch0.xml": "LUN0 补丁",
    "system.img": "系统镜像",
    "boot.img": "内核镜像",
}

# ----------------------------------------------------------------------------
# 终端输出
# ----------------------------------------------------------------------------

_USE_COLOR = sys.stdout.isatty() and platform.system() == "Windows"


def _c(text: str, code: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def ok(msg: str) -> None:
    print(f"  {_c('[ OK ]', '32')} {msg}")


def warn(msg: str) -> None:
    print(f"  {_c('[WARN]', '33')} {msg}")


def fail(msg: str) -> None:
    print(f"  {_c('[FAIL]', '31')} {msg}")


def info(msg: str) -> None:
    print(f"  {_c('[ .. ]', '36')} {msg}")


def title(msg: str) -> None:
    print()
    print(_c(f"=== {msg} ===", "1;36"))


# ----------------------------------------------------------------------------
# 1. 环境自检
# ----------------------------------------------------------------------------


def find_adb() -> str | None:
    """找可用的 adb：先看 PATH，再看几个常见位置。"""
    p = shutil.which("adb")
    if p:
        return p
    for cand in (
        r"F:\Tools\platform-tools\adb.exe",
        r"C:\platform-tools\adb.exe",
        os.path.expanduser("~/platform-tools/adb.exe"),
    ):
        if Path(cand).exists():
            return cand
    return None


def find_qfil() -> str | None:
    for p in QFIL_DEFAULT_PATHS:
        if Path(p).exists():
            return p
    return None


def list_edl_ports() -> list[str]:
    """返回当前所有 9008 端口的友好名称。仅支持 Windows。"""
    if platform.system() != "Windows":
        return []
    cmd = (
        "Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.InstanceId -match '{EDL_VID_PID}' }} | "
        "Select-Object -ExpandProperty FriendlyName"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def check_adb_device(adb: str) -> str | None:
    """返回已连接设备的序列号，没有则 None。"""
    try:
        out = subprocess.run(
            [adb, "devices"], capture_output=True, text=True, timeout=20
        )
    except Exception:
        return None
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            return parts[0]
    return None


def check_firmware(fw: Path) -> bool:
    """检查固件目录完整性。返回是否全部通过。"""
    all_ok = True
    for name, desc in REQUIRED_FILES.items():
        p = fw / name
        if p.exists():
            size_mb = p.stat().st_size / 1024 / 1024
            ok(f"{name:<34} {size_mb:>8.2f} MB  ({desc})")
        else:
            fail(f"{name:<34}   缺失    ({desc})")
            all_ok = False

    # 6 组 rawprogram / patch 是否齐全
    for prefix in ("rawprogram", "patch"):
        missing = [f"{prefix}{i}.xml" for i in range(6) if not (fw / f"{prefix}{i}.xml").exists()]
        if missing:
            fail(f"{prefix}0~5.xml 不完整，缺少：{', '.join(missing)}")
            all_ok = False
        else:
            ok(f"{prefix}0~5.xml 齐全（6 个 LUN）")

    # 陷阱提示：只有 fastboot bat 而没有 rawprogram 的包刷不了
    if (fw / "fastboot_flash_all.bat").exists() and not (fw / "rawprogram0.xml").exists():
        warn("这个包只有 fastboot 脚本、没有 rawprogram，属于 fastboot 包，无法用于 9008")
        all_ok = False

    return all_ok


def cmd_check(args: argparse.Namespace) -> int:
    print(f"\n{_c(DEVICE_NAME + ' / ' + MODEL + '  9008 刷机环境自检', '1')}")

    title("平台")
    info(f"{platform.system()} {platform.release()} / Python {platform.python_version()}")

    title("工具链")
    adb = find_adb()
    if adb:
        ok(f"adb: {adb}")
        sn = check_adb_device(adb)
        if sn:
            ok(f"已连接设备: {sn}（可直接进 EDL）")
        else:
            warn("adb 未检测到已授权设备（需要开机 + 打开 USB 调试 + 手机点允许）")
    else:
        fail("未找到 adb，请安装 platform-tools 并加入 PATH")

    qfil = find_qfil()
    if qfil:
        ok(f"QFIL: {qfil}")
    else:
        fail("未找到 QFIL，请先安装 QPST（含 QFIL 组件）")

    title("9008 端口")
    ports = list_edl_ports()
    if ports:
        for p in ports:
            ok(p)
        info("设备已在 EDL 模式 —— 建议 5 分钟内点 Download，超时需重新进入")
    else:
        warn("当前没有 9008 端口（手机不在 EDL 模式，属正常）")

    rc = 0
    if args.firmware:
        title("固件")
        fw = Path(args.firmware)
        if not fw.is_dir():
            fail(f"目录不存在: {fw}")
            rc = 1
        elif not check_firmware(fw):
            rc = 1

    title("结论")
    if rc == 0:
        ok("环境检查通过，可以继续")
        if not ports:
            print("\n  下一步： python flash_helper.py edl")
    else:
        fail("存在问题，请先按上面的提示处理")
    return rc


# ----------------------------------------------------------------------------
# 2. 进入 EDL
# ----------------------------------------------------------------------------


def cmd_edl(args: argparse.Namespace) -> int:
    print(f"\n{_c('进入 9008 (EDL) 模式', '1')}")

    adb = find_adb()
    if not adb:
        fail("未找到 adb")
        return 1

    title("检查已有 EDL 端口")
    if list_edl_ports():
        ok("设备已在 EDL 模式，无需重复操作")
        return 0

    title("检查 adb 连接")
    sn = check_adb_device(adb)
    if not sn:
        fail("adb 未检测到设备")
        print("\n  请确认：")
        print("   1. 手机已开机并解锁屏幕")
        print("   2. 设置 → 更多设置 → 开发者选项 → USB 调试 已打开")
        print("   3. USB 连接方式选「传输文件」而不是「仅充电」")
        print("   4. 手机上弹出「允许 USB 调试」时点了允许")
        return 1
    ok(f"设备 {sn} 已连接")

    title("发送 EDL 指令")
    info("执行 adb shell reboot edl")
    info("（注意：不能直接用 `adb reboot edl`，那条会因 root 检查失败）")
    try:
        subprocess.run(
            [adb, "shell", "reboot", "edl"], capture_output=True, timeout=20
        )
    except Exception as e:
        fail(f"指令发送失败: {e}")
        return 1

    title("等待 9008 端口出现（最多 30 秒）")
    deadline = time.time() + 30
    while time.time() < deadline:
        time.sleep(2)
        ports = list_edl_ports()
        if ports:
            for p in ports:
                ok(p)
            print()
            print(_c("  手机已进入 EDL 模式（屏幕全黑、无振动，这是正常的）", "1;32"))
            print()
            print(_c("  ⚠  立刻去 QFIL 点 Download！", "1;33"))
            print("     闲置太久会 Sahara Fail，届时需要重跑本命令")
            print()
            print("  下一步： python flash_helper.py guide --firmware <固件目录>")
            return 0
        print(f"      {(deadline - time.time()):.0f}s ...", end="\r", flush=True)

    print()
    fail("30 秒内未检测到 9008 端口")
    print("\n  可能原因：")
    print("   · 手机没有真正关机或 adb 授权已失效")
    print("   · USB 线只支持充电、没有数据线芯")
    print("   · 建议换机身后置 USB 口后重试")
    return 1


# ----------------------------------------------------------------------------
# 3. 合并分区表
# ----------------------------------------------------------------------------


def _extract_elements(xml_path: Path, tag: str) -> list[ET.Element]:
    """从单个 XML 中提取所有 <tag> 元素。"""
    tree = ET.parse(xml_path)
    return list(tree.getroot().iter(tag))


def merge_manifest(fw: Path, kind: str, out_name: str) -> tuple[int, dict[int, int]]:
    """
    合并 rawprogram0~5.xml 或 patch0~5.xml。

    返回 (合并的元素总数, {LUN: 元素数})
    """
    tag = "program" if kind == "rawprogram" else "patch"
    root_tag = "data" if kind == "rawprogram" else "patches"

    merged: list[ET.Element] = []
    lun_count: dict[int, int] = {}

    for i in range(6):
        src = fw / f"{kind}{i}.xml"
        if not src.exists():
            raise FileNotFoundError(f"缺少 {src.name}")
        elems = _extract_elements(src, tag)
        merged.extend(elems)
        for e in elems:
            lun = int(e.get("physical_partition_number", "0"))
            lun_count[lun] = lun_count.get(lun, 0) + 1

    root = ET.Element(root_tag)
    for e in merged:
        root.append(e)

    out = fw / out_name
    tree = ET.ElementTree(root)
    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass  # Python < 3.9 没有 indent
    tree.write(out, encoding="utf-8", xml_declaration=True)

    return len(merged), lun_count


def cmd_merge(args: argparse.Namespace) -> int:
    print(f"\n{_c('合并分区表', '1')}")
    fw = Path(args.firmware)
    if not fw.is_dir():
        fail(f"固件目录不存在: {fw}")
        return 1

    title("为什么需要合并")
    print("  QFIL 的 Load XML 是「替换」而不是「追加」：")
    print("  加载 rawprogram1.xml 之后，rawprogram0.xml 的配置就丢了。")
    print("  而 PD1610 有 6 个 UFS 逻辑单元，必须合并成一份才能一次刷完。")

    rc = 0
    for kind, out in (("rawprogram", "rawprogram_all.xml"), ("patch", "patch_all.xml")):
        title(f"合并 {kind}")
        try:
            total, dist = merge_manifest(fw, kind, out)
        except Exception as e:
            fail(str(e))
            rc = 1
            continue

        ok(f"已生成 {out}（{total} 条 <{'program' if kind == 'rawprogram' else 'patch'}>）")
        for lun in sorted(dist):
            print(f"         LUN{lun}: {dist[lun]} 条")

        if kind == "rawprogram":
            if dist == EXPECTED_LUN_DISTRIBUTION:
                ok("LUN 分布与 PD1610 实测值一致（16/3/3/6/36/6）")
            else:
                warn("LUN 分布与 PD1610 实测值不同：")
                print(f"         期望 {EXPECTED_LUN_DISTRIBUTION}")
                print(f"         实际 {dist}")
                print("         如果这是别的机型或别版本的固件，属正常；")
                print("         如果是 PD1610 且来源可靠，请先确认固件是否完整。")

    return rc


# ----------------------------------------------------------------------------
# 4. 操作指引
# ----------------------------------------------------------------------------


def cmd_guide(args: argparse.Namespace) -> int:
    fw = Path(args.firmware).resolve() if args.firmware else None
    if not fw or not fw.is_dir():
        fail("请用 --firmware 指定固件目录")
        return 1

    prog = fw / "prog_ufs_firehose_8996_ddr.elf"
    rp = fw / "rawprogram_all.xml"
    pt = fw / "patch_all.xml"

    if not rp.exists() or not pt.exists():
        warn("合并文件尚未生成，请先运行：")
        print(f'     python flash_helper.py merge --firmware "{fw}"')
        print()

    qfil = find_qfil()
    print(f"\n{_c('QFIL 操作指引', '1')}")
    print(_c("-" * 68, "36"))

    print("\n[1] 打开 QFIL" + (f"\n    {qfil}" if qfil else ""))
    print("    （建议以管理员身份运行）")

    print("\n[2] Configuration → FireHose Configuration")
    print("      Download Protocol : 0 - Sahara")
    print("      Device Type       : ufs          ← 选 emmc 会直接 Sahara Fail")
    print("      Reset After Download : 勾选")
    print("      保存后关闭 QFIL 再重新打开")

    print("\n[3] Select Port → 选 Qualcomm HS-USB QDLoader 9008 (COMx)")

    print("\n[4] Select Build Type → Flat Build")

    print("\n[5] Programmer Path → Browse（过滤器要改成 All Files 才看得到 .elf）")
    print(f"      {prog}")

    print("\n[6] Load XML")
    print("      RawProgram : " + str(rp))
    print("      Patch      : " + str(pt))

    print("\n[7] 点 Download")
    print(_c("      ⚠  手机刚进 EDL 就要点，闲置几分钟以上会 Sahara Fail", "33"))

    print("\n[8] 首次开机会卡 logo 十几分钟（跨版本 /data 加密密钥不匹配）")
    print("      随后会提示「加密失败，需重置手机」 → 点重置即可")

    print(_c("-" * 68, "36"))
    return 0


# ----------------------------------------------------------------------------
# 5. 一键流程
# ----------------------------------------------------------------------------


def cmd_all(args: argparse.Namespace) -> int:
    rc = cmd_check(argparse.Namespace(firmware=args.firmware))
    if rc != 0:
        print()
        fail("自检未通过，流程终止")
        return rc

    rc = cmd_merge(argparse.Namespace(firmware=args.firmware))
    if rc != 0:
        return rc

    rc = cmd_edl(argparse.Namespace())
    if rc != 0:
        return rc

    print()
    print(_c("现在去 QFIL，按下面的指引填完并点 Download：", "1;33"))
    return cmd_guide(argparse.Namespace(firmware=args.firmware))


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="flash_helper.py",
        description=f"{DEVICE_NAME} ({MODEL}) 9008 刷机辅助脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例
----
  python flash_helper.py check --firmware "F:\\rom\\PD1610_D_1.18.2_..."
  python flash_helper.py merge --firmware "F:\\rom\\PD1610_D_1.18.2_..."
  python flash_helper.py edl
  python flash_helper.py guide --firmware "F:\\rom\\PD1610_D_1.18.2_..."
  python flash_helper.py all   --firmware "F:\\rom\\PD1610_D_1.18.2_..."

免责声明
--------
刷机会清空全部数据。本脚本仅自动化了刷机前后的辅助步骤，
最终写入由 QFIL 完成。使用风险自负。
""",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("check", help="环境自检（工具 / 驱动 / 固件）")
    sp.add_argument("--firmware", help="固件目录")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("edl", help="让手机进入 9008 (EDL) 模式")
    sp.set_defaults(func=cmd_edl)

    sp = sub.add_parser("merge", help="合并 rawprogram/patch 的 6 个 LUN")
    sp.add_argument("--firmware", required=True, help="固件目录")
    sp.set_defaults(func=cmd_merge)

    sp = sub.add_parser("guide", help="打印 QFIL 操作指引")
    sp.add_argument("--firmware", required=True, help="固件目录")
    sp.set_defaults(func=cmd_guide)

    sp = sub.add_parser("all", help="自检 → 合并 → 进 EDL → 指引")
    sp.add_argument("--firmware", required=True, help="固件目录")
    sp.set_defaults(func=cmd_all)

    return p


def main(argv: Iterable[str] | None = None) -> int:
    if platform.system() == "Windows":
        # 让 Windows 终端的 ANSI 颜色生效
        os.system("")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n已取消")
        return 130


if __name__ == "__main__":
    sys.exit(main())
