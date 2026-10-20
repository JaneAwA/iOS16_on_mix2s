# iOS16_on_mix2s

在**小米 Mix 2S（polaris / Snapdragon 845）**上把 **iOS 16（XNU 8796，iPhone X 的用户态基线）**跑起来。

技术路线与黑苹果同理：不改写 Apple 二进制，而是用 **Project Mu UEFI（Mu-Silicium）** 把机器伪装成苹果能接受的环境，再用一个自研的 **arm64 boot shim** 把 XNU 内核托起来。

```
   手机开机
     │
     ▼
  stock ABL (小米原厂 bootloader，未替换，保持可回滚)
     │   fastboot boot  ← 不改分区，重启就回到安卓
     ▼
  Mu-Silicium UEFI firmware (polarisPkg, SDM845 平台包)
     │
     ▼
  boot shim  ← shim/          读 FDT / 建页表 / 搬运 XNU payload
     │
     ▼
  XNU kernel  ← xnu/patches/  MACHINE_CONFIG=POLARIS（纯 arm64）
     │
     ▼
  AppleDeviceTree ← tools/mkadt.py   由 Mix 2S 真实 DTB 生成
     │
     ▼
  dyld → launchd → 用户态（iOS 16.7.16 root 体制）
```

---

## 先读这里（三条规矩）

1. **本仓库不含任何 Apple 固件。** iPSW、dyld、SpringBoard、字体、框架这些二进制一处都没有，也不提供下载。它们属于 Apple，请自己从你自己的设备/官方渠道取得。仓库里只有我们自己写的配置、补丁、工具和引导桥接代码。
2. **状态表里的 ✅ / ❌ 只有设备主 @JaneAwA 在真机上确认过才会改。** 其余一律是 ⏳（代码已就位、构建已通过，但没上过真机）或 🔧（尚未实现）。在 PR 里擅自打勾会被打回。想改状态，请在 Issue 里贴真机日志/视频。
3. **不分发成品镜像。** 仓库的 `artifacts/` 是 gitignore 的，每个人都要自己从源码构建。

图例：

| 符号 | 含义 |
|---|---|
| ✅ | 已在真机上确认可用（只有设备主能给） |
| ❌ | 真机确认不可用 / 该方案已否决 |
| ⏳ | 代码已实现、构建与产物校验已通过，**等真机确认** |
| 🔧 | 尚未实现（无对应代码或代码未成型） |

---

## 1. 当前进展

到这一步为止，**从源码到可 `fastboot boot` 的完整镜像已经能一次性产出了**：

| 阶段 | 内容 | 状态 |
|---|---|---|
| M0 | 从 Mix 2S 固件解码出真实硬件参数（GIC / UFS / 帧缓冲 / 面板 / 内存） | 已完成（工具+交叉核对） |
| M1 | XNU 新增 `POLARIS` 机器配置，**编译+链接全绿**（CI run 39470309899） | ⏳ 待真机 |
| M2 | shim 适配 Mix 2S 帧缓冲与面板尺寸 | ⏳ 待真机 |
| M3 | ADT 生成 → payload 打包 → 合成 Android boot 镜像，三部件字节级校验通过 | ⏳ 待真机 |
| — | Mu-Silicium `polaris` UEFI 固件编译成功（1.7 MB，UEFI shell 自检通过） | ⏳ 待真机 |
| M3.5 | 解 OS DMG 做 HFS+ root 并接上 UFS 分区（**这是进入用户态的下一个卡点**） | 🔧 未开始 |
| M4+ | 显示 / 触控 / GPU / WiFi / 音频 … | 🔧 未开始 |

**内核侧没有 root 设备，所以现在镜像只能跑到「内核起来、没有文件系统」为止**——这也是 M3.5 的意义。

---

## 2. 功能适配矩阵

> 状态列在你的机器上跑过之前不会动。「验证方法」一列就是到时候请你做的事。

### 2.1 引导链

| 功能 | 状态 | 实现 / 修复方案 | 你需要这样验证 |
|---|:--:|---|---|
| Mi Mix 2S 的 UEFI 固件（Mu-Silicium polarisPkg） | ⏳ | 直接编译上游 `polarisPkg`，未改一行上游代码；构建命令 `python3 build_uefi.py -d polaris` | `fastboot boot Mu-polaris.img`，串口应出 UEFI banner（详见第 6 节） |
| 不动原 bootloader、可回滚 | ⏳ | 只用 `fastboot boot` 内存引导，**不 flash 任何分区** | 长按电源重启后应正常回到原来的安卓系统 |
| shim → XNU 控制权交接 | ⏳ | `shim/`：读 DTB、建 1:1 页表、把 payload 搬到虚拟地址 `0xfffffe0006000000` 后跳转 | 串口出现 XNU 的启动 banner 即成功 |
| 串口 / 控制台输出 | ⏳ | `shim/console.c` 走 BLSP UART `qup_uart@0xa84000`（DTB aliases: serial0），115200 8N1 | 开机就有日志，是所有后续调试的前提 |

### 2.2 内核与机器描述

| 功能 | 状态 | 实现 / 修复方案 | 你需要这样验证 |
|---|:--:|---|---|
| XNU `POLARIS` 机器配置（编译链接通过） | ⏳ | `xnu/patches/0099` + `0100`；Mix 2S 与 SWEET 同为 "generic ARM64 + GICv3 双安全态 + 19.2 MHz timer + 无 PAC"，故 POLARIS.h 直接继承 SWEET.h，差异全部下放到设备树 | `ci/verify_artifacts.py --kernel ...` 应报 `ARM64`（而非 ARM64E）；真机上以是否 panic 为准 |
| 不开 PAC / 保持 arm64 | ⏳ | 强制 `ARCH_FLAGS_ARM64 = -arch arm64`（见修复记录 #2）。Kryo 385 没有指针认证，编成 arm64e 必挂 | 同上，cputype 必须是 ARM64 |
| AppleDeviceTree 生成（Mix 2S 参数） | ⏳ | `tools/mkadt.py` 新增 `--polaris`（默认），写入 FB `0x9d400000`、1080×2160、UFS `0x1d84000/0x2500`、DRAM `0xb0000000/0x4d000000`；**SWEET 输出字节不变**（已回归核对） | `python3 tools/mkadt.py --polaris` 后对比分辨率/地址是否符合硬件表 |
| 设备树打包进镜像 | ⏳ | boot.img 尾部附 Mix 2S 原始 DTB（491,356 B），shim 启动时解析 | `ci/verify_artifacts.py` 报 dtb byte-identical |
| 多核（8 核 Kryo 385） | ⏳ | 沿用 SWEET 的扁平 8 核单簇方案（`MAX_CPU_CLUSTERS=1`，ADT 全 `cluster-id=0`），先跑起来再谈 big.LITTLE | 串口看几颗核起来；跑 `sysctl hw` 类信息 |
| 定时器 / GICv3 中断 | ⏳ | 与 SWEET 完全相同，直接继承；虚拟定时器 INTID 19 | 内核不卡在 `clock`/`interrupt` 上即正常 |

### 2.3 存储与用户态

| 功能 | 状态 | 实现 / 修复方案 | 你需要这样验证 |
|---|:--:|---|---|
| UFS 主机控制器驱动 | 🔧 | shim 里已有 `ufs.c` 基础访问；XNU 侧尚未接可靠块设备 | 待 M3.5 |
| HFS+ root 文件系统 | 🔧 | 方案：解开 OS DMG 做 HFS+ 卷，接 UFS 分区；或先用 ramdisk mockfs 顶住跑通后再换真根 | 待 M3.5 |
| dyld / launchd 起来 | 🔧 | 依赖上两项 | 待 M3.5 之后 |

### 2.4 外设（全部未开始）

| 功能 | 状态 | 实现 / 修复方案（方案，尚未写代码） |
|---|:--:|---|
| 显示（IOMobileFramebuffer / 面板） | 🔧 | 帧缓冲已对齐 `0x9d400000`、1080×2160（shim 阶段出图够用）；真正交给 Apple 显示管线还需按内核实际停的位置补一层 veneer / FB 属性贴合 |
| GPU（Adreno 630） | 🔧 | 底稿已在 mesa `src/freedreno/registers/adreno/a6xx*.xml`；可行路径是写 XNU 的 IOGPU/AGX 风格驱动适配层。**未经实证前不预判不可行** |
| 触控（Synaptics DSX，非 Goodix） | 🔧 | 需 XNU 的 I2C/HID 侧适配，DTB 已确认 `synaptics,dsx-i2c-force` |
| WiFi / 蓝牙 | 🔧 | 需 SDM845 侧固件与 XNU 网络栈桥接 |
| 音频 | 🔧 | 需适配 QDSP / ADSP 侧接口 |
| 相机 | 🔧 | 未开始（依赖 ISP 侧闭源） |
| 充电 / 电量（PM8998+PMI8998+PM8005） | 🔧 | 未开始。涉及电池管理，风险较高，先把引导跑通再说 |
| 传感器 / 振动 / 传感器hub | 🔧 | 未开始 |
| 基带 / 蜂窝网络 | 🔧 | 未开始（modem 分区涉及 IMEI，谨慎） |

---

## 3. 仓库地图

```
tools/
  mkadt.py       生成 AppleDeviceTree；--polaris(默认) / --sweet；两机型输出互不干扰
  mkpayload.py   把内核 + ADT + ramdisk 打包成 shim 认得的 payload；--machine 自动选 ADT
shim/
  console.h mmu.h   Mix 2S 帧缓冲常量（FB_BASE/FB_PHYS 0x9d400000，高 2160）
  build.sh          交叉编译 shim（纯 bash 算偏移，不依赖 gawk strtonum）
xnu/patches/
  0099-polaris-machine-config.patch   POLARIS 机器配置、编译 flags、pexpert 头
  0100-polaris-master-config.patch    config/MASTER.arm64.polaris（缺它链接会挂）
  0019-* 0020-* 0026-*                把原本只认 SWEET 的门控放宽到也认 POLARIS
ci/
  xnu-polaris.yml         CI 工作流（machine_config 默认 POLARIS）
  trigger_build.py        触发一次远程 XNU 构建
  watch_run.py            轮询运行状态并抽取真正到达 clang 的编译参数与错误
  verify_artifacts.py     上线前自检：boot.img 布局、payload/dtb 字节一致、内核非 arm64e
  decode_dtb.py           从 boot.img 抽出扁平设备树并挑出行本品那一份
hardware/polaris.txt      解码出的 Mix 2S 硬件参数表（含 DTB 证据）
patches/upstream-polaris.diff   相对上游 ios-sweet 的完整差异，一个文件复刻全部改动
apply_to_upstream.sh       把上面的差异应用到一份 ios-sweet checkout
```

---

## 4. 从零复现

依赖 baseline 是 [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet)（把 XNU 跑到 Snapdragon 732G 的项目）。XNU **只能在 macOS toolchain 下编译**，所以用 GitHub Actions 的 `macos-14` runner；UEFI 和 shim 在 Linux 上原生编。

```bash
# 1) 基线：拿上游 ios-sweet checkout（这里是你的 fork）
git clone https://github.com/<you>/ios-sweet.git

# 2) 把本仓库的全部改动一次性打上去（带 dry-run 检查）
./apply_to_upstream.sh /path/to/ios-sweet main

# 3) 内核：CI 编（约 1 小时，取决于 runner 排队）
export GITHUB_TOKEN=ghp_xxx
./ci/trigger_build.py --repo <you>/ios-sweet --config POLARIS --wait

# 4) 拿到 kernel.development.polaris 后，生成本地 ADT 与 payload
python3 tools/mkadt.py --polaris -o tools/polaris.adt
python3 tools/mkpayload.py --machine polaris -o payload.bin

# 5) shim 与打包
(cd shim && ./build.sh ../payload.bin)
mkbootimg --kernel shim/shim.bin --ramdisk payload.bin \
          --dtb dtb_out/dtb_36.dtb -o shim-polaris-kernel-boot.img

# 6) 上线前自检（必须全部 ALL CHECKS PASSED）
python3 ci/verify_artifacts.py \
    --image   shim-polaris-kernel-boot.img \
    --payload payload.bin \
    --dtb     dtb_out/dtb_36.dtb \
    --kernel  kernel.development.polaris

# 7) 真机（不写分区，随时可回滚）
adb reboot bootloader && fastboot boot shim-polaris-kernel-boot.img
```

UEFI 固件（可选，独立的一条线，走上游 Mu-Silicium）：

```bash
python3 Platforms/Xiaomi/polarisPkg/DeviceBuild.py --update -t RELEASE
python3 build_uefi.py -d polaris
```

---

## 5. 修复方案记录

这一节是"每个问题 → 根因 → 怎么修"的完整留档，方便按顺序理解代码为什么长这样。
五轮 CI 才把内核编绿，**每一个失败都不是猜出来的，是从失败 run 的日志里挖出来的**。

### #1 `Unsupported CURRENT_MACHINE_CONFIG POLARIS`

- 现象：首轮 CI 直接 `MakeInc.kernel:22: *** Unsupported CURRENT_MACHINE_CONFIG POLARIS`。
- 根因：手写的 `0004b` 补丁 hunk 计数写错（`@@ -9,7` 实际 6 行），`git apply` 判为 corrupt 并**跳过**，于是 POLARIS 从未进入 `SUPPORTED_ARM64_MACHINE_CONFIGS` 白名单；而且补丁插的位置也被后面 13 个补丁反复改动。
- 修复：下载失败 run 的 `xnu-buildtree` 产物（即**打完全部补丁之后**的 xnu 源码）→ 在 git 里建基线、直接改真文件 → 用 `git diff` 生成 `0099`（hunk 由 git 自己算，不可能错），并统一换行。删掉 `0004b`。

### #2 `-arch arm64e` → ptrauth 符号未定义

- 现象：编译 `-arch arm64e`，`__has_feature(ptrauth_calls)` 打开但 `HAS_APPLE_PAC` 没有，`pmap_sign_user_ptr` / `jop_pid` 未声明；同时 `sweet_vtimer_intid` 在 `sleh.c` 里按 `#if defined(SWEET)` 使用、在 `protos.h` 里按 `#if defined(ARM64_BOARD_CONFIG_SWEET)` 声明，两边对不上。
- 根因：Kryo 385 和 SWEET 的 Cortex-A76/A55 都没有指针认证，两者都必须是纯 arm64；ARCH_STRING 走的是 `?=`，环境里一旦有值就会静默跳过覆盖，目标仍是 arm64e。
- 修复：`MakeInc.def` 里用 `ifneq ($(filter SWEET POLARIS,$(CURRENT_MACHINE_CONFIG)),)` **强制** 纯 arm64；`POLARIS.h` 里 `#include <pexpert/arm64/SWEET.h>`，让 `ARM64_BOARD_CONFIG_SWEET` 与 `POLARIS` 同时有定义，声明与使用两端就一致了（不再重复 include `board_config.h`，避免重复定义）。

### #3 缺 `sweet_bearssl/` 与 `sweet_libpthread/`

- 现象：`'sweet_bearssl/inc/bearssl_hash.h' file not found`、`'sweet_libpthread/kern/kern_init.c' file not found`。
- 根因：3 个 stage 脚本 + 2 个 Makefile 补丁把这些信息/utils 用**字面 `== SWEET`** 卡住；而 BearSSL（软件 AES/MD5/SHA）、libpthread（XNU 自带的）、HFS（根文件系统）跟板子没有关系。
- 修复（5 处）：
  - `0019-stage-libpthread.sh`、`0020-stage-bearssl.sh`、`0026-stage-hfs.sh`：门控改为 `case ... in SWEET|POLARIS)`；
  - `0019-sweet-builtin-pthread.patch`、`0020-sweet-portable-aes-cbc.patch`：`ifeq ($(CURRENT_MACHINE_CONFIG),SWEET)` → `ifneq ($(filter SWEET POLARIS,$(CURRENT_MACHINE_CONFIG)),)`（因为 bsd/conf 的 `-I` 路径必须对 POLARIS 也生效）。
  - 注意这里是**严格 1:1 行替换**，unified diff 的 hunk 行数不变，避免再踩 #1 的坑。

### #4 链接期 264 个未定义符号

- 现象：`CleanPoC_Dcache`、`Idle_context`、`__start`、`__bcopyin` … 264 个 undefined。
- 根因：`config/Makefile` 用 `wildcard` 找 `MASTER.arm64.<machine>`；POLARIS 没有对应文件，**静默回退到 Apple 原版 config**，那份配置期望低层符号来自闭源 KDK 的 `lib<SOC>.os.<CONFIG>.a`（arm64e + Apple Silicon 专用），于是 `osfmk/arm64/*.s` 一个都没编。
  `nos_arm_asm` 是**需要被打开的选项**，不是"不要汇编"的意思。
- 修复：新增 `config/MASTER.arm64.polaris`（`0100`）——内容与最终版 `MASTER.arm64.sweet` 逐字相同，里面没有一条是板子相关的；它在最后生成，所以已经带上后续补充（mockfs ramdisk root、sweet_hfs、bindfs、stubbed ext resolver）。

### #5 对照组：SWEET 也挂

- 特意 dispatch 一次 `MACHINE_CONFIG=SWEET`（run 39468989984），**同样失败且同样是 arm64e**。说明该缺陷是环境既有问题，不是 POLARIS 引入的；反过来也佐证 #4 是 POLARIS 专属缺口（SWEET 死在编译，POLARIS 已走到链接）。

### #6 环境与工具坑（重来必看）

| 坑 | 症状 | 解法 |
|---|---|---|
| Windows git autocrlf | 远程 bash 报 `set -o pipefail\r` | 全部源文件 LF（见 `.gitattributes`），脚本跑前确认无 `\r` |
| Debian awk 是 mawk | `gawk: strtonum` 不存在 | `shim/build.sh` 改用 bash 原生十六进制算术 |
| 沙箱内 `git push` 被代理拦（CONNECT 502） | push rc=128 | 换 GitHub Contents API 提交，或直接 `git push` 走可达代理 |
| Contents API 提交**不触发** Actions | 推完没有 run | 每次显式 `workflow_dispatch`（`ci/trigger_build.py`） |
| `if cmd \| tail; then` | 退出码取自 `tail`，永远为真、误判成功 | 用真实 `$?` / `${PIPESTATUS[0]}` |
| 只看 CI 网页上的错误摘要 | 找不到第一轮到底错在哪 | 拉 `{run}/logs` 压缩包，直接 grep `*_Build.txt`（`ci/watch_run.py` 就是干这个的） |

---

## 6. 待真机确认清单

> 这一段专门给设备主看：下面这些从上往下逐项确认，确认一项改一项状态。**别忘了串口线。**

- [ ] **串口**：把 Mix 2S 的 UART（`qup_uart@0xa84000`）接到 FTDI，115200 8N1。没有串口日志，后面所有项都只能盲猜。
- [ ] **UEFI 固件单独跑**：`fastboot boot Mu-polaris.img` → 应能看到 Project Mu 的输出/进 UEFI shell。**这一步不写分区，长按电源重启即可回到安卓。**
- [ ] **完整镜像**：`fastboot boot shim-polaris-kernel-boot.img` → shim banner → XNU 启动日志 →（预期）卡在找不到 root 设备。这个panic 是**符合预期的**，说明引导链通了。
- [ ] **回滚确认**：重启后安卓正常、串号/IMEI 未变。
- [ ] **内核 arch**：取下引起不来时，先 `ci/verify_artifacts.py --kernel ...` 确认 cputype 是 ARM64 而不是 ARM64E。
- [ ] **多核**：日志里确认几颗核被唤醒；adb/lockdownd 之类能起来再说。

失败时请把**完整串口日志**贴进 Issue，而不是"黑屏"三个字——黑屏可能停在 shim、XNUhead、或者 framebuffer 地址不对，三者路子完全不同。

---

## 7. 路线图

| 顺序 | 目标 | 说明 |
|---|---|---|
| 下一步 | **M3.5**：解 OS DMG 做 HFS+ root、接上 UFS 分区 | 不做完这步永远到不了 dyld |
| 之后 | M4：显示管线（IOMobileFramebuffer） | 先把控制台画面点亮，再谈 UI |
| 之后 | M5：触控、充电、WiFi 等基础外设 | |
| stretch | **M6：GPU（Adreno 630）** | mesa a6xx 寄存器文档已就位。**只有在实证后才能下结论**，本仓库不会预先把它判为不可能 |

---

## 8. 许可与致谢

- 本仓库自己写的部分（补丁、工具、shim 改动、CI 脚本）以 **MIT** 发布，见 `LICENSE`。
- XNU 本身遵循 **Apple Public Source License (APSL)**，版权归 Apple Inc. 与 Carnegie Mellon University；本仓库只提供对此源码的**补丁**，不包含其任何源码。
- Mu-Silicium / Project Mu 遵循各自的 BSD 系许可与上游仓库协议。
- 致谢：[dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet)（XNU-on-Snapdragon 的先行工作）、[Mu-Silicium](https://github.com/mu-silicium)（polarisPkg 的 UEFI 平台包）、mesa/freedreno（Adreno 630 寄存器文档）。

> 本工程为**个人学习与私有设备移植研究**，不提供也不分发任何 Apple 固件或成品镜像。刷机有风险，任何操作请先备份串号分区（persist / modemst / fsg）。
