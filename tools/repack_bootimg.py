#!/usr/bin/env python3
"""Swap the XNU payload inside an existing boot.img without rebuilding the shim.

Why this exists: the shim only changes when the shim sources change. Rebuilding
the kernel is a GitHub Actions round trip, rebuilding the shim is a
cross-toolchain round trip, and most iterations are kernel-only. This rewrites
just the payload slot of an already-known-good image and leaves everything else
byte-identical, so a kernel iteration needs neither macOS nor aarch64 gcc.

Round trip is self-checked: repacking with the payload it already carries must
reproduce the input file byte for byte. If it does not, this script has a bug
and the output must not be flashed.

Usage:
    repack_bootimg.py IN.img NEW_PAYLOAD -o OUT.img [--slot ramdisk|second]
    repack_bootimg.py IN.img --selftest
"""

import argparse
import hashlib
import struct
import sys

MAGIC = b"ANDROID!"
PAGE_DEFAULT = 4096

# boot_img_hdr, little endian
F_KERNEL_SIZE = 8
F_KERNEL_ADDR = 12
F_RAMDISK_SIZE = 16
F_RAMDISK_ADDR = 20
F_SECOND_SIZE = 24
F_SECOND_ADDR = 28
F_TAGS_ADDR = 32
F_PAGE_SIZE = 36
F_HEADER_VERSION = 40
F_OS_VERSION = 44
F_NAME = 48
F_CMDLINE = 64
F_ID = 576          # sha1 x4
F_EXTRA_CMDLINE = 608
F_RECOVERY_DTBO_SIZE = 1632
F_RECOVERY_DTBO_OFFSET = 1636
F_HEADER_SIZE = 1644
F_DTB_SIZE = 1648
F_DTB_ADDR = 1652


class BootImage(object):
    def __init__(self, blob):
        if blob[:8] != MAGIC:
            raise ValueError("not an ANDROID! boot image (magic %r)" % blob[:8])
        self.blob = blob
        self.page = struct.unpack_from("<I", blob, F_PAGE_SIZE)[0] or PAGE_DEFAULT
        self.version = struct.unpack_from("<I", blob, F_HEADER_VERSION)[0]
        self.header_size = self.page
        self.kernel_size = struct.unpack_from("<I", blob, F_KERNEL_SIZE)[0]
        self.ramdisk_size = struct.unpack_from("<I", blob, F_RAMDISK_SIZE)[0]
        self.second_size = struct.unpack_from("<I", blob, F_SECOND_SIZE)[0]
        self.dtb_size = (struct.unpack_from("<I", blob, F_DTB_SIZE)[0]
                         if self.version >= 2 else 0)
        self._locate()

    def _round(self, n):
        return (n + self.page - 1) // self.page * self.page

    def _locate(self):
        # mkbootimg writes header, then each blob padded up to the page size,
        # in this order: kernel, ramdisk, second, then dtb (v2+).
        off = self.header_size
        self.kernel_off = off
        off += self._round(self.kernel_size)
        self.ramdisk_off = off
        off += self._round(self.ramdisk_size)
        self.second_off = off
        off += self._round(self.second_size)
        self.dtb_off = off
        off += self._round(self.dtb_size)
        self.end = off

    def slots(self):
        return {
            "kernel": (self.kernel_off, self.kernel_size),
            "ramdisk": (self.ramdisk_off, self.ramdisk_size),
            "second": (self.second_off, self.second_size),
            "dtb": (self.dtb_off, self.dtb_size),
        }

    def blob_at(self, name):
        off, size = self.slots()[name]
        return self.blob[off:off + size]

    def describe(self, out=sys.stdout):
        def line(label, off, size):
            out.write("  %-8s off=%-12d size=%-12d (%d pages)\n"
                      % (label, off, size, self._round(size) // self.page))
        out.write("boot.img header version %d, page %d\n" % (self.version, self.page))
        line("kernel", self.kernel_off, self.kernel_size)
        line("ramdisk", self.ramdisk_off, self.ramdisk_size)
        line("second", self.second_off, self.second_size)
        line("dtb", self.dtb_off, self.dtb_size)
        out.write("  total  = %d bytes\n" % self.end)

    def repack(self, payload, slot="ramdisk"):
        kernel = self.blob_at("kernel")
        ramdisk = self.blob_at("ramdisk")
        second = self.blob_at("second")
        dtb = self.blob_at("dtb")
        if slot == "ramdisk":
            ramdisk = payload
        elif slot == "second":
            second = payload
        else:
            raise ValueError("slot must be ramdisk or second")

        hdr = bytearray(self.blob[:self.header_size])
        # The digest the original packer left in id[] is carried over untouched.
        # It could not be reproduced: only the first 20 bytes are ever set (one
        # SHA-1, not the four AOSP writes), none of the obvious 70-odd
        # algorithm/order/size-prefix combinations match it, and two images
        # sharing an identical kernel carry different digests -- so it covers
        # the payload too, yet no variant of it lines up. Nothing on this boot
        # path checks it (the stock ABL happily boots these), and keeping the
        # original bytes is what makes the round trip above byte-exact, which is
        # the property worth having. Leave it alone.
        struct.pack_into("<I", hdr, F_KERNEL_SIZE, len(kernel))
        struct.pack_into("<I", hdr, F_RAMDISK_SIZE, len(ramdisk))
        struct.pack_into("<I", hdr, F_SECOND_SIZE, len(second))
        if self.version >= 2:
            struct.pack_into("<I", hdr, F_DTB_SIZE, len(dtb))

        body = bytearray()
        for data in (kernel, ramdisk, second, dtb):
            body.extend(data)
            if self._round(len(data)) > len(data):
                body.extend(b"\0" * (self._round(len(data)) - len(data)))
        return bytes(hdr) + bytes(body)


def can_rebuild_exactly(img):
    """True if repacking with the payload it already carries is byte-identical."""
    rebuilt = img.repack(img.blob_at("ramdisk"), slot="ramdisk")
    if len(rebuilt) == len(img.blob) and rebuilt == img.blob:
        return True
    rebuilt = img.repack(img.blob_at("second"), slot="second")
    return rebuilt == img.blob


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("payload", nargs="?", help="new XNU payload to splice in")
    ap.add_argument("-o", "--output")
    ap.add_argument("--slot", choices=("ramdisk", "second"), default="ramdisk")
    ap.add_argument("--selftest", action="store_true",
                    help="round trip check and exit")
    args = ap.parse_args()

    with open(args.image, "rb") as fh:
        raw = fh.read()
    img = BootImage(raw)
    img.describe()

    if not can_rebuild_exactly(img):
        print("\nFAIL: repacking the existing payload does not reproduce this "
              "image byte for byte. Either the header layout here does not "
              "match this image or the padding is not what mkbootimg wrote. "
              "Refusing to produce something you would flash.",
              file=sys.stderr)
        return 1
    print("self-check: round trip is byte-identical")

    if args.selftest:
        return 0

    if not args.payload or not args.output:
        print("both a payload and -o are required unless --selftest")
        return 2

    with open(args.payload, "rb") as fh:
        payload = fh.read()

    out = img.repack(payload, slot=args.slot)
    check = BootImage(out)
    ok = (check.blob_at("kernel") == img.blob_at("kernel")
          and check.blob_at("dtb") == img.blob_at("dtb")
          and check.blob_at("second") == img.blob_at("second")
          and check.blob_at(args.slot) == payload)
    if not ok:
        print("FAIL: verification of the produced image failed", file=sys.stderr)
        return 1

    with open(args.output, "wb") as fh:
        fh.write(out)
    print("wrote %s (%d bytes); kernel and dtb unchanged, %s replaced with %d bytes"
          % (args.output, len(out), args.slot, len(payload)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
