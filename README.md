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
| M0 | 从 Mix 2S 固件解码出真实硬件参数（GIC / UFS / 帧缓冲 / 面板 / 内存） | ✅ |
| M1 | XNU 新增 `POLARIS` 机器配置，编译 + 链接全绿 | ✅ 真机跑到用户态 |
| M2 | shim 适配 Mix 2S 帧缓冲 `0x9d400000` 与面板 1080×2160 | ✅ 屏幕有输出 |
| M3 | ADT 生成 → payload 打包 → 合成 Android boot 镜像，三部件字节级校验通过 | ✅ |
| M3.5 | **UFS 根 + HFS+ 卷 → 自写 init 作为 PID 1 在真机上跑起来** | ✅ 2026-10-21 确认 |
| M3.6 | 把卷里的自写 init 换成 iPhone X 20H392 的 Apple 用户态（dyld / launchd） | ⏳ 构建中 |
| — | Mu-Silicium `polaris` UEFI 固件编译成功（1.7 MB，UEFI shell 自检通过） | ⏳ 待真机 |
| M4+ | 显示管线 / 触控 / GPU / WiFi / 音频 … | 🔧 未开始 |

引导链已经打通到用户态，卡的是**用户态里装的是谁**：现在卷里的 `/sbin/launchd` 是我们自己写的
16 KB 静态程序（它唯一的工作就是每 5 秒说一次自己还活着），换成 Apple 的那一整套才是 M3.6。

---

## 2. 功能适配矩阵

> 状态列在你的机器上跑过之前不会动。「验证方法」一列就是到时候请你做的事。

### 2.1 引导链

| 功能 | 状态 | 实现 / 修复方案 | 你需要这样验证 |
|---|:--:|---|---|
| Mi Mix 2S 的 UEFI 固件（Mu-Silicium polarisPkg） | ⏳ | 直接编译上游 `polarisPkg`，未改一行上游代码；构建命令 `python3 build_uefi.py -d polaris` | `fastboot boot Mu-polaris.img`，串口应出 UEFI banner（详见第 6 节） |
| 不动原 bootloader、可回滚 | ⏳ | 只用 `fastboot boot` 内存引导，**不 flash 任何分区** | 长按电源重启后应正常回到原来的安卓系统 |
| shim → XNU 控制权交接 | ✅ | `shim/`：读 DTB、建 1:1 页表、把 payload 搬到虚拟地址 `0xfffffe0006000000` 后跳转 | 已确认：内核一路跑到 IOKit 并进入用户态 |
| 帧缓冲控制台（看屏幕） | ✅ | shim 的 console 直接写面板帧缓冲，1080×2160，2x 字号 | 已确认：开机就有逐行文字，是所有后续调试的实际通道 |
| UART 串口（115200 8N1） | ⏳ | `shim/console.c` 走 BLSP UART `qup_uart@0xa84000`（DTB aliases: serial0） | 设备主目前是**直接看手机屏**；串口线还没接，这条路未验证 |

### 2.2 内核与机器描述

| 功能 | 状态 | 实现 / 修复方案 | 你需要这样验证 |
|---|:--:|---|---|
| XNU `POLARIS` 机器配置 | ✅ | `xnu/patches/0099` + `0100`；Mix 2S 与 SWEET 同为 "generic ARM64 + GICv3 双安全态 + 19.2 MHz timer + 无 PAC"，故 POLARIS.h 直接继承 SWEET.h，差异全部下放到设备树 | 已确认：内核在真机上跑到用户态。`ci/verify_artifacts.py --kernel ...` 会报 cputype `ARM64`（而非 ARM64E） |
| 不开 PAC / 保持 arm64 | ✅ | 强制 `override ARCH_STRING_FOR_CURRENT_MACHINE_CONFIG := arm64`（见修复记录 #2）。Kryo 385 与 iPhone X 的 A11 都没有指针认证 | 同上，cputype 必须是 ARM64 |
| AppleDeviceTree 生成（Mix 2S 参数） | ✅ | `tools/mkadt.py` 新增 `--polaris`（默认），写入 FB `0x9d400000`、1080×2160、UFS `0x1d84000/0x2500`、DRAM `0xb0000000/0x4d000000`；**SWEET 输出字节不变**（已回归核对） | 已确认：`IOPlatformExpert.cpp:2319` 的 panic 消失。见修复记录 #7（字符串必须 NUL 分隔） |
| 设备树打包进镜像 | ✅ | boot.img 尾部附 Mix 2S 原始 DTB（491,356 B），shim 启动时解析 | `ci/verify_artifacts.py` 报 dtb byte-identical |
| 多核（8 核 Kryo 385） | ⏳ | 沿用 SWEET 的扁平 8 核单簇方案（`MAX_CPU_CLUSTERS=1`，ADT 全 `cluster-id=0`）；**目前启动参数是 `cpus=1`**，先单核跑通再谈 big.LITTLE | 去掉 `cpus=1` 后看几颗核起来 |
| 定时器 / GICv3 中断 | ✅ | 与 SWEET 完全相同，直接继承；虚拟定时器 INTID 19 | 已确认：用户态 init 每 5 秒一次心跳，说明定时器中断在走 |

### 2.3 存储与用户态

| 功能 | 状态 | 实现 / 修复方案 | 你需要这样验证 |
|---|:--:|---|---|
| UFS 主机控制器驱动（SDM845） | ✅ | 0028 的 `bsd/dev/sweet_ufs.c`；ADT 里 `/sweet-ufs` 的 reg 是 `<0x1d84000, 0x2500>`——**这是 Mix 2S 的真实值**（sweet 是 `0x3000`）。驱动只读，不碰数据 | 已确认：屏幕出现 `SWEET UFS: "userdata" on LUN 0` 并继续往下走 |
| HFS+ root 从 UFS 挂载 | ✅ | 卷必须造在 macOS 上：Linux 侧 hfsfuse 是只读的、飞牛 NAS 内核没有 hfsplus 模块、`mkfs.hfsplus` 只出空卷（见修复记录 #8） | 已确认：屏幕出现 `hfs: mounted SweetRoot on device b(1, 0)` |
| PID 1 从 **UFS 根**上跑起来 | ✅ | 自写的静态 Mach-O init 放进卷的 `/sbin/launchd` | **已确认（2026-10-21）**：屏幕 `*** SWEET userspace: init running as PID 1 ***` + 每 5 秒 `SWEET init: still alive` |
| PID 1 从 **RAM 盘**上跑起来（`rd=md0`） | ✅ | 同一份 init 塞进 ramdisk 槽 + mockfs，不刷任何分区 | 已确认：屏幕同样出这两行 |
| Apple 真正的 dyld / launchd | ⏳ | 卷里换成 iPhone X 20H392 的用户态（OS rootfs + 两个 cryptex），dyld 共享缓存硬链到 `/System/Library/Caches/com.apple.dyld` | 屏幕应出 `Darwin Bootstrapper Version 7.0.0` |

### 2.4 外设（全部未开始）

| 功能 | 状态 | 实现 / 修复方案（方案，尚未写代码） |
|---|:--:|---|
| 帧缓冲文本控制台 | ✅ | shim 的 console 直接写 `0x9d400000`、1080×2160、2x 字号；已确认是实际调试通道 |
| 显示（IOMobileFramebuffer / UI 画面） | 🔧 | 文字有了，图形/合成管线还没接：需要按内核实际停的位置补 Apple 显示管线的 veneer 与 FB 属性贴合 |
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
  check_adt.py   遍历生成的树，报出任何不以 NUL 结尾的字符串属性（#7 就是它抓到的）
  mkpayload.py   把内核 + ADT + ramdisk 打包成 shim 认得的 payload；--machine 自动选 ADT
  repack_bootimg.py  只换 boot.img 里 payload 那一槽，不用重编 shim；带往返自测
  mkhfsroot.sh   在 macOS 上造一个裸 HFS+ 卷（只有它能写 HFS+，见 #8）
  mkiosroot-macos.sh  把 iOS 16 的三个 APFS 镜像搬进 HFSX 卷，产出可刷的根镜像
  img2simg.py    raw → Android sparse。10 GB 镜像要刷进分区，非它不可
  sweet-init.b64 自写的最小 init（base64 文本入库；二进制不进 git）
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

# 5b) 根文件系统卷（UFS 根才需要，两档任选）
     #     最小验证版：一个 32 MB 卷，里面只有一个自写的 /sbin/launchd
base64 -D < tools/sweet-init.b64 > /tmp/sweet-init
./tools/mkhfsroot.sh root-hfs.raw 32 /tmp/sweet-init
     #     完整 iOS 16 版：三个 APFS 镜像出自你自己的 IPSW，仓库不提供
./tools/mkiosroot-macos.sh ios16-root.raw OS.dmg SYSTEMOS.dmg APPOS.dmg
python3 tools/img2simg.py ios16-root.raw ios16-root.simg
     #     10 GB 级的镜像只能以 sparse 形式刷（见 #8 里的 max-download-size）
fastboot -S 512M flash userdata ios16-root.simg

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
| 本地改了没提交就用脚本推远端 | 推上去的树把远端**回滚**了（见 #9） | 触发构建前跑 `check_remote_sync.py` |

### #7 2319 panic 的真根因：ADT 里的字符串没有 NUL 分隔

- 现象：`unable to find driver for this platform:"D22APiPhone10,3xiaomi,polarisqcom,sdm845AppleARMmodel"` @`IOPlatformExpert.cpp:2319`。
- **我第一次判错了**：以为是内核 personality 表里没有 polaris 条目（表里的 `IONameMatch` 确实写死 `xiaomi,sweet`），于是补了 `xnu/patches/0101` —— 真机上 panic **一字未变**。
- 真根因在 `tools/mkadt.py`：`compatible` 是**裸拼接** `b'D22AP' + b'iPhone10,3' + b'xiaomi,polaris' + ...`，成了一条 44 字节的字符串。设备树的 `compatible` 是 NUL 分隔的**字符串列表**，`IODTCompareNubName` 拿它跟 `IONameMatch` 逐项比——连成一串等于零个可匹配项，于是落到 `IOPanicPlatform`（那个类的整个存在意义就是 panic）。
- 顺带解释了 panic 结尾那个突兀的 `model`：连结尾 NUL 都没有，内核按 C 字符串读会越界，把下一个属性的名字一起读进来。**这条串从头到尾都在给答案，我第一次没读懂。**
- 修复：`strlist()` / `cstr()`（`cstr` 要同时接受 `str` 和 `bytes`，`bytes` 没有 `.encode()`，第一版直接崩）；新增 `tools/check_adt.py` 遍历整棵树报出所有不以 NUL 结尾的字符串属性——修复前 12 处，修复后 0 处；ADT 体积 9912→9920，正好是补上的 NUL 数量。
- 代价：`0101` 里 CPU（`qcom,kryo385`）和显示（`polaris,display`）两条是必要的，平台专家那条是追着一个不存在的影子补的。

### #8 往 HFS+ 卷里灌文件：Linux 全线堵死，改走 macOS

- 需求：卷里得有文件——先是 16 KB 的 init，后来是 10 GB 的 iOS 用户态。
- 三条路都堵死：

| 办法 | 结果 |
|---|---|
| NAS 上 `mount -t hfsplus -o loop` | ❌ 飞牛内核 6.18.18-trim 没有 hfsplus 模块；机器上只有内核头文件、没有源码树，也编不出来 |
| hfsfuse（现场编译的） | ❌ **设计上只读**，README 原话 "read-only and cannot write to or alter the target filesystem" |
| 本机 WSL | ❌ 没装 |

- 修复：卷造在 macOS runner 上，用 Apple 自己的 `newfs_hfs`——与 XNU 的 hfs kext 同源。产出是**偏移 0 就是 HFS+ 的裸盘**（无 UDIF 尾部、无分区表），fastboot 能直接写。
- macOS 的两个坑：BSD 的 `base64` 没有 `--decode`（只认 `-D`，4 秒就挂了一次）；无分区表镜像 macOS 有时会合成 slice，挂载要把 `$dev` 和 `${dev}s1` 两个候选都试。

### #9 只留在工作区的改动，会被推送脚本反向推没

- 现象：新的一轮 CI 报的错和最早那轮一模一样（`pmap_sign_user_ptr` / `jop_pid` 未声明），看着像编译环境问题。
- 根因：上一轮的关键修复只存在于**本地工作区**，从未 commit；而推送脚本是按本地 `HEAD` 建整棵树的，于是把远端**回滚**成了旧版（远端 0099 只有 4153 字节，好的版本 6410 字节，`MASTER.arm64.polaris` 整个丢失）。
- 修复：补提交推回去；新写 `check_remote_sync.py`，逐 blob 比对远端树与本地 HEAD，并提示工作区里没提交的内容。**触发构建前必跑。**

---

## 6. 真机记录与待确认清单

### 6.1 2026-10-21：引导链一路打通到用户态（M3.5）

设备 `faa72261`，`fastboot boot`（内存引导，不写分区）。设备主目前是**直接看手机屏**。

第一次上机，内核跑进了 IOKit 才停：

```
unable to find driver for this platform:"D22APiPhone10,3xiaomi,polarisqcom,sdm845AppleARMmodel"
@IOPlatformExpert.cpp:2319
debug_log_init: Error!! gPanicBase is still not initialized
"name" not a kext
"AAPL,phandle" not a kext
SWEET: trust cache unavailable (Image4/AMFI not installed)
handshake structure not initialized
```

修好设备树后（#7），进到没有根设备：

```
Waiting on IOMedia/Apple_HFS
Failed to write boot-picker-bringup-reason to NVRAM.
```

把 HFS+ 卷刷进 `userdata` 并用 `rd=ufsroot0` 之后，卷里还是空的：

```
SWEET: root volume is not authenticated (error 25): continuing unsealed
devfs_kernel_mount: kernel_mount failed: 2
panic: Process 1 exec of /sbin/launchd failed, error 2 @kern_exec.c:6929
```

`error 2` = ENOENT，三个位置指向同一件事：**卷是空的**。换成带 `/sbin/launchd` 的卷后：

```
*** SWEET userspace: init running as PID 1 ***
SWEET init: still alive
SWEET init: still alive
```

同一份 init 在 RAM 盘根（`rd=md0`，不刷任何分区）上也是同样两行。
M3.5 到此确认。

### 6.2 待确认

> 下面从上往下逐项确认，确认一项改一项状态。**别忘了串口线。**

- [ ] **串口**：把 Mix 2S 的 UART（`qup_uart@0xa84000`）接到 FTDI，115200 8N1。现在只能看屏幕，看不到滚出屏外的行。
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
| 进行中 | **M3.6**：把 iPhone X 20H392 的用户态放进卷里（OS rootfs + 两个 cryptex + dyld 共享缓存），让 Apple 的 launchd 起来 | 三个已经看清的坎：内核是 macOS 配置，会把 iOS 平台二进制判成 alien（`unentitled_ios_sim_launch=1` 绕）；没有 AMFI，`launchd_cache_loader` 会 abort；dyld 在 ignition level 1 只找 `/System/Library/Caches/com.apple.dyld` |
| 之后 | M4：显示管线（IOMobileFramebuffer） | 控制台文字已经有了，下一步是给 UI 的显示管线 |
| 之后 | M5：触控、充电、WiFi 等基础外设 | |
| 之后 | M5：触控、充电、WiFi 等基础外设 | |
| stretch | **M6：GPU（Adreno 630）** | mesa a6xx 寄存器文档已就位。**只有在实证后才能下结论**，本仓库不会预先把它判为不可能 |

---

## 8. 许可与致谢

- 本仓库自己写的部分（补丁、工具、shim 改动、CI 脚本）以 **MIT** 发布，见 `LICENSE`。
- XNU 本身遵循 **Apple Public Source License (APSL)**，版权归 Apple Inc. 与 Carnegie Mellon University；本仓库只提供对此源码的**补丁**，不包含其任何源码。
- Mu-Silicium / Project Mu 遵循各自的 BSD 系许可与上游仓库协议。
- 致谢：[dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet)（XNU-on-Snapdragon 的先行工作）、[Mu-Silicium](https://github.com/mu-silicium)（polarisPkg 的 UEFI 平台包）、mesa/freedreno（Adreno 630 寄存器文档）。

> 本工程为**个人学习与私有设备移植研究**，不提供也不分发任何 Apple 固件或成品镜像。刷机有风险，任何操作请先备份串号分区（persist / modemst / fsg）。
