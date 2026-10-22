#!/usr/bin/env python3
"""Turn a raw disk image into an Android sparse image.

    img2simg.py IN.raw OUT.simg [BLOCKSIZE]

The phone's bootloader refuses a download larger than max-download-size (768 MiB
on this board), and a 12 GB root image is two orders of magnitude past that.
fastboot will however accept a sparse image and write it in -S sized chunks, so
this is what makes a multi-gigabyte image flashable at all.

The format is libsparse's: a little-endian 28 byte file header, then chunks of
one of four types. Blocks that are entirely zero become DONT_CARE (written as
nothing at the device), which is where most of the saving on a freshly
formatted volume comes from.
"""
import struct
import sys

MAGIC = 0xED26FF3A
CHUNK_RAW = 0xCAC1
CHUNK_FILL = 0xCAC2
CHUNK_DONT_CARE = 0xCAC3
CHUNK_CRC32 = 0xCAC4

FILE_HDR_SZ = 28
CHUNK_HDR_SZ = 12
BLK = 4096


def chunks(fin, size, blk):
    """Yield (chunk_type, block_count, payload) covering the whole image."""
    pos = 0
    while pos < size:
        data = fin.read(blk)
        if not data:
            break
        if len(data) < blk:  # final partial block, pad it out
            data += b"\0" * (blk - len(data))
        if data.count(0) == blk:
            # Absorb the whole run of zero blocks into one DONT_CARE chunk.
            n = 1
            while pos + n * blk < size:
                nxt = fin.read(blk)
                if len(nxt) < blk:
                    nxt += b"\0" * (blk - len(nxt))
                if nxt.count(0) != blk:
                    fin.seek(-len(nxt), 1)
                    break
                n += 1
            yield CHUNK_DONT_CARE, n, b""
            pos += n * blk
            continue
        # Absorb contiguous non-zero blocks into as few RAW chunks as we can,
        # capped so a single chunk stays well under fastboot's download limit.
        n = 1
        buf = bytearray(data)
        while pos + n * blk < size and n * blk < 64 * 1024 * 1024:
            nxt = fin.read(blk)
            if len(nxt) < blk:
                nxt += b"\0" * (blk - len(nxt))
            if nxt.count(0) == blk:
                fin.seek(-len(nxt), 1)
                break
            buf += nxt
            n += 1
        yield CHUNK_RAW, n, bytes(buf)
        pos += n * blk


def main(argv):
    if not 3 <= len(argv) <= 4:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: img2simg.py IN.raw OUT.simg [BLOCKSIZE]", file=sys.stderr)
        return 2
    blk = int(argv[3]) if len(argv) == 4 else BLK
    size = __import__("os").path.getsize(argv[1])

    # Two passes: the header has to state the chunk count before we write any.
    with open(argv[1], "rb") as fin:
        plan = list(chunks(fin, size, blk))
    total_blks = (size + blk - 1) // blk
    with open(argv[2], "wb") as out:
        out.write(struct.pack("<I4H4I", MAGIC, 1, 0, FILE_HDR_SZ, CHUNK_HDR_SZ,
                              blk, total_blks, len(plan), 0))
        written = 0
        with open(argv[1], "rb") as fin:
            for ctype, nblocks, payload in plan:
                total_sz = CHUNK_HDR_SZ + len(payload)
                out.write(struct.pack("<2H2I", ctype, 0, nblocks, total_sz))
                if payload:
                    out.write(payload)
                written += nblocks
        assert written == total_blks, (written, total_blks)
    raw_bytes = __import__("os").path.getsize(argv[2])
    print("%s -> %s  raw %d -> sparse %d (%.1f%%)" %
          (argv[1], argv[2], size, raw_bytes, 100.0 * raw_bytes / size))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
