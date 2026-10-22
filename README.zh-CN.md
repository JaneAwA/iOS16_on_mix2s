简体中文 | [English](README.md)

# 在小米 Mi Mix 2S（`polaris` / 骁龙 845）上运行 iOS 16

将 **iOS 16（XNU 8796，以 iPhone X 用户态为基线）** 移植到 **小米 Mi Mix 2S（代号 `polaris`，高通骁龙 845 / SDM845）**。

## 简介

整体策略借鉴 Hackintosh 的思路：与其修改 Apple 二进制，不如通过 **Project Mu UEFI 固件（Mu-Silicium）** 把平台以「目标兼容环境」呈现给 XNU，随后由 **自定义 arm64 引导 shim** 拉起 XNU 内核。

引导架构：

```
 device power-on
     │
     ▼
 stock ABL (Xiaomi factory bootloader; retained, rollback-preserving)
     │   fastboot boot  ← no partition modified; reboot returns to Android
     ▼
 [ Mu-Silicium UEFI firmware (polarisPkg, SDM845 platform package) ]   ← optional stage
     │
     ▼
 boot shim  ← shim/           parse FDT / build page tables / relocate XNU payload
     │
     ▼
 XNU kernel  ← xnu/patches/  MACHINE_CONFIG=POLARIS (pure arm64)
     │
     ▼
 AppleDeviceTree ← tools/mkadt.py   generated from the Mix 2S stock DTB
     │
     ▼
 dyld → launchd → userspace (iOS 16.7.16 root image)
```

### Mu-Silicium 的作用

Mu-Silicium 是 **Project Mu**（微软开源 UEFI 实现框架）的一个移植，提供 `polarisPkg` 这个面向 Mi Mix 2S（SDM845）的 UEFI 平台包。在本项目中它的角色是设备的 **UEFI 固件阶段**：负责早期平台初始化（DRAM 配置、通过 RPMh 配置时钟与电源资源、UART 与 GICv3 配置），并暴露标准 UEFI 启动服务，boot shim 由此被拉起。在当前 bring-up 中，使用原厂 ABL 配合 `fastboot boot` 直接加载 shim 镜像，因此 Mu-Silicium UEFI 阶段是一条替代 / 可选的固件路径；采用它会用标准化的 UEFI 环境取代原厂 ABL 的早期初始化职责。构建状态：UEFI 镜像已构建（1.7 MB，UEFI shell 自测通过）；上机验证待进行。

---

## 阅读前必读（三条规则）

1. **本仓库不含任何 Apple 源码。** 没有 iPSW、dyld、SpringBoard、字体或框架——树中也不提供它们的下载。这些是 Apple 的知识产权，请从你自己的设备或官方渠道获取。仓库只发布我们自己的配置、补丁、工具与引导桥接代码。构建出的二进制作为 GitHub Release 资产单独发布（见 §3），绝不提交进树。
2. **状态表中的 ✅ / ❌ 标记，只有在设备 owner `@JaneAwA` 在真机上确认后才改变。** 其余一律为 ⏳（代码已就绪且构建/产物已验证，但尚未上机运行）或 🔧（尚未实现）。没有真机证据的、擅自翻转标记的 PR 会被拒绝。要改动状态，请在 Issue 中附上真机日志或视频。
3. **预构建镜像作为 GitHub Releases 发布——不在源码树中。** `artifacts/` 已被 git 忽略，因此二进制永远不会进入仓库；取而代之的是，构建好的 UEFI 固件（`Mu-polaris.img`）与 iOS 16 根卷（`ios16-root.simg`）会被上传到项目的 GitHub Releases。每个资产都带有 SHA-256 校验和用于完整性验证。如果你不想从源码构建，可以下载一个 Release。

图例：

| 符号 | 含义                       |
| -- | ------------------------ |
| ✅  | 已在真机确认可用（仅限设备 owner）     |
| ❌  | 已在真机确认不可用 / 方案被否决        |
| ⏳  | 已实现；构建与产物验证通过，**等待上机确认** |
| 🔧 | 尚未实现（无对应代码，或代码尚未定稿）      |

---

## 3. 预编译发布

仓库只发布源码、补丁与工具；庞大的二进制产物作为 GitHub Release 资产发布，这样你就不必自己跑完整 CI 流水线。每个资产都带有 SHA-256 校验和用于完整性验证。

| 资产                             | 大小               | 它是什么                                                                                 | 构建自                                                            | 状态           |
| ------------------------------ | ---------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------- | ------------ |
| `Mu-polaris.img`               | ~1.7 MB          | Mu-Silicium UEFI 固件（`polarisPkg`）——执行早期平台初始化并拉起 boot shim 的可选固件阶段                    | `python3 build_uefi.py -d polaris`                             | ⏳ 待进行        |
| `shim-polaris-kernel-boot.img` | ~数十 MB           | 复合 Android boot 镜像：boot shim + XNU 载荷 + ADT + 原厂 DTB（经 `fastboot boot` 加载；不写任何分区）    | `shim/build.sh` + `mkbootimg`                                  | ⏳ 待进行        |
| `ios16-root.simg`              | ~5.8 GB (sparse) | 稀疏 HFS+ 根卷，填充了 iPhone X 20H392 iOS 16.7.16 用户态（OS rootfs + 两个 cryptexes + dyld 共享缓存） | CI `mode=ios`：IPSW → 挂载 3 个 DMG → HFSX 卷 → `tools/img2simg.py` | ⏳ 待进行 (M3.6) |

> `ios16-root.simg` 卷是一个**由 CI 根据你提供的 IPSW 生成的派生产物**；它在你自己的 Apple 许可下打包了 Apple 用户态二进制。源码树本身仍然不含任何 Apple 源码（见规则 1）。刷入命令：`fastboot -S 512M flash userdata ios16-root.simg`，然后 `fastboot boot shim-polaris-kernel-boot.img`。

---

## 1. 当前状态

至此，**从源码到可启动的 `fastboot boot` 镜像的完整流水线已可在单次流程中复现**：

| 里程碑  | 内容                                                         | 状态                         |
| ---- | ---------------------------------------------------------- | -------------------------- |
| M0   | 从小米 Mi Mix 2S 固件中解码真实硬件参数（GIC / UFS / 帧缓冲 / 面板 / 内存）       | ✅                          |
| M1   | XNU 获得 `POLARIS` 机器配置；编译 + 链接干净                            | ✅ 已在设备上确认进入用户态             |
| M2   | shim 适配 Mi Mix 2S 帧缓冲 `0x9d400000` 与面板 1080×2160           | ✅ 屏幕输出已确认                  |
| M3   | ADT 生成 → 载荷打包 → 复合 Android boot 镜像；对全部三个组件做字节级验证           | ✅                          |
| M3.5 | **UFS 根 + HFS+ 卷 → 自定义 init 作为 PID 1 在真机运行**               | ✅ 已于 2026-10-21 确认         |
| M3.6 | 用 iPhone X 20H392 的 Apple 用户态（dyld / launchd）替换卷中的自定义 init | ⏳ 进行中——产物已构建，下载进行中；上机验证待进行 |
| —    | Mu-Silicium `polaris` UEFI 固件已构建（1.7 MB，UEFI shell 自测通过）   | ⏳ 等待上机运行                   |
| M4+  | 显示管线 / 触控 / GPU / WiFi / 音频 …                              | 🔧 未开始                     |

引导链已 bring-up 到用户态；剩余的缺口在用户态的*内容*。当前卷里的 `/sbin/launchd` 是我们编写的一个 16 KB 静态 Mach-O 程序（它唯一的功能是每 5 秒发出一次心跳）；用 Apple 的完整用户态栈替换它就是 M3.6 的目标。

---

## 2. 硬件适配矩阵

> 在功能于你的设备上实际验证之前，状态列不会变动。「验证方式」列描述了会要求你做什么。

### 2.1 引导链

| 特性                                         |  状态 | 实现 / 修复                                                                 | 你如何验证                                                 |
| ------------------------------------------ | :-: | ----------------------------------------------------------------------- | ----------------------------------------------------- |
| Mi Mix 2S UEFI 固件 (Mu-Silicium polarisPkg) |  ⏳  | 直接基于上游 `polarisPkg` 构建，未修改任何上游行；构建命令 `python3 build_uefi.py -d polaris` | `fastboot boot Mu-polaris.img`；串口控制台应输出 UEFI 横幅（见 §6） |
| 不修改原厂 bootloader；可回滚                       |  ⏳  | `fastboot boot` 仅做内存内启动，**不刷写任何分区**                                     | 长按电源键重启后，原厂 Android 系统应正常返回                           |
| shim → XNU 控制权移交                           |  ✅  | `shim/`：解析 DTB，建立 1:1 页表，将载荷重定位到虚拟地址 `0xfffffe0006000000`，然后跳转          | 已确认：内核到达 IOKit 并进入用户态                                 |
| 帧缓冲控制台（屏幕上）                                |  ✅  | shim 控制台直接写入面板帧缓冲，1080×2160，2× 字形缩放                                     | 已确认：从开机起逐行文本；是所有后续工作的实用调试通道                           |
| UART 串口 (115200 8N1)                       |  ⏳  | `shim/console.c` 使用 BLSP UART `qup_uart@0xa84000`（DTB 别名：serial0）       | 设备 owner 目前直接**读手机屏幕**；串口线尚未接上，因此该路径未验证               |

### 2.2 内核与机器描述

| 特性                               |  状态 | 实现 / 修复                                                                                                                                       | 你如何验证                                                                                |
| -------------------------------- | :-: | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| XNU `POLARIS` 机器配置               |  ✅  | `xnu/patches/0099` + `0100`；Mi Mix 2S 与 SWEET 共享「通用 ARM64 + GICv3 双安全态 + 19.2 MHz 定时器 + 无 PAC」，因此 `POLARIS.h` 直接继承 `SWEET.h`，所有差异下放到设备树       | 已确认：内核在设备上到达用户态。`ci/verify_artifacts.py --kernel ...` 报告 cputype 为 `ARM64`（非 ARM64E） |
| PAC 禁用 / 保留 arm64                |  ✅  | 强制 `override ARCH_STRING_FOR_CURRENT_MACHINE_CONFIG := arm64`（见修复记录 #2）。Kryo 385 与 iPhone X 的 A11 都不支持指针认证                                    | 同上；cputype 必须为 ARM64                                                                 |
| AppleDeviceTree 生成（Mi Mix 2S 参数） |  ✅  | `tools/mkadt.py` 添加 `--polaris`（默认）；写入 FB `0x9d400000`、1080×2160、UFS `0x1d84000/0x2500`、DRAM `0xb0000000/0x4d000000`；**SWEET 输出字节不变**（已做回归检查） | 已确认：`IOPlatformExpert.cpp:2319` 处的 panic 已消失。见修复记录 #7（字符串必须 NUL 结尾）                  |
| 设备树打包进镜像                         |  ✅  | Mi Mix 2S 原厂 DTB（491,356 B）追加到 boot.img 尾部；在 shim 启动时解析                                                                                       | `ci/verify_artifacts.py` 报告 DTB 字节一致                                                 |
| 多核（8× Kryo 385）                  |  ⏳  | 复用 SWEET 的平坦 8 核单簇方案（`MAX_CPU_CLUSTERS=1`，ADT 全部 `cluster-id=0`）；**当前启动参数是 `cpus=1`**——先单核，big.LITTLE 后续再做                                    | 去掉 `cpus=1`，观察有多少核被拉起                                                                |
| 定时器 / GICv3 中断                   |  ✅  | 与 SWEET 完全一致，直接继承；虚拟定时器 INTID 19                                                                                                              | 已确认：用户态 init 每 5 秒心跳证明定时器中断在触发                                                       |


### 2.3 存储与用户态

| 特性                          |  状态 | 实现 / 修复                                                                                                                      | 你如何验证                                                                                                     |
| --------------------------- | :-: | ---------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| UFS 主机控制器驱动 (SDM845)        |  ✅  | `0028` 的 `bsd/dev/sweet_ufs.c`；ADT `/sweet-ufs` 寄存器为 `<0x1d84000, 0x2500>`——**真实的 Mi Mix 2S 值**（SWEET 用 `0x3000`）。驱动只读，不触碰数据 | 已确认：屏幕显示 `SWEET UFS: "userdata" on LUN 0` 并继续                                                             |
| 从 UFS 挂载 HFS+ 根             |  ✅  | 卷必须在 macOS 上构建：Linux hfsfuse 只读，fnOS NAS 内核缺少 hfsplus 模块，且 `mkfs.hfsplus` 只产出空卷（见修复记录 #8）                                    | 已确认：屏幕显示 `hfs: mounted SweetRoot on device b(1, 0)`                                                       |
| 来自 **UFS 根** 的 PID 1        |  ✅  | 自定义静态 Mach-O init 置于卷中的 `/sbin/launchd`                                                                                      | **已确认（2026-10-21）**：屏幕 `*** SWEET userspace: init running as PID 1 ***` + 每 5 秒 `SWEET init: still alive` |
| 来自 **内存盘**（`rd=md0`）的 PID 1 |  ✅  | 同一 init 置于内存盘槽位 + mockfs；不刷写任何分区                                                                                             | 已确认：屏幕上相同的两行                                                                                              |
| Apple 真实的 dyld / launchd    |  ⏳  | 卷替换为 iPhone X 20H392 用户态（OS rootfs + 两个 cryptexes）；dyld 共享缓存硬链接到 `/System/Library/Caches/com.apple.dyld`                     | 屏幕应显示 `Darwin Bootstrapper Version 7.0.0`                                                                 |

### 2.4 外设（全部未开始）

| 特性                                 |  状态 | 实现 / 修复（计划，尚未编码）                                                                                       |
| ---------------------------------- | :-: | ------------------------------------------------------------------------------------------------------ |
| 帧缓冲文本控制台                           |  ✅  | shim 控制台写入 `0x9d400000`、1080×2160、2× 字形缩放；已确认为实用调试通道                                                   |
| 显示（IOMobileFramebuffer / UI 渲染）    |  🔧 | 文本已存在；图形/合成器管线尚未接入——需要一个适配层对接 Apple 显示管线，并对齐帧缓冲属性，由内核实际卡住的位置驱动                                         |
| GPU（Adreno 630）                    |  🔧 | 寄存器文档已就位在 mesa `src/freedreno/registers/adreno/a6xx*.xml`；可行路径是 XNU IOGPU/AGX 风格的驱动适配层。**在实证验证之前不下结论** |
| 触控（Synaptics DSX，非 Goodix）         |  🔧 | 需要 XNU I2C/HID 侧适配；DTB 确认 `synaptics,dsx-i2c-force`                                                    |
| WiFi / 蓝牙                          |  🔧 | 需要 SDM845 固件 + XNU 网络栈桥接                                                                               |
| 音频                                 |  🔧 | 需要 QDSP / ADSP 侧接口适配                                                                                   |
| 摄像头                                |  🔧 | 未开始（依赖闭源 ISP）                                                                                          |
| 充电 / 电池（PM8998 + PMI8998 + PM8005） |  🔧 | 未开始。电池管理高风险；先把引导链 bring-up 起来                                                                          |
| 传感器 / 振动 / sensor hub              |  🔧 | 未开始                                                                                                    |
| 基带 / 蜂窝                            |  🔧 | 未开始（modem 分区涉及 IMEI；谨慎处理）                                                                              |

---

## 4. 从零复现

基线来自 [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet)（在骁龙 732G 上运行 XNU 的项目）。**XNU 只能在 macOS 工具链下编译**，因此构建使用 GitHub Actions 的 `macos-14` runner；UEFI 与 shim 在 Linux 上原生编译。

> **想直接用现成镜像？** 从项目的 GitHub Releases（§3）获取 `Mu-polaris.img` 与 `ios16-root.simg`，直接跳到步骤 5b（刷 `userdata`）与步骤 7（`fastboot boot`）。下面的流程仅在你想要从源码重建时才需要。

```bash
# 1) 基线：获取一个 ios-sweet 检出（你的 fork）
git clone https://github.com/<you>/ios-sweet.git

# 2) 一次性应用本仓库的完整改动集（含 dry-run 检查）
./apply_to_upstream.sh /path/to/ios-sweet main

# 3) 内核：在 CI 上构建（约 1 小时，取决于 runner 队列）
export GITHUB_TOKEN=ghp_xxx
./ci/trigger_build.py --repo <you>/ios-sweet --config POLARIS --wait

# 4) 拿到 kernel.development.polaris 后，生成本地 ADT 与载荷
python3 tools/mkadt.py --polaris -o tools/polaris.adt
python3 tools/mkpayload.py --machine polaris -o payload.bin

# 5) shim 与打包
(cd shim && ./build.sh ../payload.bin)
mkbootimg --kernel shim/shim.bin --ramdisk payload.bin \
          --dtb dtb_out/dtb_36.dtb -o shim-polaris-kernel-boot.img

# 5b) 根文件系统卷（仅 UFS 根；任选一层）
     #     最小验证层：仅含一个自定义 /sbin/launchd 的 32 MB 卷
base64 -D < tools/sweet-init.b64 > /tmp/sweet-init
./tools/mkhfsroot.sh root-hfs.raw 32 /tmp/sweet-init
     #     完整 iOS 16 层：三个 APFS 镜像来自你自己的 IPSW；不提供
./tools/mkiosroot-macos.sh ios16-root.raw OS.dmg SYSTEMOS.dmg APPOS.dmg
python3 tools/img2simg.py ios16-root.raw ios16-root.simg
     #     10 GB 级镜像只能以 sparse 方式刷入（见 #8，max-download-size）
fastboot -S 512M flash userdata ios16-root.simg

# 6) 飞行前自检（必须报告 ALL CHECKS PASSED）
python3 ci/verify_artifacts.py \
    --image   shim-polaris-kernel-boot.img \
    --payload payload.bin \
    --dtb     dtb_out/dtb_36.dtb \
    --kernel  kernel.development.polaris

# 7) 上机（不写任何分区；随时可回滚）
adb reboot bootloader && fastboot boot shim-polaris-kernel-boot.img
```

UEFI 固件（可选；一个独立于上游 Mu-Silicium 跟踪的工作流）：

```bash
python3 Platforms/Xiaomi/polarisPkg/DeviceBuild.py --update -t RELEASE
python3 build_uefi.py -d polaris
```

---

## 5. 修复记录

本节是 *问题 → 根因 → 修复* 的完整日志，便于按序理解代码当前的形态。让内核干净编译花了五轮 CI——**每一次失败都从失败运行的日志中挖出，而非猜测。**

### #1 `Unsupported CURRENT_MACHINE_CONFIG POLARIS`

- 症状：第一轮 CI 立即失败，报 `MakeInc.kernel:22: *** Unsupported CURRENT_MACHINE_CONFIG POLARIS`。
- 根因：手写的 `0004b` 补丁 hunk 计数错误（`@@ -9,7` 实际应为 6 行）；`git apply` 判定其损坏并**跳过**，于是 POLARIS 从未进入 `SUPPORTED_ARM64_MACHINE_CONFIGS` 白名单；该补丁的插入点还被后续 13 个补丁反复挪动。
- 修复：下载失败运行的 `xnu-buildtree` 产物（即所有补丁**应用后**的 xnu）→ 在 git 中建立基线 → 直接编辑真实文件 → 用 `git diff` 生成 `0099`（hunk 计数由 git 计算，不可能错），并统一换行符。删除 `0004b`。

### #2 `-arch arm64e` → 未定义的 ptrauth 符号

- 症状：以 `-arch arm64e` 编译；`__has_feature(ptrauth_calls)` 开启但 `HAS_APPLE_PAC` 缺失，于是 `pmap_sign_user_ptr` / `jop_pid` 未声明；同时 `sweet_vtimer_intid` 在 `sleh.c` 中于 `#if defined(SWEET)` 下使用，却在 `protos.h` 中于 `#if defined(ARM64_BOARD_CONFIG_SWEET)` 下声明——两侧不一致。
- 根因：Kryo 385 与 SWEET 的 Cortex-A76/A55 都不支持指针认证，因此两者都必须是纯 arm64；`ARCH_STRING` 用了 `?=`，于是环境中的任何值都会静默跳过覆盖，使目标停留在 arm64e。
- 修复：在 `MakeInc.def` 中，用 `ifneq ($(filter SWEET POLARIS,$(CURRENT_MACHINE_CONFIG)),)` 来**强制**纯 arm64；在 `POLARIS.h` 中 `#include <pexpert/arm64/SWEET.h>`，使 `ARM64_BOARD_CONFIG_SWEET` 与 `POLARIS` 都被定义，从而声明与使用一致（不再重复 include `board_config.h`，那会重复定义）。

### #3 缺失 `sweet_bearssl/` 与 `sweet_libpthread/`

- 症状：`'sweet_bearssl/inc/bearssl_hash.h' file not found`、`'sweet_libpthread/kern/kern_init.c' file not found`。
- 根因：3 个 stage 脚本 + 2 个 Makefile 补丁用字面量 `== SWEET` 来给这些 info/utils 加门控；但 BearSSL（软件 AES/MD5/SHA）、libpthread（XNU 自带）与 HFS（根文件系统）是与板无关的。
- 修复（5 处）：
  - `0019-stage-libpthread.sh`、`0020-stage-bearssl.sh`、`0026-stage-hfs.sh`：门控改为 `case ... in SWEET|POLARIS)`。
  - `0019-sweet-builtin-pthread.patch`、`0020-sweet-portable-aes-cbc.patch`：`ifeq ($(CURRENT_MACHINE_CONFIG),SWEET)` → `ifneq ($(filter SWEET POLARIS,$(CURRENT_MACHINE_CONFIG)),)`（因为 bsd/conf 的 `-I` 路径必须也对 POLARIS 生效）。
  - 注意：这些都是**严格的 1:1 行替换**；统一 diff 的 hunk 行计数不变，避免再次落入 #1 的陷阱。

### #4 链接时有 264 个未定义符号

- 症状：`CleanPoC_Dcache`、`Idle_context`、`__start`、`__bcopyin` …… 264 个未定义。
- 根因：`config/Makefile` 通过 `wildcard` 定位 `MASTER.arm64.<machine>`；POLARIS 没有这样的文件，于是**静默回退到 Apple 原始配置**，后者期望来自闭源 KDK 的 `lib<SOC>.os.<CONFIG>.a`（仅 arm64e + Apple Silicon）中的底层符号——结果 `osfmk/arm64/*.s` 一个都没被编译。  
  `nos_arm_asm` 是一个**必须开启**的选项，而非「禁用汇编」。
- 修复：添加 `config/MASTER.arm64.polaris`（`0100`）——与最终的 `MASTER.arm64.sweet` 字节一致，不含任何板相关的内容；最后生成，因此已自带后续的补充（mockfs 内存盘根、sweet_hfs、bindfs、桩化的 ext 解析器）。

### #5 控制用例：SWEET 同样失败

- 故意派发了一个 `MACHINE_CONFIG=SWEET` 的运行（run 39468989984），它**以完全相同的方式失败，且同样落在 arm64e**。这证明该缺陷是环境中预先存在的，并非 POLARIS 引入；反过来说，这也佐证 #4 是 POLARIS 特有的（SWEET 死在编译，POLARIS 到达链接）。

### #6 环境与工具链陷阱（重新尝试前必读）

| 陷阱                               | 症状                            | 解决                                                              |
| -------------------------------- | ----------------------------- | --------------------------------------------------------------- |
| Windows git autocrlf             | 远端 bash 报 `set -o pipefail\r` | 所有源文件用 LF（见 `.gitattributes`）；运行脚本前确认无 `\r`                     |
| Debian awk 是 mawk                | `gawk: strtonum` not found    | `shim/build.sh` 改用 bash 原生十六进制运算                                |
| `git push` 被沙箱代理阻断 (CONNECT 502) | push rc=128                   | 用 GitHub Contents API 提交，或通过可达的代理 `git push`                    |
| Contents API 提交**不会触发** Actions  | push 后无运行                     | 始终显式 dispatch（`ci/trigger_build.py`）                            |
| `if cmd \| tail; then`           | 退出码取自 `tail`，永远为真 → 假成功       | 用真实的 `$?` / `${PIPESTATUS[0]}`                                  |
| 只读 CI 网页错误摘要                     | 无法定位第一轮错误                     | 拉取 `{run}/logs` 归档，直接 grep `*_Build.txt`（`ci/watch_run.py` 做这个） |
| 推送前未提交本地改动                       | 推送的树**把远端回滚**（见 #9）           | 触发构建前运行 `check_remote_sync.py`                                  |


### #7 2319 panic 的真正根因：ADT 字符串未 NUL 结尾

- 症状：`unable to find driver for this platform:"D22APiPhone10,3xiaomi,polarisqcom,sdm845AppleARMmodel"` @`IOPlatformExpert.cpp:2319`。
- **首次诊断是错误的**：假设内核 personality 表缺少 polaris 条目（其 `IONameMatch` 硬编码为 `xiaomi,sweet`），于是添加了补丁 `xnu/patches/0101`——上机 panic **没有变化**。
- 真正根因在 `tools/mkadt.py`：`compatible` 被**裸拼**为 `b'D22AP' + b'iPhone10,3' + b'xiaomi,polaris' + ...`，形成一条 44 字节的字符串。设备树的 `compatible` 是一个**以 NUL 分隔的字符串列表**；`IODTCompareNubName` 把它与 `IONameMatch` 逐条比较——拼成一条字符串后它什么也匹配不上，于是落入 `IOPanicPlatform`（它存在的全部理由就是 panic）。
- 这也解释了 panic 尾部突兀的 `model`：没有结尾 NUL，内核会越过 C 字符串边界读入下一个属性的名字。**字符串一直都在回答问题；第一次阅读漏掉了它。**
- 修复：`strlist()` / `cstr()`（`cstr` 必须同时接受 `str` 与 `bytes`——`bytes` 没有 `.encode()`，第一版直接崩）；添加 `tools/check_adt.py` 遍历整棵树并报告每个未 NUL 结尾的字符串属性——修复前 12 处，修复后 0 处；ADT 大小 9912 → 9920，正好是补上的 NUL 数。
- 代价：两个 `0101` 条目（CPU `qcom,kryo385` 与显示 `polaris,display`）都是必要的；那个 platform-expert 条目是为一个并不存在的幻影添加的。

### #8 填充 HFS+ 卷：Linux 完全受阻；转向 macOS

- 需求：卷必须能容纳文件——先是一个 16 KB 的 init，后来是一个 10 GB 的 iOS 用户态。
- 三条路全部受阻：

| 方法                               | 结果                                                    |
| -------------------------------- | ----------------------------------------------------- |
| NAS 上 `mount -t hfsplus -o loop` | ❌ fnOS 内核 6.18.18-trim 无 hfsplus 模块；只有内核头文件，无源码树，无法编译 |
| hfsfuse（本地编译）                    | ❌ **设计上只读**；README 写明「只读，无法写入或修改目标文件系统」               |
| 本地 WSL                           | ❌ 未安装                                                 |

- 修复：在 macOS runner 上用 Apple 自家的 `newfs_hfs` 构建卷——与 XNU 的 hfs kext 同源。输出是**偏移 0 处为 HFS+ 的原始磁盘**（无 UDIF 尾部、无分区表），fastboot 可直接写入。
- 两个 macOS 陷阱：BSD `base64` 没有 `--decode`（只接受 `-D`；约 4 秒后失败一次）；未分区的镜像有时会被 macOS 合成为一个 slice，因此挂载必须同时尝试 `$dev` 与 `${dev}s1`。

### #9 仅工作树的改动被同步脚本推走

- 症状：新一轮 CI 报出与最开始完全相同的错误（`pmap_sign_user_ptr` / `jop_pid` 未声明），看起来像构建环境问题。
- 根因：上一轮的关键修复只存在于**本地工作树**，从未提交；推送脚本从本地 `HEAD` 构建整个树，于是把远端**回滚**到了旧版本（远端 `0099` 只有 4153 字节；好版本是 6410 字节；`MASTER.arm64.polaris` 整个丢失）。
- 修复：重新提交并推送回去；添加 `check_remote_sync.py`，它逐 blob 比较远端树与本地 `HEAD`，标记出未提交的工作树改动。**每次触发构建前运行。**

---

## 6. 上机记录与待验证

### 6.1 2026-10-21：引导链 bring-up 到用户态（M3.5）

设备 `faa72261`，`fastboot boot`（内存内启动，不写分区）。设备 owner 目前直接**读手机屏幕**。

首次上机运行，内核进入 IOKit 后仅卡住：

```
unable to find driver for this platform:"D22APiPhone10,3xiaomi,polarisqcom,sdm845AppleARMmodel"
@IOPlatformExpert.cpp:2319
debug_log_init: Error!! gPanicBase is still not initialized
"name" not a kext
"AAPL,phandle" not a kext
SWEET: trust cache unavailable (Image4/AMFI not installed)
handshake structure not initialized
```

修复设备树（#7）后，到达无根设备：

```
Waiting on IOMedia/Apple_HFS
Failed to write boot-picker-bringup-reason to NVRAM.
```

用 `rd=ufsroot0` 把 HFS+ 卷刷入 `userdata` 后，卷仍是空的：

```
SWEET: root volume is not authenticated (error 25): continuing unsealed
devfs_kernel_mount: kernel_mount failed: 2
panic: Process 1 exec of /sbin/launchd failed, error 2 @kern_exec.c:6929
```

`error 2` = ENOENT；三处都指向同一事实：**卷是空的**。换成含 `/sbin/launchd` 的卷后：

```
*** SWEET userspace: init running as PID 1 ***
SWEET init: still alive
SWEET init: still alive
```

同一 init 在内存盘根（`rd=md0`，不刷分区）上也产生相同的两行。至此 M3.5 确认。

### 6.2 待验证

> 自上而下，一次一项；确认后才翻转状态。**别忘了串口线。**

- [ ] **串口**：将 Mi Mix 2S 的 UART（`qup_uart@0xa84000`）接到 FTDI 适配器，115200 8N1。目前只能读屏幕；滚过屏幕的行不可见。
- [ ] **UEFI 固件独立运行**：`fastboot boot Mu-polaris.img` → 应显示 Project Mu 输出 / 进入 UEFI shell。**这不写任何分区；长按电源键重启回到 Android。**
- [ ] **完整镜像**：`fastboot boot shim-polaris-kernel-boot.img` → shim 横幅 → XNU 启动日志 →（预期）卡在「no root device」。这个 panic 是**预期**的，证明引导链活着。
- [ ] **回滚确认**：重启后 Android 正常，串口/IMEI 不变。
- [ ] **内核架构**：若启动失败，先运行 `ci/verify_artifacts.py --kernel ...` 确认 cputype 是 ARM64，而非 ARM64E。
- [ ] **多核**：在日志中确认有多少核被唤醒；等 adb/lockdownd 类服务能启动后再回头看。

失败时，把**完整串口日志**附到 Issue，而不是一句光秃秃的「黑屏」报告——黑屏可能意味着 shim、XNU head 或错误的帧缓冲地址处卡住，三条路径完全不同。

---

## 7. 路线图

| 顺序  | 目标                                                                                            | 备注                                                                                                                                                                                       |
| --- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 进行中 | **M3.6**：把 iPhone X 20H392 用户态放进卷中（OS rootfs + 两个 cryptexes + dyld 共享缓存），让 Apple 的 launchd 启动 | 三个已知障碍：内核以 macOS 配置构建，会把 iOS 平台二进制判为 alien（`unentitled_ios_sim_launch=1` 绕过此点）；没有 AMFI，于是 `launchd_cache_loader` 中止；在 ignition level 1 下 dyld 只查 `/System/Library/Caches/com.apple.dyld` |
| 下一步 | M4：显示管线（IOMobileFramebuffer）                                                                  | 文本控制台已存在；下一步是 UI 显示管线                                                                                                                                                                    |
| 下一步 | M5：触控、充电、WiFi 及其他基础外设                                                                         |                                                                                                                                                                                          |
| 延伸  | **M6：GPU（Adreno 630）**                                                                        | mesa a6xx 寄存器文档已就位。**仅在实证验证之后下结论**；本仓库不会预先判定其不可行                                                                                                                                         |

---

## 8. 许可与致谢

- 本仓库中创作的部分（补丁、工具、shim 改动、CI 脚本）以 **MIT** 发布；见 `LICENSE`。
- XNU 本身受 **Apple Public Source License (APSL)** 管辖，版权归 Apple Inc. 与 Carnegie Mellon University；本仓库只发布针对该源码的**补丁**，从不发布源码本身。
- Mu-Silicium / Project Mu 受其各自的 BSD 家族许可与上游仓库条款管辖。
- 致谢：[dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet)（XNU-on-Snapdragon 的先前工作）、[Mu-Silicium](https://github.com/mu-silicium)（`polarisPkg` UEFI 平台包）、mesa/freedreno（Adreno 630 寄存器文档）。

> 本项目为**个人学习与私有设备移植研究**。源码树只发布我们自己的代码、补丁与工具——不含任何 Apple 源码（见规则 1）。构建好的固件（`Mu-polaris.img`）与派生的 iOS 16 根卷（`ios16-root.simg`）作为 GitHub Release 资产发布以图方便；后者在你自己的 Apple 许可下打包了由 CI 根据你提供的 IPSW 生成的 Apple 用户态。刷机有风险；任何操作前请备份串号分区（`persist` / `modemst` / `fsg`）。
