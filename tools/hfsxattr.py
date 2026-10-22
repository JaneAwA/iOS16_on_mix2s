#!/usr/bin/env python3
"""Read an HFS+ volume directly and report its extended attributes.

Why this exists: the "is the image clean?" question has to be answered by
looking at the FILESYSTEM, not by looking for bytes in the image. A byte
scan finds the attribute NAMES in the B-tree's free space as well as in
live records, so it cannot tell a volume whose files are still marked
compressed from one whose records were merely freed.

The structures below were established by reading the actual bytes of the
volumes this project produces, not from memory of the format.

Volume header (HFSPlusVolumeHeader, at offset 1024 of a disk image --
after the 512-byte partition table and the 512-byte alternate descriptor):

    0x00  signature "H+" (HFS+) or "HX" (HFSX, case sensitive)
    0x28  UInt32 blockSize
    0x2C  UInt32 totalBlocks
    0x70  HFSPlusForkData allocationFile
    0xC0  HFSPlusForkData extentsFile
    0x110 HFSPlusForkData catalogFile
    0x160 HFSPlusForkData attributesFile
    0x1B0 HFSPlusForkData startupFile

HFSPlusForkData (80 bytes):

    0x00  UInt64 logicalSize
    0x08  UInt32 clumpSize
    0x0C  UInt32 totalBlocks
    0x10  8 x { UInt32 startBlock; UInt32 blockCount }

B-tree node (nodeSize bytes; the node descriptor is at the START, the
record offset array is at the END):

    0x00  UInt32 fLink            next sibling node
    0x04  UInt32 bLink            previous sibling node
    0x08  Int8  kind              1 = header, 0 = index, -1 = leaf
    0x09  UInt8 height
    0x0A  UInt16 numRecords
    0x0C  UInt16 reserved
    ...   record offsets, UInt16 each, at the END of the node:
          offset[i] = be16(node, nodeSize - 2*(i+1)), so offset[0] is the
          LOWEST record offset and offset[0] is the first record in key
          order. The 2 bytes just below the array are the free-space
          offset and must not be read as a record offset.

B-tree header record (record 0 of the header node):

    0x00  UInt16 treeDepth
    0x02  UInt32 rootNode
    0x06  UInt32 leafRecords
    0x0A  UInt32 firstLeafNode
    0x0E  UInt32 lastLeafNode
    0x12  UInt16 nodeSize
    0x14  UInt16 maxKeyLength
    0x16  UInt32 totalNodes
    0x1A  UInt32 freeNodes

Catalog B-tree leaf record:

    key    HFSPlusCatalogKey
           0x00 UInt16 keyLength   6 + 2*nameLength
           0x02 UInt32 parentID
           0x06 UInt16 nameLength   in UTF-16 code units
           0x08 UniChar255 nodeName
    data   0x00 UInt16 recordType: 1 = folder, 2 = file, 3 = thread
           for a file record, the BSD info's "special" field sits at
           data offset 40 and carries the UF_* attribute bits; bit 0x20
           is UF_COMPRESSED.

Attributes B-tree leaf record:

    key    HFSPlusAttrKey
           0x00 UInt16 keyLength   12 + 2*attrNameLength
           0x02 UInt16 pad
           0x04 UInt32 primaryID
           0x08 UInt32 secondaryID
           0x0C UInt16 attrNameLength
           0x0E UniChar255 attrName
    data   0x00 UInt16 recordType: 4 = attribute data, 5 = attribute extents

keyLength does not count its own two bytes in either tree, which is why
the two formulas differ by the extra pad/primaryID/secondaryID words.

A file that still carries com.apple.decmpfs is exactly what makes XNU take
the compressed read path and return EOPNOTSUPP(45), so the answer has to
be "no live record", not "no bytes".

Usage:
    python3 hfsxattr.py RAW_IMAGE [--json]
"""
import json
import struct
import sys

# Catalog record types.
kHFSPlusCatalogFolder = 0x0001
kHFSPlusCatalogFile = 0x0002
kHFSPlusCatalogThread = 0x0003

# Attributes-file record types.
kHFSPlusAttrData = 0x0004
kHFSPlusAttrExtents = 0x0005

# UF_COMPRESSED, in the catalog file record's BSD-info special field.
UF_COMPRESSED = 0x20

# Volume header offsets of the five forks.
FORK_OFFSETS = {
    "allocation": 0x70,
    "extents": 0xC0,
    "catalog": 0x110,
    "attributes": 0x160,
    "startup": 0x1B0,
}


class Extent:
    __slots__ = ("startBlock", "blockCount")

    def __init__(self, startBlock, blockCount):
        self.startBlock = startBlock
        self.blockCount = blockCount


class Fork:
    __slots__ = ("logicalSize", "clumpSize", "totalBlocks", "extents")

    def __init__(self, logicalSize, clumpSize, totalBlocks, extents):
        self.logicalSize = logicalSize
        self.clumpSize = clumpSize
        self.totalBlocks = totalBlocks
        self.extents = extents


def be16(b, off):
    return struct.unpack_from(">H", b, off)[0]


def be32(b, off):
    return struct.unpack_from(">I", b, off)[0]


SPARSE_MAGIC = 0xED26FF3A


class SparseFile:
    """Read-only view of an Android sparse image.

    The CI ships a sparse image (fastboot only accepts sparse), so the
    HFS+ volume inside it is not at a fixed file offset: the chunk table
    has to be consulted for every read. A raw image is handled by the same
    interface with a single trivial mapping.

    Chunk types: 0xCAC1 raw, 0xCAC2 fill, 0xCAC3 don't-care, 0xCAC4 CRC.
    Only RAW chunks carry file data; FILL repeats a 4-byte pattern and
    DONT_CARE reads as zeros.
    """

    RAW = 0xCAC1
    FILL = 0xCAC2
    DONT_CARE = 0xCAC3
    CRC32 = 0xCAC4

    def __init__(self, path):
        self.path = path
        self.fh = open(path, "rb")
        head = self.fh.read(28)
        magic = struct.unpack_from("<I", head, 0)[0]
        if magic != SPARSE_MAGIC:
            self.fh.seek(0)
            self.chunks = None
            return
        # sparse_header (libsparse, 28 bytes):
        #   UInt32 magic; UInt16 major; UInt16 minor; UInt16 file_hdr_sz;
        #   UInt16 chunk_hdr_sz; UInt32 blk_sz; UInt32 total_blks;
        #   UInt32 total_chunks; UInt32 image_sz;
        (_magic2, _major, _minor, file_hdr_sz, chunk_hdr_sz, blk_sz,
         total_blks, total_chunks, _img_sz) = struct.unpack_from(
            "<I4H4I", head, 0)
        self.chunk_sz = blk_sz
        self.dataStart = file_hdr_sz
        self.chunks = []
        for _ in range(total_chunks):
            chunk_start = self.fh.tell()
            ctype, _res, nblocks, total_sz = struct.unpack(
                "<2H2I", self.fh.read(12))
            # [file offset of the chunk, type, block count, payload length]
            self.chunks.append([chunk_start, ctype, nblocks,
                                max(0, total_sz - 12)])
            # The payload follows the chunk header; skip it to reach the
            # next chunk header.
            self.fh.seek(self.fh.tell() + max(0, total_sz - 12))
        total = total_blks * blk_sz
        logical = 0
        for c in self.chunks:
            c.append(logical)
            logical += c[2] * blk_sz
        self.total = total

    def read(self, offset, length):
        if self.chunks is None:
            self.fh.seek(offset)
            return self.fh.read(length)
        out = bytearray()
        end = offset + length
        for (chunk_start, ctype, nblocks, payload_len, logical) in self.chunks:
            if len(out) >= length:
                break
            chunk_len = nblocks * self.chunk_sz
            chunk_end = logical + chunk_len
            if chunk_end <= offset or logical >= end:
                continue
            want_from = max(offset, logical) - logical
            want_to = min(end, chunk_end) - logical
            n = want_to - want_from
            if n <= 0:
                continue
            # The payload starts right after the 12-byte chunk header.
            payload_off = chunk_start + 12 + want_from
            if ctype == self.RAW:
                self.fh.seek(payload_off)
                out += self.fh.read(n)
            elif ctype == self.FILL:
                self.fh.seek(chunk_start + 12)
                pat = self.fh.read(4)
                out += (pat * (n // 4 + 1))[:n]
            else:
                out += b"\x00" * n
        return bytes(out)


def read_fork(b, off):
    """Parse an HFSPlusForkData at off."""
    logicalSize = struct.unpack_from(">Q", b, off)[0]
    clumpSize = be32(b, off + 8)
    totalBlocks = be32(b, off + 12)
    extents = []
    for i in range(8):
        eo = off + 16 + i * 8
        startBlock = be32(b, eo)
        blockCount = be32(b, eo + 4)
        if blockCount:
            extents.append(Extent(startBlock, blockCount))
    return Fork(logicalSize, clumpSize, totalBlocks, extents)


def read_volume_header(img, base=1024):
    # The HFS+ volume starts after the 512-byte partition table plus the
    # 512-byte secondary descriptor, i.e. at offset 1024 of the disk image.
    vh = img.read(base, 512)
    sig = vh[0:2]
    # "H+" is plain HFS+; "HX" is HFSX, the case-sensitive variant that
    # newfs_hfs -s produces (the volume has to be case sensitive: the iOS
    # filesystem is).
    if sig not in (b"H+", b"HX"):
        raise SystemExit("no HFS+ volume header at offset %d (signature %r)"
                         % (base, sig))
    blockSize = be32(vh, 0x28)
    totalBlocks = be32(vh, 0x2C)
    forks = {}
    for name, off in FORK_OFFSETS.items():
        forks[name] = read_fork(vh, off)
    return {"blockSize": blockSize, "totalBlocks": totalBlocks,
            "forks": forks, "raw": vh}


def fork_bytes(img, fork, vol_base=0, blockSize=None):
    """Read a fork's bytes by following its extents.

    vol_base is the offset of the volume inside the image. The volume
    header sits at offset 1024 of the disk image (the 512-byte partition
    table plus the 512-byte secondary descriptor), but the volume's own
    block 0 is at offset 0 -- the first 1024 bytes are the reserved boot
    blocks. So the extents are relative to offset 0.

    blockSize is the VOLUME's block size, not the fork's clump size: the
    extent descriptors are counted in volume blocks.
    """
    if blockSize is None:
        raise ValueError("fork_bytes needs the volume block size")
    out = bytearray()
    for ext in fork.extents:
        out += img.read(vol_base + ext.startBlock * blockSize,
                        ext.blockCount * blockSize)
    return bytes(out[:fork.logicalSize])


def btree_header(data, nodeSize):
    """Decode the B-tree header record (record 0 of the header node)."""
    numRecords = be16(data, 10)
    if numRecords < 1:
        return None
    off = be16(data, nodeSize - 2)
    h = data[off:off + 0x1E]
    if len(h) < 0x1E:
        return None
    (treeDepth, rootNode, leafRecords, firstLeafNode, lastLeafNode,
     hNodeSize, maxKeyLength, totalNodes, freeNodes) = struct.unpack_from(
        ">HIIIIHHII", h, 0)
    return {"treeDepth": treeDepth, "rootNode": rootNode,
            "leafRecords": leafRecords, "firstLeafNode": firstLeafNode,
            "lastLeafNode": lastLeafNode, "nodeSize": hNodeSize,
            "maxKeyLength": maxKeyLength, "totalNodes": totalNodes,
            "freeNodes": freeNodes}


def leaf_nodes(data, nodeSize, firstLeaf):
    """Yield the bytes of every leaf node, following the fLink chain."""
    node = firstLeaf
    seen = 0
    while node:
        chunk = data[node * nodeSize:(node + 1) * nodeSize]
        if len(chunk) < nodeSize:
            return
        yield chunk
        fLink = be32(chunk, 0)
        if fLink == node:
            return
        node = fLink
        seen += 1
        if seen > 500000:
            return


def node_record_offsets(node, nodeSize, numRecords):
    """Record offsets live at the END of the node, in decreasing address."""
    return [be16(node, nodeSize - 2 * (i + 1)) for i in range(numRecords)]


def _readable(name):
    return bool(name) and all(c.isprintable() for c in name)


def scan_catalog(data, nodeSize, firstLeaf):
    """Yield (recordType, parentID, name, special) for live records."""
    for node in leaf_nodes(data, nodeSize, firstLeaf):
        kind = struct.unpack_from(">b", node, 8)[0]
        if kind != -1:
            continue
        numRecords = be16(node, 10)
        offs = node_record_offsets(node, nodeSize, numRecords)
        for i, o in enumerate(offs):
            if o + 10 > nodeSize:
                continue
            klen = be16(node, o)
            nameLen = be16(node, o + 6)
            if not (1 <= nameLen <= 255) or klen != 6 + 2 * nameLen:
                continue
            end = o + 8 + nameLen * 2
            if end + 2 > nodeSize:
                continue
            name = node[o + 8:end].decode("utf-16-be", "replace")
            if not _readable(name):
                continue
            recordType = be16(node, end)
            special = None
            if recordType == kHFSPlusCatalogFile and end + 42 <= nodeSize:
                # The BSD info's "special" field carries the UF_* bits.
                special = be16(node, end + 40)
            yield recordType, be32(node, o + 2), name, special


def scan_attributes(data, nodeSize, firstLeaf):
    """Yield (recordType, primaryID, attrName) for every live xattr."""
    for node in leaf_nodes(data, nodeSize, firstLeaf):
        kind = struct.unpack_from(">b", node, 8)[0]
        if kind != -1:
            continue
        numRecords = be16(node, 10)
        offs = node_record_offsets(node, nodeSize, numRecords)
        for o in offs:
            if o + 14 > nodeSize:
                continue
            klen = be16(node, o)
            nameLen = be16(node, o + 12)
            if not (1 <= nameLen <= 255) or klen != 12 + 2 * nameLen:
                continue
            end = o + 14 + nameLen * 2
            if end + 2 > nodeSize:
                continue
            name = node[o + 14:end].decode("utf-16-be", "replace")
            if not _readable(name):
                continue
            yield be16(node, end), be32(node, o + 4), name


def scan_volume(img):
    vol = read_volume_header(img)
    bs = vol["blockSize"]
    out = {"blockSize": bs, "totalBlocks": vol["totalBlocks"],
           "catalogRecords": 0, "fileRecords": 0, "folderRecords": 0,
           "compressedFiles": 0, "compressedSample": [],
           "attributes": {}, "decmpfs": [], "otherAttrs": []}

    cat_fork = vol["forks"]["catalog"]
    if cat_fork.logicalSize:
        cat = fork_bytes(img, cat_fork, blockSize=bs)
        nodeSize = 8192
        hdr = btree_header(cat, nodeSize)
        if hdr and hdr["nodeSize"]:
            nodeSize = hdr["nodeSize"]
        out["catalogNodeSize"] = nodeSize
        out["catalogTotalNodes"] = hdr["totalNodes"] if hdr else None
        out["catalogLeafRecords"] = hdr["leafRecords"] if hdr else None
        for (rtype, _pid, name, special) in scan_catalog(
                cat, nodeSize, hdr["firstLeafNode"] if hdr else 0):
            out["catalogRecords"] += 1
            if rtype == kHFSPlusCatalogFile:
                out["fileRecords"] += 1
                if special is not None and special & UF_COMPRESSED:
                    out["compressedFiles"] += 1
                    if len(out["compressedSample"]) < 20:
                        out["compressedSample"].append(name)
            elif rtype == kHFSPlusCatalogFolder:
                out["folderRecords"] += 1

    attr_fork = vol["forks"]["attributes"]
    if attr_fork.logicalSize:
        attr = fork_bytes(img, attr_fork, blockSize=bs)
        nodeSize = 8192
        hdr = btree_header(attr, nodeSize)
        if hdr and hdr["nodeSize"]:
            nodeSize = hdr["nodeSize"]
        out["attrNodeSize"] = nodeSize
        out["attrTotalNodes"] = hdr["totalNodes"] if hdr else None
        out["attrLeafRecords"] = hdr["leafRecords"] if hdr else None
        for (rtype, _pid, name) in scan_attributes(
                attr, nodeSize, hdr["firstLeafNode"] if hdr else 0):
            out["attributes"].setdefault(name, 0)
            out["attributes"][name] += 1
            if name in ("com.apple.decmpfs", "decmpfs"):
                out["decmpfs"].append(rtype)
            elif name != "com.apple.ResourceFork":
                out["otherAttrs"].append(name)
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit(__doc__)
    path = args[0]
    img = SparseFile(path)
    r = scan_volume(img)

    decmpfs = r["decmpfs"]
    names = sorted(r["attributes"].keys())
    result = {
        "path": path,
        "catalogRecords": r["catalogRecords"],
        "fileRecords": r["fileRecords"],
        "folderRecords": r["folderRecords"],
        "compressedFiles": r["compressedFiles"],
        "attributeNames": names,
        "decmpfsCount": len(decmpfs),
    }
    if "--json" in sys.argv:
        print(json.dumps(result, indent=2))
    else:
        print("catalog B-tree: %d live records (%d files, %d folders); "
              "nodeSize=%s totalNodes=%s leafRecords=%s"
              % (r["catalogRecords"], r["fileRecords"], r["folderRecords"],
                 r.get("catalogNodeSize"), r.get("catalogTotalNodes"),
                 r.get("catalogLeafRecords")))
        print("files flagged UF_COMPRESSED: %d"
              % r["compressedFiles"])
        for n in r["compressedSample"]:
            print("    compressed: %s" % n)
        print("attributes B-tree: %d distinct names, %d live records"
              % (len(names), sum(r["attributes"].values())))
        for n in names:
            print("    %-40s x%d" % (n, r["attributes"][n]))
        print("live decmpfs attribute records: %d" % len(decmpfs))
    if decmpfs:
        print("VERDICT: DIRTY -- live decmpfs attribute records exist")
        return 1
    print("VERDICT: CLEAN -- no live decmpfs attribute records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
