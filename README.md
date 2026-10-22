English | [简体中文](README.zh-CN.md)

# iOS 16 on Xiaomi Mi Mix 2S (`polaris` / Snapdragon 845)

Bringing **iOS 16 (XNU 8796, iPhone X userspace baseline)** to the **Xiaomi Mi Mix 2S (codename `polaris`, Qualcomm Snapdragon 845 / SDM845)**.

## About

The strategy mirrors the Hackintosh approach: rather than modifying Apple binaries, the platform is presented to XNU as a target-conformant environment through a **Project Mu UEFI firmware (Mu-Silicium)**, after which a **custom arm64 boot shim** bootstraps the XNU kernel.

Boot architecture:

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

### Role of Mu-Silicium

Mu-Silicium is a port of **Project Mu** (Microsoft's open-source UEFI implementation framework) that provides `polarisPkg`, a UEFI platform package targeting the Mi Mix 2S (SDM845). Within this project its function is to act as the device's **UEFI firmware stage**: it performs early platform initialization (DRAM configuration, clock and power-resource setup via RPMh, UART and GICv3 configuration) and exposes standard UEFI boot services, from which the boot shim is launched. In the current bring-up the stock ABL is used with `fastboot boot` to load the shim image directly, so the Mu-Silicium UEFI stage is an alternative / optional firmware path; adopting it would replace the stock ABL's early-init responsibility with a standards-based UEFI environment. Build status: UEFI image built (1.7 MB, UEFI shell self-test passed); on-device verification pending.

---

## Read this first (three rules)

1. **This repository contains no Apple source.** No iPSW, dyld, SpringBoard, fonts, or frameworks — and no downloads for them in the tree. They are Apple intellectual property; obtain them from your own device or official channels. The repository ships only our own configuration, patches, tooling, and boot bridging code. Built binaries are published separately as GitHub Release assets (see §3), never committed to the tree.
2. **The ✅ / ❌ markers in the status tables change only after the device owner `@JaneAwA` confirms them on real hardware.** Everything else remains ⏳ (code present and build/artifact-verified, but not yet run on device) or 🔧 (not yet implemented). PRs that flip a marker without on-device evidence are rejected. To change a status, attach on-device logs or video in an Issue.
3. **Prebuilt images are published as GitHub Releases — not in the source tree.** `artifacts/` is git-ignored, so binaries never enter the repository; instead the built UEFI firmware (`Mu-polaris.img`) and the iOS 16 root volume (`ios16-root.simg`) are uploaded to the project's GitHub Releases. Each asset ships with a SHA-256 checksum for integrity verification. Download a release if you would rather not build from source.

Legend:

| Symbol | Meaning                                                                                  |
| ------ | ---------------------------------------------------------------------------------------- |
| ✅      | Confirmed working on real hardware (device owner only)                                   |
| ❌      | Confirmed non-working on real hardware / approach rejected                               |
| ⏳      | Implemented; build and artifact verification passed, **awaiting on-device confirmation** |
| 🔧     | Not yet implemented (no corresponding code, or code not finalized)                       |

---

## 3. Prebuilt releases

The repository ships source, patches, and tooling only; the large binary products are published as GitHub Release assets so you do not have to run the full CI pipeline yourself. Every asset carries a SHA-256 checksum for integrity verification.

| Asset                        | Size              | What it is                                                                                                                              | Built from                                                                                  | Status            |
| ---------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | ----------------- |
| `Mu-polaris.img`             | ~1.7 MB           | Mu-Silicium UEFI firmware (`polarisPkg`) — the optional firmware stage that performs early platform init and bootstraps the boot shim  | `python3 build_uefi.py -d polaris`                                                           | ⏳ pending        |
| `shim-polaris-kernel-boot.img` | ~tens of MB    | Composite Android boot image: boot shim + XNU payload + ADT + stock DTB (loaded via `fastboot boot`; writes no partition)              | `shim/build.sh` + `mkbootimg`                                                               | ⏳ pending        |
| `ios16-root.simg`            | ~5.8 GB (sparse) | Sparse HFS+ root volume populated with iPhone X 20H392 iOS 16.7.16 userspace (OS rootfs + two cryptexes + dyld shared cache)           | CI `mode=ios`: IPSW → attach 3 DMGs → HFSX volume → `tools/img2simg.py`                      | ⏳ pending (M3.6) |

> The `ios16-root.simg` volume is a **derived artifact generated by CI from an IPSW you supply**; it bundles Apple userspace binaries under your own Apple license. The source tree itself still contains no Apple source (see rule 1). Flash it with `fastboot -S 512M flash userdata ios16-root.simg`, then `fastboot boot shim-polaris-kernel-boot.img`.

---

## 1. Current status

To this point, the **full pipeline from source to a bootable `fastboot boot` image is reproducible in a single pass**:

| Milestone | Content                                                                                                            | Status                                                                             |
| --------- | ------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| M0        | Decode real hardware parameters from Mix 2S firmware (GIC / UFS / framebuffer / panel / memory)                    | ✅                                                                                  |
| M1        | XNU gains `POLARIS` machine config; compile + link clean                                                           | ✅ confirmed to userspace on device                                                 |
| M2        | shim adapts Mix 2S framebuffer `0x9d400000` and panel 1080×2160                                                    | ✅ screen output confirmed                                                          |
| M3        | ADT generation → payload packaging → composite Android boot image; byte-level verification of all three components | ✅                                                                                  |
| M3.5      | **UFS root + HFS+ volume → custom init running as PID 1 on real hardware**                                         | ✅ confirmed 2026-10-21                                                             |
| M3.6      | Replace the volume's custom init with iPhone X 20H392 Apple userspace (dyld / launchd)                             | ⏳ In progress — clean artifact built and verified on-disk (0 decmpfs records); on-device verification pending |
| —         | Mu-Silicium `polaris` UEFI firmware built (1.7 MB, UEFI shell self-test passed)                                    | ⏳ awaiting on-device run                                                           |
| M4+       | Display pipeline / touch / GPU / WiFi / audio …                                                                    | 🔧 not started                                                                     |

The boot chain is brought up through to userspace; the remaining gap is the *contents* of userspace. The current volume's `/sbin/launchd` is a 16 KB static Mach-O program we authored (its only function is to emit a heartbeat every 5 seconds); replacing it with Apple's full userspace stack is the objective of M3.6.

### 1.1 `errno 45` at `exec` of `/sbin/launchd`

A first attempt at the Apple userspace volume panicked during boot with:

```
panic: Process 1 exec of /sbin/launchd failed, errno 45 @kern_exec.c:6929
```

`45` is `EOPNOTSUPP`. The cause is **not** the boot chain but the volume's *filesystem metadata*: XNU's `bsd/kern/decmpfs.c` only registers a **Type 1** decompressor, so a file that carries Apple's **Type 4 (LZVN)** compression cannot be read. `decmpfs_read_compressed()` returns `EOPNOTSUPP` and `load_init_program()` fails.

Reading the HFS+ catalog and attribute B-trees directly (`tools/hfsxattr.py`, which walks the leaf chain and counts only live records) shows the previously published root image was:

| Measurement                            | Previously published image | Clean image |
| -------------------------------------- | -------------------------- | ----------- |
| Live `com.apple.decmpfs` xattr records | 131,125                    | **0**       |
| Files flagged `UF_COMPRESSED`          | 131,103                    | **0**       |
| `/sbin/launchd` data fork              | 0 bytes (content only in the xattr) | 541,600 bytes, plain FAT Mach-O |

The kernel's `decmpfs` path is entered when a vnode has both the `UF_COMPRESSED` flag and the `com.apple.decmpfs` attribute; `/sbin/launchd` had both. `tools/hfsxattr.py` reports `VERDICT: CLEAN` for the rebuilt volume and can be run against any image to decide this without relying on the CI's own macOS-side check.

---

## 2. Hardware adaptation matrix

> Status columns do not move until the feature has been exercised on your device. The "Verification" column describes what you will be asked to do.

### 2.1 Boot chain

| Feature                                                  | Status | Implementation / fix                                                                                                   | How you verify                                                                                                               |
| -------------------------------------------------------- | :----: | ---------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Mi Mix 2S UEFI firmware (Mu-Silicium polarisPkg)         |    ⏳   | Built directly from upstream `polarisPkg`, no upstream line modified; build command `python3 build_uefi.py -d polaris` | `fastboot boot Mu-polaris.img`; serial console should emit the UEFI banner (see §6)                                          |
| No modification of stock bootloader; rollback-preserving |    ⏳   | `fastboot boot` performs in-RAM boot only, **no partition is flashed**                                                 | After a long-press power reboot, the original Android system should return normally                                          |
| shim → XNU control transfer                              |    ✅   | `shim/`: parse DTB, build 1:1 page tables, relocate payload to virtual address `0xfffffe0006000000`, then branch       | Confirmed: kernel reaches IOKit and enters userspace                                                                         |
| Framebuffer console (on-screen)                          |    ✅   | shim console writes directly to the panel framebuffer, 1080×2160, 2× glyph scale                                       | Confirmed: line-by-line text from power-on; the practical debug channel for all subsequent work                              |
| UART serial (115200 8N1)                                 |    ⏳   | `shim/console.c` uses BLSP UART `qup_uart@0xa84000` (DTB aliases: serial0)                                             | Device owner currently reads the **phone screen directly**; the serial cable is not yet attached, so this path is unverified |

### 2.2 Kernel and machine description

| Feature                                        | Status | Implementation / fix                                                                                                                                                                                              | How you verify                                                                                                            |
| ---------------------------------------------- | :----: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| XNU `POLARIS` machine config                   |    ✅   | `xnu/patches/0099` + `0100`; Mix 2S and SWEET share "generic ARM64 + GICv3 dual-security + 19.2 MHz timer + no PAC", so `POLARIS.h` inherits `SWEET.h` directly, with all deltas pushed down into the device tree | Confirmed: kernel reaches userspace on device. `ci/verify_artifacts.py --kernel ...` reports cputype `ARM64` (not ARM64E) |
| PAC disabled / arm64 retained                  |    ✅   | Force `override ARCH_STRING_FOR_CURRENT_MACHINE_CONFIG := arm64` (see fix record #2). Kryo 385 and iPhone X's A11 both lack pointer authentication                                                                | Same as above; cputype must be ARM64                                                                                      |
| AppleDeviceTree generation (Mix 2S parameters) |    ✅   | `tools/mkadt.py` adds `--polaris` (default); writes FB `0x9d400000`, 1080×2160, UFS `0x1d84000/0x2500`, DRAM `0xb0000000/0x4d000000`; **SWEET output bytes unchanged** (regression-checked)                       | Confirmed: the panic at `IOPlatformExpert.cpp:2319` is gone. See fix record #7 (strings must be NUL-terminated)           |
| Device tree packaged into image                |    ✅   | Mix 2S stock DTB (491,356 B) appended to the boot.img tail; parsed at shim startup                                                                                                                                | `ci/verify_artifacts.py` reports DTB byte-identical                                                                       |
| Multicore (8× Kryo 385)                        |    ⏳   | Reuses SWEET's flat 8-core single-cluster scheme (`MAX_CPU_CLUSTERS=1`, ADT all `cluster-id=0`); **current boot argument is `cpus=1`** — single core first, big.LITTLE later                                      | Remove `cpus=1` and observe how many cores come up                                                                        |
| Timer / GICv3 interrupts                       |    ✅   | Identical to SWEET, inherited directly; virtual timer INTID 19                                                                                                                                                    | Confirmed: userspace init heartbeat every 5 s proves the timer interrupt is firing                                        |

### 2.3 Storage and userspace

| Feature                             | Status | Implementation / fix                                                                                                                                                        | How you verify                                                                                                            |
| ----------------------------------- | :----: | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| UFS host controller driver (SDM845) |    ✅   | `0028`'s `bsd/dev/sweet_ufs.c`; ADT `/sweet-ufs` reg is `<0x1d84000, 0x2500>` — **the real Mix 2S value** (SWEET uses `0x3000`). Driver is read-only, touches no data       | Confirmed: screen shows `SWEET UFS: "userdata" on LUN 0` and continues                                                    |
| HFS+ root mounted from UFS          |    ✅   | Volume must be built on macOS: Linux hfsfuse is read-only, the fnOS NAS kernel lacks the hfsplus module, and `mkfs.hfsplus` only yields an empty volume (see fix record #8) | Confirmed: screen shows `hfs: mounted SweetRoot on device b(1, 0)`                                                        |
| PID 1 from **UFS root**             |    ✅   | Custom static Mach-O init placed at `/sbin/launchd` in the volume                                                                                                           | **Confirmed (2026-10-21)**: screen `*** SWEET userspace: init running as PID 1 ***` + `SWEET init: still alive` every 5 s |
| PID 1 from **RAM disk** (`rd=md0`)  |    ✅   | Same init placed in the ramdisk slot + mockfs; no partition flashed                                                                                                         | Confirmed: same two lines on screen                                                                                       |
| Apple's real dyld / launchd         |    ⏳   | Volume replaced with iPhone X 20H392 userspace (OS rootfs + two cryptexes); dyld shared cache hard-linked to `/System/Library/Caches/com.apple.dyld`                        | Screen should show `Darwin Bootstrapper Version 7.0.0`                                                                    |

### 2.4 Peripherals (all unstarted)

| Feature                                        | Status | Implementation / fix (plan, not yet coded)                                                                                                                                                                   |
| ---------------------------------------------- | :----: | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Framebuffer text console                       |    ✅   | shim console writes `0x9d400000`, 1080×2160, 2× glyph scale; confirmed as the practical debug channel                                                                                                        |
| Display (IOMobileFramebuffer / UI rendering)   |   🔧   | Text exists; graphics/compositor pipeline not yet attached — requires a veneer for Apple's display pipeline plus framebuffer property alignment, driven by where the kernel actually stalls                  |
| GPU (Adreno 630)                               |   🔧   | Register documentation already staged in mesa `src/freedreno/registers/adreno/a6xx*.xml`; viable path is an XNU IOGPU/AGX-style driver adaptation layer. **No conclusion drawn before empirical validation** |
| Touch (Synaptics DSX, not Goodix)              |   🔧   | Requires XNU I2C/HID-side adaptation; DTB confirms `synaptics,dsx-i2c-force`                                                                                                                                 |
| WiFi / Bluetooth                               |   🔧   | Requires SDM845 firmware plus XNU network-stack bridging                                                                                                                                                     |
| Audio                                          |   🔧   | Requires QDSP / ADSP-side interface adaptation                                                                                                                                                               |
| Camera                                         |   🔧   | Not started (depends on closed-source ISP)                                                                                                                                                                   |
| Charging / battery (PM8998 + PMI8998 + PM8005) |   🔧   | Not started. Battery management is high-risk; bring up the boot chain first                                                                                                                                  |
| Sensors / vibrator / sensor hub                |   🔧   | Not started                                                                                                                                                                                                  |
| Baseband / cellular                            |   🔧   | Not started (modem partition involves IMEI; handle with caution)                                                                                                                                             |


## 4. Reproduce from scratch

The baseline is [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet) (the project that runs XNU on Snapdragon 732G). **XNU compiles only under the macOS toolchain**, so the build uses a GitHub Actions `macos-14` runner; UEFI and shim compile natively on Linux.

> **Prefer ready-made images?** Grab `Mu-polaris.img` and `ios16-root.simg` from the project's GitHub Releases (§3) and skip straight to step 5b (flash `userdata`) and step 7 (`fastboot boot`). The procedure below is only needed if you want to rebuild from source.

```bash
# 1) Baseline: obtain an ios-sweet checkout (your fork)
git clone https://github.com/<you>/ios-sweet.git

# 2) Apply this repository's full change set in one pass (with a dry-run check)
./apply_to_upstream.sh /path/to/ios-sweet main

# 3) Kernel: build on CI (~1 hour, depending on runner queue)
export GITHUB_TOKEN=ghp_xxx
./ci/trigger_build.py --repo <you>/ios-sweet --config POLARIS --wait

# 4) With kernel.development.polaris in hand, generate the local ADT and payload
python3 tools/mkadt.py --polaris -o tools/polaris.adt
python3 tools/mkpayload.py --machine polaris -o payload.bin

# 5) shim and packaging
(cd shim && ./build.sh ../payload.bin)
mkbootimg --kernel shim/shim.bin --ramdisk payload.bin \
          --dtb dtb_out/dtb_36.dtb -o shim-polaris-kernel-boot.img

# 5b) Root filesystem volume (UFS root only; either tier)
     #     Minimal verification tier: a 32 MB volume holding only a custom /sbin/launchd
base64 -D < tools/sweet-init.b64 > /tmp/sweet-init
./tools/mkhfsroot.sh root-hfs.raw 32 /tmp/sweet-init
     #     Full iOS 16 tier: the three APFS images come from your own IPSW; not provided
./tools/mkiosroot-macos.sh ios16-root.raw OS.dmg SYSTEMOS.dmg APPOS.dmg
python3 tools/img2simg.py ios16-root.raw ios16-root.simg
     #     A 10 GB-class image can only be flashed as sparse (see #8, max-download-size)
fastboot -S 512M flash userdata ios16-root.simg

# 6) Pre-flight self-check (must report ALL CHECKS PASSED)
python3 ci/verify_artifacts.py \
    --image   shim-polaris-kernel-boot.img \
    --payload payload.bin \
    --dtb     dtb_out/dtb_36.dtb \
    --kernel  kernel.development.polaris

# 7) On device (no partition written; rollback at any time)
adb reboot bootloader && fastboot boot shim-polaris-kernel-boot.img
```

UEFI firmware (optional; an independent workstream tracked against upstream Mu-Silicium):

```bash
python3 Platforms/Xiaomi/polarisPkg/DeviceBuild.py --update -t RELEASE
python3 build_uefi.py -d polaris
```

---

## 5. Fix records

This section is a complete log of *problem → root cause → fix*, so the code's current shape is understandable in order. It took five CI rounds to get the kernel to compile clean — **every failure was excavated from the failed run's logs, not guessed.**

### #1 `Unsupported CURRENT_MACHINE_CONFIG POLARIS`

- Symptom: first CI round failed immediately with `MakeInc.kernel:22: *** Unsupported CURRENT_MACHINE_CONFIG POLARIS`.
- Root cause: the hand-written `0004b` patch had an incorrect hunk count (`@@ -9,7` for an actual 6 lines); `git apply` judged it corrupt and **skipped it**, so POLARIS never entered the `SUPPORTED_ARM64_MACHINE_CONFIGS` whitelist; the patch's insertion point was also repeatedly reshuffled by the 13 subsequent patches.
- Fix: download the failed run's `xnu-buildtree` artifact (i.e. xnu **after all patches applied**) → establish a baseline in git → edit the real files directly → generate `0099` with `git diff` (hunk counts computed by git, cannot be wrong), and normalize line endings. Delete `0004b`.

### #2 `-arch arm64e` → undefined ptrauth symbols

- Symptom: compiled with `-arch arm64e`; `__has_feature(ptrauth_calls)` enabled but `HAS_APPLE_PAC` absent, so `pmap_sign_user_ptr` / `jop_pid` undeclared; meanwhile `sweet_vtimer_intid` is used in `sleh.c` under `#if defined(SWEET)` but declared in `protos.h` under `#if defined(ARM64_BOARD_CONFIG_SWEET)` — the two sides disagree.
- Root cause: Kryo 385 and SWEET's Cortex-A76/A55 both lack pointer authentication, so both must be pure arm64; `ARCH_STRING` used `?=`, so any value in the environment silently skipped the override, leaving the target as arm64e.
- Fix: in `MakeInc.def`, use `ifneq ($(filter SWEET POLARIS,$(CURRENT_MACHINE_CONFIG)),)` to **force** pure arm64; in `POLARIS.h` `#include <pexpert/arm64/SWEET.h>` so `ARM64_BOARD_CONFIG_SWEET` and `POLARIS` are both defined, making declaration and use consistent (without re-including `board_config.h`, which would duplicate definitions).

### #3 Missing `sweet_bearssl/` and `sweet_libpthread/`

- Symptom: `'sweet_bearssl/inc/bearssl_hash.h' file not found`, `'sweet_libpthread/kern/kern_init.c' file not found`.
- Root cause: 3 stage scripts + 2 Makefile patches gated these info/utils with a **literal `== SWEET`**; but BearSSL (software AES/MD5/SHA), libpthread (XNU's own), and HFS (root filesystem) are board-independent.
- Fix (5 sites):
  - `0019-stage-libpthread.sh`, `0020-stage-bearssl.sh`, `0026-stage-hfs.sh`: gate changed to `case ... in SWEET|POLARIS)`.
  - `0019-sweet-builtin-pthread.patch`, `0020-sweet-portable-aes-cbc.patch`: `ifeq ($(CURRENT_MACHINE_CONFIG),SWEET)` → `ifneq ($(filter SWEET POLARIS,$(CURRENT_MACHINE_CONFIG)),)` (because bsd/conf's `-I` paths must take effect for POLARIS too).
  - Note: these are **strict 1:1 line replacements**; the unified-diff hunk line counts are unchanged, avoiding the #1 trap again.

### #4 264 undefined symbols at link time

- Symptom: `CleanPoC_Dcache`, `Idle_context`, `__start`, `__bcopyin` … 264 undefined.
- Root cause: `config/Makefile` locates `MASTER.arm64.<machine>` via `wildcard`; POLARIS had no such file, so it **silently fell back to Apple's original config**, which expects low-level symbols from the closed-source KDK's `lib<SOC>.os.<CONFIG>.a` (arm64e + Apple Silicon only) — consequently none of `osfmk/arm64/*.s` was compiled.  
  `nos_arm_asm` is an option that **must be enabled**, not "disable assembly".
- Fix: add `config/MASTER.arm64.polaris` (`0100`) — byte-identical to the final `MASTER.arm64.sweet`, containing nothing board-specific; generated last, so it already carries the later supplements (mockfs ramdisk root, sweet_hfs, bindfs, stubbed ext resolver).

### #5 Control case: SWEET also fails

- Deliberately dispatched a `MACHINE_CONFIG=SWEET` run (run 39468989984), which **failed identically and also as arm64e**. This proves the defect is pre-existing in the environment, not introduced by POLARIS; conversely it corroborates that #4 is POLARIS-specific (SWEET died at compile, POLARIS reached link).

### #6 Environment and tooling pitfalls (mandatory review before re-attempting)

| Pitfall                                              | Symptom                                                  | Resolution                                                                               |
| ---------------------------------------------------- | -------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Windows git autocrlf                                 | Remote bash reports `set -o pipefail\r`                  | All source files LF (see `.gitattributes`); verify no `\r` before running scripts        |
| Debian awk is mawk                                   | `gawk: strtonum` not found                               | `shim/build.sh` switched to bash-native hex arithmetic                                   |
| `git push` blocked by proxy in sandbox (CONNECT 502) | push rc=128                                              | Use GitHub Contents API to commit, or `git push` through a reachable proxy               |
| Contents API commit **does not trigger** Actions     | No run after push                                        | Always dispatch explicitly (`ci/trigger_build.py`)                                       |
| `if cmd \| tail; then`                               | Exit code taken from `tail`, always true → false success | Use the real `$?` / `${PIPESTATUS[0]}`                                                   |
| Reading only the CI web error summary                | Cannot locate the first-round error                      | Pull the `{run}/logs` archive, grep `*_Build.txt` directly (`ci/watch_run.py` does this) |
| Local edits not committed before pushing via script  | Pushed tree **rolls back** remote (see #9)               | Run `check_remote_sync.py` before triggering a build                                     |

### #7 The real root cause of the 2319 panic: ADT strings not NUL-terminated

- Symptom: `unable to find driver for this platform:"D22APiPhone10,3xiaomi,polarisqcom,sdm845AppleARMmodel"` @`IOPlatformExpert.cpp:2319`.
- **First diagnosis was wrong**: assumed the kernel personality table lacked a polaris entry (its `IONameMatch` is hard-coded to `xiaomi,sweet`), so patch `xnu/patches/0101` was added — the on-device panic was **unchanged**.
- Real root cause in `tools/mkadt.py`: `compatible` was **concatenated raw** as `b'D22AP' + b'iPhone10,3' + b'xiaomi,polaris' + ...`, forming a single 44-byte string. A device tree's `compatible` is a **NUL-separated string list**; `IODTCompareNubName` compares it entry-by-entry against `IONameMatch` — concatenated into one string, it matches nothing, so it falls through to `IOPanicPlatform` (whose entire reason for existing is to panic).
- This also explains the abrupt `model` at the panic tail: with no trailing NUL, the kernel reads past the C string boundary and pulls in the next property's name. **The string was answering the question the whole time; the first reading missed it.**
- Fix: `strlist()` / `cstr()` (`cstr` must accept both `str` and `bytes` — `bytes` has no `.encode()`, the first version crashed outright); added `tools/check_adt.py` to walk the whole tree and report every string property not NUL-terminated — 12 before the fix, 0 after; ADT size 9912 → 9920, exactly the NULs added.
- Cost: of the two `0101` entries (CPU `qcom,kryo385` and display `polaris,display`), both were necessary; the platform-expert entry was added in response to a non-existent phantom.


### #8 Populating the HFS+ volume: Linux is fully blocked; move to macOS

- Requirement: the volume must hold files — first a 16 KB init, later a 10 GB iOS userspace.
- All three routes blocked:

| Method                            | Result                                                                                                           |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `mount -t hfsplus -o loop` on NAS | ❌ fnOS kernel 6.18.18-trim has no hfsplus module; only kernel headers present, no source tree, cannot compile it |
| hfsfuse (compiled locally)        | ❌ **read-only by design**; README states "read-only and cannot write to or alter the target filesystem"          |
| Local WSL                         | ❌ not installed                                                                                                  |

- Fix: build the volume on a macOS runner using Apple's own `newfs_hfs` — same lineage as XNU's hfs kext. Output is a **raw disk with HFS+ at offset 0** (no UDIF trailer, no partition table), directly writable by fastboot.
- Two macOS pitfalls: BSD `base64` has no `--decode` (accepts only `-D`; failed once after ~4 s); an unpartitioned image is sometimes synthesized with a slice by macOS, so mount must try both `$dev` and `${dev}s1`.

### #9 Working-tree-only changes get pushed away by the sync script

- Symptom: a new CI round reported the exact same error as the very first (`pmap_sign_user_ptr` / `jop_pid` undeclared), looking like a build-environment issue.
- Root cause: the prior round's key fix existed only in the **local working tree**, never committed; the push script builds the entire tree from local `HEAD`, so it **rolled back** remote to the old version (remote `0099` was only 4153 bytes; the good version is 6410 bytes; `MASTER.arm64.polaris` was lost entirely).
- Fix: re-commit and push back; add `check_remote_sync.py`, which compares the remote tree against local `HEAD` blob-by-blob and flags uncommitted working-tree changes. **Run before every build trigger.**

---

## 6. On-device record and pending verification

### 6.1 2026-10-21: boot chain brought up through to userspace (M3.5)

Device `faa72261`, `fastboot boot` (in-RAM boot, no partition written). Device owner currently reads the **phone screen directly**.

First on-device run, kernel stalled only after entering IOKit:

```
unable to find driver for this platform:"D22APiPhone10,3xiaomi,polarisqcom,sdm845AppleARMmodel"
@IOPlatformExpert.cpp:2319
debug_log_init: Error!! gPanicBase is still not initialized
"name" not a kext
"AAPL,phandle" not a kext
SWEET: trust cache unavailable (Image4/AMFI not installed)
handshake structure not initialized
```

After fixing the device tree (#7), it reached no root device:

```
Waiting on IOMedia/Apple_HFS
Failed to write boot-picker-bringup-reason to NVRAM.
```

After flashing the HFS+ volume into `userdata` with `rd=ufsroot0`, the volume was still empty:

```
SWEET: root volume is not authenticated (error 25): continuing unsealed
devfs_kernel_mount: kernel_mount failed: 2
panic: Process 1 exec of /sbin/launchd failed, error 2 @kern_exec.c:6929
```

`error 2` = ENOENT; all three sites point to the same fact: **the volume was empty**. After switching to a volume containing `/sbin/launchd`:

```
*** SWEET userspace: init running as PID 1 ***
SWEET init: still alive
SWEET init: still alive
```

The same init on the RAM-disk root (`rd=md0`, no partition flashed) produced the same two lines. M3.5 confirmed at this point.

### 6.2 Pending verification

> Confirm top-down, one item at a time; flip a status only after confirming. **Do not forget the serial cable.**

- [ ] **Serial**: connect Mix 2S UART (`qup_uart@0xa84000`) to an FTDI adapter, 115200 8N1. Currently only the screen is readable; lines scrolling past it are invisible.
- [ ] **UEFI firmware standalone**: `fastboot boot Mu-polaris.img` → should show Project Mu output / drop into the UEFI shell. **This writes no partition; a long-press power reboot returns to Android.**
- [ ] **Full image**: `fastboot boot shim-polaris-kernel-boot.img` → shim banner → XNU boot log → (expected) stalls at "no root device". This panic is **expected** and confirms the boot chain is live.
- [ ] **Rollback confirmation**: after reboot, Android is normal and serial/IMEI unchanged.
- [ ] **Kernel arch**: if it fails to boot, first run `ci/verify_artifacts.py --kernel ...` to confirm cputype is ARM64, not ARM64E.
- [ ] **Multicore**: confirm in the log how many cores are woken; revisit once adb/lockdownd-class services can start.

On failure, attach the **full serial log** to an Issue, not a bare "black screen" report — a black screen could mean a stall in the shim, XNU head, or a wrong framebuffer address, and the three paths are entirely different.

---

## 7. Roadmap

| Order       | Goal                                                                                                                              | Notes                                                                                                                                                                                                                                                                               |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| In progress | **M3.6**: place iPhone X 20H392 userspace in the volume (OS rootfs + two cryptexes + dyld shared cache) so Apple's launchd starts | Three known obstacles: the kernel is built with the macOS config and judges iOS platform binaries as alien (`unentitled_ios_sim_launch=1` bypasses this); no AMFI, so `launchd_cache_loader` aborts; at ignition level 1 dyld looks only in `/System/Library/Caches/com.apple.dyld` |
| Next        | M4: display pipeline (IOMobileFramebuffer)                                                                                        | Text console exists; next is the UI display pipeline                                                                                                                                                                                                                                |
| Next        | M5: touch, charging, WiFi and other base peripherals                                                                              |                                                                                                                                                                                                                                                                                     |
| Stretch     | **M6: GPU (Adreno 630)**                                                                                                          | mesa a6xx register docs already staged. **Conclusion only after empirical validation**; this repository will not pre-judge it as infeasible                                                                                                                                         |

---

## 8. License and acknowledgments

- The portions authored in this repository (patches, tooling, shim changes, CI scripts) are released under **MIT**; see `LICENSE`.
- XNU itself is governed by the **Apple Public Source License (APSL)**, copyright Apple Inc. and Carnegie Mellon University; this repository ships only **patches** against that source, never the source itself.
- Mu-Silicium / Project Mu are governed by their respective BSD-family licenses and upstream repository terms.
- Acknowledgments: [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet) (prior work on XNU-on-Snapdragon), [Mu-Silicium](https://github.com/mu-silicium) (the `polarisPkg` UEFI platform package), mesa/freedreno (Adreno 630 register documentation).

> This project is **personal study and private-device porting research**. The source tree ships only our own code, patches, and tooling — no Apple source (see rule 1). Built firmware (`Mu-polaris.img`) and the derived iOS 16 root volume (`ios16-root.simg`) are published as GitHub Release assets for convenience; the latter bundles Apple userspace generated by CI from an IPSW you supply, under your own Apple license. Flashing carries risk; back up the serial-number partitions (`persist` / `modemst` / `fsg`) before any operation.
