# vivo Xplay6 (PD1610) 降级实录：从 Android 8.1 刷回 6.0.1

> 一篇写给后来人的完整记录。包含成功路径，以及那些**看起来可行、实际走不通**的弯路。
> 实测机型：vivo Xplay6 (PD1610)，Snapdragon 820 (MSM8996) + UFS，6 个逻辑单元 (LUN)。
> 起始系统：Android 8.1.0 / Funtouch OS 4.0（8.19.16 内测版）
> 目标系统：Android 6.0.1 / Funtouch OS 3.0（PD1610_D_1.18.2）

---

## 为什么有人要降回 6.0.1

- 8.19.x 是 Funtouch OS 4.0 的**内测线**，卡顿、耗电、发热都明显
- 音质党认为 1.x 系列（尤其 1.15.1 出厂版）耳机口推力与调音更好
- 6.0.1 的 1.18.2 / 1.17.5 在流畅度和续航上明显优于 8.1

---

## 结论先说

需要 **9008 (EDL) 模式 + QFIL**。

- ❌ 卡刷（recovery 装 update-full.zip）在 8.1 上会被版本回滚校验拦下
- ❌ fastboot 刷写被 Bootloader 锁拒绝
- ❌ AFTool（vivo 售后工具）的 15 天联网校验无法绕过
- ✅ 9008 是芯片级模式，绕过以上全部限制

**而 Xplay6 进 9008 不需要拆机短接**，用一条 adb 命令即可。

---

## 配套脚本

仓库里带了一个 `flash_helper.py`，把最容易出错的几个环节自动化了：

```bash
python flash_helper.py check --firmware <固件目录>   # 环境自检
python flash_helper.py merge --firmware <固件目录>   # 合并 6 个 LUN 的分区表
python flash_helper.py edl                          # 一键进入 9008
python flash_helper.py guide --firmware <固件目录>   # 打印 QFIL 操作指引
python flash_helper.py all   --firmware <固件目录>   # 以上全做一遍
```

它解决的问题：

- **环境自检**：adb / QFIL / 9008 驱动 / 固件完整性一次性查清
- **一键进 EDL**：封装 `adb shell reboot edl`，并轮询端口出现
- **自动合并分区表**：`rawprogram0~5.xml` → `rawprogram_all.xml`，并校验 LUN 分布是否为 16/3/3/6/36/6
- **操作指引**：把 QFIL 里每一项该填什么打印出来，避免漏项

末尾的「点 Download」无法自动化——QFIL 不提供命令行接口。

仅依赖 Python 3.8+ 标准库，`pip install` 什么都不用装。

---

## 准备清单

### 软件

| 用途 | 工具 | 备注 |
|---|---|---|
| 进 EDL | platform-tools 新版 adb | 见下方关键说明 |
| 刷写 | QPST 2.7.496 内的 QFIL 2.0.3.5 | 需单独安装 QPST |
| 驱动 | Qualcomm HS-USB QDLoader 9008 | QPST 安装后自带，或手动装 qcser.inf |

### 固件（必须是 9008/EDL 格式）

你需要一份解压后包含以下文件的固件：

```
prog_ufs_firehose_8996_ddr.elf     ← firehose programmer (UFS)
rawprogram0.xml ~ rawprogram5.xml  ← 6 个 LUN 的分区表
patch0.xml ~ patch5.xml            ← 对应的补丁
system*.img / boot.img / userdata*.img / gpt_both*.bin ...
```

判断技巧：**文件名带 `vivo_qcom` 且内含 `rawprogram*.xml` + `prog_*firehose*.elf`，就是 9008 包**。
只有 `fastboot_flash_all.bat` / `fastboot_flash_ufs.bat` 而**没有** rawprogram 的，是 fastboot 包，用不了。

> 固件不提供下载，请自行搜索型号名（如 `PD1610_D_1.18.2_vivo_qcom_LA.HB.1.3.2-09200-8x96.0_msm8996`）。
> 第三方来源存在被改动的风险，下载后务必校对文件完整性。

---

## 核心步骤

### 第 0 步：环境准备

1. 手机开机，进入 `设置 → 更多设置 → 开发者选项`，打开 **USB 调试**
2. 手机连电脑，选择「**传输文件 (MTP)**」——只选「仅充电」时电脑可能枚举不到设备
3. 手机上弹出「允许 USB 调试」→ 勾选「始终允许」并确定
4. 验证：

```powershell
adb devices
# 应输出：xxxxxxxx    device
```

5. 安装 QPST（含 QFIL），安装后确认存在：

```
C:\Program Files (x86)\Qualcomm\QPST\bin\QFIL.exe
```

---

### 第 1 步：进入 9008 (EDL) 模式【关键】

**这是整篇最重要的部分。**

| 尝试过的方法 | 结果 |
|---|---|
| 关机 + 同时按住音量上/下 + 插 USB | ❌ 进的是 **fastboot**，不是 EDL |
| `adb reboot edl` | ❌ 报 `adb root is required` |
| `fastboot oem edl` | ❌ 报 `unknown command or device is lock` |
| `fastboot oem enable-edl` | ⚠️ 返回 OKAY 但设备不进 EDL，无实效 |
| **`adb shell reboot edl`** | ✅ **成功，直接进 9008** |

原因：`adb reboot edl` 是 adb 客户端层面的命令，会先检查 root 权限；而 `adb shell reboot edl` 是把 `reboot edl` 直接丢进手机的 shell 里执行，绕过了这层检查。

```powershell
adb shell reboot edl
```

执行后 3~6 秒，设备管理器会出现：

```
Qualcomm HS-USB QDLoader 9008 (COMx)
```

此时手机**屏幕全黑、无振动**，这是正常状态。

> 若组合键进 fastboot 也无效，说明 8.1 改了按键映射。`adb shell reboot edl` 是目前唯一免拆机的入口。

---

### 第 2 步：QFIL 配置

打开 QFIL（建议以管理员身份运行）。

**① Configuration → FireHose Configuration**

| 项目 | 值 |
|---|---|
| Download Protocol | `0 - Sahara` |
| Device Type | `ufs`（PD1610 是 UFS，选 emmc 会直接 Sahara Fail） |
| Reset After Download | 勾选 |

保存后**关闭 QFIL 重新打开**，配置才生效。

**② 选端口**：顶部 `Select Port` → 选 `Qualcomm HS-USB QDLoader 9008 (COMx)`

**③ Select Build Type** → `Flat Build`

**④ Programmer Path** → Browse → 选 `prog_ufs_firehose_8996_ddr.elf`
> 文件过滤器默认只显示 `.mbn`，要改成 **All Files** 才能看到 `.elf`

---

### 第 3 步：合并分区表【关键】

QFIL 的 **Load XML 是「替换」而不是「追加」**：加载 rawprogram1.xml 后，rawprogram0.xml 的配置就没了。逐个加载 6 组是做不到的。

必须把 6 个 LUN 的分区表合并成一个 XML。

```powershell
$d = "固件目录"

# 合并 rawprogram
$prog = @()
foreach($n in 0..5){
  $c = Get-Content "$d\rawprogram$n.xml" -Raw
  [regex]::Matches($c,'(?m)^\s*(<program\b[^>]*/?>)\s*$') | ForEach-Object { $prog += $_.Groups[1].Value }
}
$out = "<?xml version=`"1.0`" ?>`r`n<data>`r`n" + (($prog | %{ "  $_" }) -join "`r`n") + "`r`n</data>`r`n"
[System.IO.File]::WriteAllText("$d\rawprogram_all.xml", $out, (New-Object System.Text.UTF8Encoding($false)))

# 合并 patch
$pat = @()
foreach($n in 0..5){
  $c = Get-Content "$d\patch$n.xml" -Raw
  [regex]::Matches($c,'(?m)^\s*(<patch\b[^>]*/?>)\s*$') | ForEach-Object { $pat += $_.Groups[1].Value }
}
$out2 = "<?xml version=`"1.0`" ?>`r`n<patches>`r`n" + (($pat | %{ "  $_" }) -join "`r`n") + "`r`n</patches>`r`n"
[System.IO.File]::WriteAllText("$d\patch_all.xml", $out2, (New-Object System.Text.UTF8Encoding($false)))
```

合并后校验 LUN 分布（PD1610 应为 16 / 3 / 3 / 6 / 36 / 6）：

```powershell
[regex]::Matches((Get-Content "$d\rawprogram_all.xml" -Raw),'physical_partition_number="(\d+)"') |
  ForEach-Object { $_.Groups[1].Value } | Group-Object | Sort-Object Name | Select Name,Count
```

**⑤ Load XML** → RawProgram 选 `rawprogram_all.xml` → 弹出的 Patch 选 `patch_all.xml`

> QFIL 2.0.3.5 加载成功后不会打印分区数量，**只看两个输入框是否填上**即可，不用等特定日志。

---

### 第 4 步：点 Download【时序很重要】

**手机刚进 EDL 后要尽快点 Download。**

EDL 的 Sahara 握手窗口有时效性。如果手机在 9008 里闲置过久（本案例中闲置了约 40 分钟），点 Download 必然报：

```
ERROR function:main 320 Uploading Image using Sahara protocol failed
Download Fail: SaharaFail:QSaharaServer Fail: Process fail
```

**解决办法**：让手机退出 EDL（长按电源键 15 秒开机），重新执行 `adb shell reboot edl`，**然后立刻点 Download**。

刷写过程约 3–8 分钟。日志会逐条滚过分区（`system.img is a sparse image` → `{program} FILE="..."`），大分区（system / userdata）会静默几分钟，属正常。最后出现：

```
Download Succeed
Finish Download
{All Finished Successfully}
```

---

### 第 5 步：首次开机

**跨大版本降级后一定会卡 logo。**

原因：`/data` 分区上残留着 8.1 时代的加密密钥（在 `metadata` / `keymaster` 分区），6.0.1 的框架无法解密，vold 会反复重试，表现为卡在 logo 十几分钟。

重试次数耗尽后，系统会弹出「**加密失败，需要重置手机**」——**点重置即可**，它做的就是双清，而且比手工进 recovery 更彻底。

也可以主动处理：

1. 长按电源键 15 秒强制关机
2. 同时按住「音量上 + 电源键」，出 logo 后松电源键、继续按音量上 → 进入 recovery
3. 「清除数据」→「清除所有数据」
4. 重启

重置完成后进入设置向导，即告成功。

---

## 踩坑记录（这些弯路不必再走）

### ❌ AFTool 售后工具：15 天校验绕不过

vivo 官方的 AFTool 会在启动时弹出：

> 工具信息15天未更新，请连接网络再使用，工具将自动关闭

尝试过并**全部失败**的方法：

| 尝试 | 结果 |
|---|---|
| 改系统时间到 2020-07-15 | ❌ 仍弹框 |
| 停用 w32time + 锁定时间 | ❌ 仍弹框 |
| 断网运行 | ❌ 仍弹框 |
| RunAsDate 注入单个进程的伪时间 | ❌ 仍弹框 |
| 删除 / 移走 `_PKG_UNSPT_LIST.BIN` 等校验文件 | ❌ 仍弹框 |
| 批量修改工具目录所有文件时间戳 | ❌ 仍弹框 |
| 用 5.1.28 的启动壳去拉起 4.8.0 主程序 | ❌ 仍弹框 |

**结论：校验既不看本地时间，也不看文件时间，属于联网判定或加密清单校验，没有公开的绕过方法。**

### ❌ AFTool 5.1.28 的双重限制

1. 要求 9008 包目录名以 `_split` 结尾。售后包即使改名，仍报：
   > 构建下载数据包失败,请查看软件包是否选择正确,例如:9008和fastboot-9008升级需要选择split包
2. 明确拒绝 X20 之前的老机型：
   > 请尝试9008模式升级(仅X20及X20后机型使用fastboot,9008升级)

顺带一提：售后包里的 `flash.xml` 写的是 `MPRG8974.mbn`（MSM8974 的 programmer），与 MSM8996 不符。改成正确的 firehose 文件后 AFTool 依然不认——**它根本不读这个文件**。

### ❌ fastboot 刷写：Bootloader 锁死了

```
fastboot getvar all      → (bootloader) unlocked:no  /  secure:yes
fastboot oem device-info → Device unlocked: false  /  critical unlocked: false
fastboot flashing unlock → FAILED (remote: 'unknown command or device is lock')
fastboot oem unlock      → FAILED (remote: 'unknown command or device is lock')
```

固件包里的 `fastboot_flash_ufs.bat` 第一行就是 `fastboot bbk unlock_vivo`——这是 vivo 售后专用解锁指令，需要服务器认证，公开渠道无法执行。

### ⚠️ 若干注意事项

- 路径**不要含中文或空格**，QFIL 和 AFTool 都可能因此读不到文件
- 装 QPST 时 `QPST.2.7.477.exe` 在本机启动即退出（无窗口无报错），换 `QPST.2.7.496.1.exe` 正常
- 用 PowerShell 的 `Start-Process` 启动的 GUI 程序，会随该 PowerShell 进程树被 Job Object 一起清理。若要让程序长期驻留，用 WMI 创建：

```powershell
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
  CommandLine = '"C:\Program Files (x86)\Qualcomm\QPST\bin\QFIL.exe"'
}
```

---

## 后续：刷回 1.15.1（出厂音质版）

降级到 6.0.1 之后，就**不必再走 9008** 了：

同一 Android 大版本内部（6.0.1 → 6.0.1）的升降级，recovery 的卡刷通常会放行。

```
1. 将 PD1610_D_1.15.1-update-full.zip 拷到手机内置存储根目录（不要解压）
2. 关机 → 音量上 + 电源键 → recovery
3. 清除数据 → 清除所有数据
4. 安装升级软件 → 手机存储 → 选择该 zip
5. 等待完成并重启
```

若被「版本校验失败」拦下，可逐级降：`1.18.2 → 1.17.5 → 1.16.14 → 1.15.1`。

> 注意：`PD1610_D_1.25.3-for7.1-wipe-update-full.zip` 是给 7.1 系统用的过渡包，6.0.1 上不需要。

---

## 开源版本谱系

```
1.15.1  ← 出厂版，发烧友称音质最佳
1.16.14
1.17.5  ← 常见的 9008 救砖包版本
1.18.2  ← 本文实测刷入
1.19.2 / 1.21.1 / 1.22.4 / 1.24.3
1.25.3  ← Android 6.0.1 最后一版
7.9.6 / 7.12.x / 7.13.x  ← Android 7.1
8.19.x  ← Android 8.1（Funtouch OS 4.0 内测线）
```

---

## 开机后验收

| 检查项 | 方法 | 说明 |
|---|---|---|
| 版本号 | 设置 → 关于手机 | 应为 PD1610_D_1.18.2 / Android 6.0.1 |
| IMEI | 拨号 `*#06#` | 有号码 = 基带正常 |
| 指纹 | 录入一次 | 验证 persist 分区 |
| 传感器 | 屏幕自动旋转 | 验证 persist 分区 |

若 IMEI 丢失或传感器失效，可用同一套 9008 流程**单独补刷** `modem` / `persist` 分区，不必整包重来。

---

## 风险声明

- **刷机有风险，本文仅为个人实测记录，不构成任何保证。**
- 整个过程会**清空全部数据**，请提前备份。
- 操作前确保电量 50% 以上，使用原装或质量可靠的数据线与机身后置 USB 口。
- 过程中断线或断电可能导致设备无法开机。
- 若设备连 fastboot 与 9008 都无法进入，则需要拆机短接测试点，这已超出本文范围。
- 请仅对自己拥有的设备操作，并遵守当地法律与厂商条款。

---

## 致谢

感谢那些在论坛、贴吧、B 站专栏里留下只言片语的先行者——正是「`adb reboot edl` 需要 root，但 `adb shell reboot edl` 不需要」这一条线索，让整件事从「必须拆机」变成了「三条命令搞定」。

---

*本文基于 2026-10 的一次真实刷机过程整理。不同批次、不同固件版本的表现可能有所差异。*
