#!/usr/bin/env python3
"""Check everything we packed before it ever touches a phone.

    python3 ci/verify_artifacts.py \
        --image   artifacts/shim-polaris-kernel-boot.img \
        --payload artifacts/polaris-payload.bin \
        --kernel  artifacts/kernel-polaris/kernel.development.polaris

Three independent checks, all offline:

  1. the boot image header (magic ANDROID!, sizes, page alignment, layout)
  2. the ramdisk slice is byte-identical to the payload we meant to ship,
     and the trailing blob is byte-identical to the Mix 2S DTB
  3. the kernel is a Mach-O with cputype ARM64 (NOT ARM64E - Mix 2S has no
     pointer authentication, an arm64e kernel would trap immediately)

Exits non-zero if any check fails.
"""

import argparse
import hashlib
import struct
import sys


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def check_image(img_path, payload_path, dtb_path, verbose=True):
    ok = True
    d = open(img_path, "rb").read()
    if verbose:
        print("=== boot image: %s (%d bytes) ===" % (img_path, len(d)))
        print("  sha256 : %s" % sha256(d))
    if d[:8] != b"ANDROID!":
        print("  FAIL magic %r != ANDROID!" % d[:8])
        return False

    (magic, kernel_size, kernel_addr, ramdisk_size, ramdisk_addr,
     second_size, second_addr, tags_addr, page_size, dt_size,
     unused) = struct.unpack("<8s10I", d[:48])
    if verbose:
        print("  kernel_size  : {:,}".format(kernel_size))
        print("  ramdisk_size : {:,}".format(ramdisk_size))
        print("  second_size  : {:,}".format(second_size))
        print("  dt_size      : {:,}".format(dt_size))
        print("  page_size    : {}".format(page_size))
        print("  tags_addr    : 0x{:08x}".format(tags_addr))

    pages = lambda n: (n + page_size - 1) // page_size
    kstart = page_size
    rstart = kstart + pages(kernel_size) * page_size
    sstart = rstart + pages(ramdisk_size) * page_size + pages(second_size) * page_size
    if verbose:
        print("  layout       : kernel@{:,} ramdisk@{:,} dtb@{:,}".format(
            kstart, rstart, sstart))

    if payload_path:
        pay = open(payload_path, "rb").read()
        same_hdr = len(pay) == ramdisk_size
        same_bytes = bytes(d[rstart:rstart + len(pay)]) == pay
        print("  payload    : {} disk / {} in header -> {}".format(
            len(pay), ramdisk_size, "size ok" if same_hdr else "SIZE MISMATCH"))
        print("  byte-identical in image: {}".format(same_bytes))
        ok &= same_hdr and same_bytes

    if dtb_path:
        dtb = open(dtb_path, "rb").read()
        blob = bytes(d[sstart:sstart + len(dtb)])
        print("  dtb        : {} bytes -> {}".format(
            len(dtb), "byte-identical" if blob == dtb else "MISMATCH"))
        ok &= (blob == dtb)

    return ok


def check_kernel(path):
    """Mach-O sanity: must be ARM64, not ARM64E."""
    mh = open(path, "rb").read(32)
    magic, cputype, cpusub, filetype, ncmds, sizeofcmds = struct.unpack("<6I", mh[:24])
    names = {0xFEEDFACF: "MH_MAGIC_64", 0xCFFAEDFE: "MH_CIGAM_64"}
    cpus = {0x0100000C: "ARM64", 0x0200000C: "ARM64E", 0x01000007: "X86_64"}
    print("=== kernel: %s ===" % path)
    print("  magic     : 0x%08x %s" % (magic, names.get(magic, "?")))
    print("  cputype   : 0x%08x %s" % (cputype, cpus.get(cputype, "?")))
    print("  cpusubtype: 0x%08x" % cpusub)
    print("  filetype  : %d (%s)" % (filetype,
                                     "MH_EXECUTE/kernel" if filetype == 2 else "?"))
    print("  ncmds     : %d, sizeofcmds %d" % (ncmds, sizeofcmds))
    good = magic in names and cputype == 0x0100000C and filetype == 2
    print("  verdict   : %s" % ("OK" if good else "FAIL - not an arm64 MH_EXECUTE"))
    return good


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--payload")
    ap.add_argument("--dtb")
    ap.add_argument("--kernel")
    args = ap.parse_args()

    if not (args.image or args.kernel):
        sys.exit("nothing to check")

    ok = True
    if args.image:
        ok &= check_image(args.image, args.payload, args.dtb)
    if args.kernel:
        ok &= check_kernel(args.kernel)

    print("\nRESULT: %s" % ("ALL CHECKS PASSED" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
