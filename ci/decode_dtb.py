#!/usr/bin/env python3
"""Extract every flattened device tree out of a boot image or dtbo/dtbs partition
and pick the one that describes this board.

    pip install pyfdt
    python3 ci/decode_dtb.py --boot /path/to/boot.img --outdir dtb_out \
        --match polaris

The kernel never reads these blobs directly; their only job here is to tell us
real hardware numbers (framebuffer address, panel size, UFS aperture, GIC base)
so tools/mkadt.py can build the matching AppleDeviceTree.
"""

import argparse
import os
import struct

MAGIC = 0xD00DFEED


def blobs(data):
    out, i = [], 0
    packed = struct.pack(">I", MAGIC)
    while True:
        off = data.find(packed, i)
        if off < 0:
            break
        (totalsize,) = struct.unpack_from(">I", data, off + 4)
        if totalsize <= 8 or off + totalsize > len(data):
            i = off + 4
            continue
        out.append((off, data[off:off + totalsize]))
        i = off + 4
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", "--dtb", dest="boot", required=True,
                    help="boot.img, dtbo.img or a raw concatenated dtb blob")
    ap.add_argument("--outdir", default="dtb_out")
    ap.add_argument("--match", default="polaris",
                    help="model substring that identifies the right tree")
    args = ap.parse_args()

    try:
        from pyfdt import pyfdt
    except ImportError:
        raise SystemExit("pip install pyfdt")

    os.makedirs(args.outdir, exist_ok=True)
    data = open(args.boot, "rb").read()
    found = blobs(data)
    print("found %d DTB blob(s)" % len(found))

    hits = []
    for idx, (off, blob) in enumerate(sorted(found, key=lambda b: -len(b[1]))):
        path = os.path.join(args.outdir, "dtb_%02d.dtb" % idx)
        open(path, "wb").write(blob)
        print("  dtb_%02d off=0x%x size=%d -> %s" % (idx, off, len(blob), path))
        try:
            dts = pyfdt.Fdt(blob).to_dts()
            if isinstance(dts, bytes):
                dts = dts.decode("utf-8", "replace")
        except Exception as e:
            print("     (undecodable: %s)" % e)
            continue
        open(path[:-4] + ".dts", "w").write(dts)
        if args.match and args.match.lower() in dts.lower():
            hits.append((idx, path))
            print("     MATCH: contains %r -> %s" % (args.match, path))

    if not hits:
        print("\nno blob mentioned %r - pass --match with another substring" % args.match)
    else:
        print("\nmatched %d blob(s): %s" % (len(hits), " ".join(p for _, p in hits)))


if __name__ == "__main__":
    main()
