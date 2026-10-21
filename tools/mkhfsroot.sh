#!/bin/bash
# Build a raw HFS+ root image on macOS, ready for `fastboot flash userdata`.
#
#   mkhfsroot.sh OUT_RAW_IMG SIZE_MB [INIT]
#
# Why this runs on a macOS runner instead of the Linux box: writing HFS+ needs
# an HFS+ writer, and Linux here has none. hfsfuse is read-only by design, the
# NAS (FeiNiu, 6.18.18-trim) ships no hfsplus kernel module, and mkfs.hfsplus
# only produces an empty volume. macOS has newfs_hfs - the implementation the
# XNU hfs kext was written against - so the result is the shape the kernel
# expects, and we do not have to write a catalog B-tree ourselves.
#
# The image is a bare CRawDiskImage with HFS+ at offset 0: no UDIF trailer, no
# partition map, exactly what fastboot writes to the partition. Detaching is
# what syncs the catalog back into the file, so it is not optional.
set -eu

out=${1:?usage: mkhfsroot.sh OUT_RAW_IMG SIZE_MB [INIT]}
size_mb=${2:?usage: mkhfsroot.sh OUT_RAW_IMG SIZE_MB [INIT]}
init=$3

label=${LABEL:-SweetRoot}
journal=${JOURNAL:-1}          # 1 = journaled, like a real iOS root

rm -f "$out"
echo "allocating ${size_mb} MB"
mkfile -n "${size_mb}m" "$out"
abs=$(cd "$(dirname "$out")" && pwd)/$(basename "$out")

echo "attaching as a raw disk image"
dev=$(hdiutil attach -nomount -imagekey diskimage-class=CRawDiskImage "$abs")
dev=$(printf '%s' "$dev" | awk 'NF{print $1}')
echo "  device $dev"

jflag=""
[[ $journal == 1 ]] && jflag="-J"
# newfs_hfs on the whole disk: the image intentionally carries no partition
# map, so the volume header belongs at block 0.
sudo newfs_hfs $jflag -v "$label" "$dev"

mp=$(mktemp -d)
trap 'sudo umount "$mp" 2>/dev/null || true; hdiutil detach "$dev" 2>/dev/null || true; rmdir "$mp" 2>/dev/null || true' EXIT

# Attaching a partition-map-less image usually gives only the whole-disk node,
# but macOS sometimes synthesises a slice: mount whichever one exists.
mounted=""
for cand in "$dev" "${dev}s1"; do
	if [[ -b $cand ]] && sudo mount_hfs "$cand" "$mp" 2>/dev/null; then
		mounted=$cand
		break
	fi
done
[[ -z $mounted ]] && { echo "could not mount $dev" >&2; exit 1; }
echo "  mounted $mounted"

if [[ -n $init ]]; then
	echo "installing /sbin/launchd"
	sudo mkdir -p "$mp/sbin"
	sudo install -m 0755 -o 0 -g 0 "$init" "$mp/sbin/launchd"
fi

# devfs mounts over /dev and the kernel wants /private/var before anything in
# userspace asks for it.
sudo mkdir -p "$mp/dev" "$mp/private/var"
sudo chown 0:0 "$mp/dev" "$mp/private/var"

echo "--- contents ---"
sudo find "$mp" -mindepth 1 -maxdepth 3 | sort
sudo ls -l "$mp/sbin/launchd" 2>/dev/null || true

sudo umount "$mp"
hdiutil detach "$dev"

echo "--- volume header (offset 1024) ---"
xxd -l 16 -s 1024 "$out"
ls -l "$out"
