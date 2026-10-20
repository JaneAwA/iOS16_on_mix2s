#!/usr/bin/env python3
"""Build the minimal Apple Device Tree that the xnu needs to boot.

Only what the early boot path actually reads (see NOTES.md); every MMIO
address comes from the device's live FDT. Usage:
  mkadt.py OUT.adt [--sweet|--polaris] [--dump] [--qemu] [--highmem]

Machines:
  sweet   - Redmi Note 10 Pro (SM7150 / Snapdragon 732G), 1080x2400 panel
  polaris - Xiaomi Mi Mix 2S (SDM845 / Snapdragon 845), 1080x2160 AMOLED
            (decoded from the stock boot.img DTB: GIC @0x17a00000/0x17a60000,
             UFS @0x1d84000, cont_splash framebuffer @0x9d400000, 19.2MHz timer)
Default is polaris (our port target); pass --sweet to reproduce the original tree.
"""
import hashlib, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402

# ---- shared (both machines) -------------------------------------------------
# Kernel-managed RAM: above every Qualcomm XPU carve-out (see NOTES.md).
# For SDM845 the reserved-memory carve-outs span 0x85700000..0x9f800000, so
# 0xb0000000 sits safely above them (verified against the polaris DTB).
PHYS_BASE = 0xb0000000
MEM_SIZE = 0x4d000000
# --highmem (phone only): the whole upper DDR bank.
HIGH_PHYS_BASE = 0x100000000
HIGH_MEM_SIZE = 0xfcc00000
# /arm-io children are relative to this; it must not be 0 (serial_init bails)
SOC_BASE = 0x01000000

# QEMU virt (-M virt,gic-version=3 -cpu cortex-a76): GICD/GICR and the generic
# timer's CNTFRQ. Identical for both machines (just a dev harness).
QEMU_GICD, QEMU_GICR, QEMU_TIMEBASE = 0x08000000, 0x080a0000, 62500000
QEMU_VTIMER_INTID = 27

SWEET_ECID = 0x5357454554000001  # 'SWEET' + 1, synthetic
BOOT_MANIFEST_HASH = hashlib.sha384(b'sweet boot manifest').digest()

# The iOS userland is the iPhone X (iPhone10,3 / D22AP) IPSW. MobileGestalt
# derives product type, device class, home-button-less UI, artwork etc. from
# the root identity and /product of the real D22AP device tree. That tree is
# an Apple artifact (kept out of git): extract it from the IPSW with
#   tools/remotezip.py URL DeviceTree.d22ap.im4p DIR
#   ipsw img4 im4p extract DIR/Firmware/all_flash/DeviceTree.d22ap.im4p -o d22ap.adt
D22AP_ADT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../research/ipsw-x/d22ap.adt')

# Per-machine MMIO + panel map. Everything else (chosen/cpu/buttons/defaults)
# is identical between them.
MACHINES = {
    'sweet': dict(
        gicd=0x17a00000, gicd_size=0x10000, gicr=0x17a60000, gicr_size=0x100000,
        fb=0x9c000000, fb_size=0x1700000, fb_w=1080, fb_h=2400, fb_stride=1080 * 4,
        ufs=0x01d84000, ufs_size=0x3000,
        timebase=19200000, vtimer_intid=19,
        canvas_w=1125, canvas_h=2436,
        compatible=b'D22AP' + b'iPhone10,3' + b'xiaomi,sweet' + b'qcom,sm7150' + b'AppleARM',
        model=b'iPhone10,3', target_type=b'D22', target_sub=b'D22AP',
        io_devtype=b'sweet-io', io_compat=b'sweet-io',
        cpu_compat=b'qcom,kryo470' + b'ARM,v8',
        big_clk=2304000000, little_clk=1804800000, big_first=False,
    ),
    'polaris': dict(
        # All decoded from the Mix 2S (polaris) retail DTB, dtb_36 (Polaris MP v2.1):
        gicd=0x17a00000, gicd_size=0x10000, gicr=0x17a60000, gicr_size=0x100000,
        fb=0x9d400000, fb_size=0x2400000, fb_w=1080, fb_h=2160, fb_stride=1080 * 4,
        ufs=0x01d84000, ufs_size=0x2500,
        timebase=19200000, vtimer_intid=19,
        canvas_w=1080, canvas_h=2160,
        compatible=b'D22AP' + b'iPhone10,3' + b'xiaomi,polaris' + b'qcom,sdm845' + b'AppleARM',
        model=b'iPhone10,3', target_type=b'D22', target_sub=b'D22AP',
        io_devtype=b'polaris-io', io_compat=b'polaris-io',
        cpu_compat=b'qcom,kryo385' + b'ARM,v8',
        # SDM845: cluster 0 = Kryo 385 Gold (Cortex-A75, 2.8GHz, cores 0-3),
        # cluster 1 = Kryo 385 Silver (Cortex-A55, 1.8GHz, cores 4-7). The DTB
        # cpu@0..cpu@300 have reg <0x0>..<0x300> => big-first (cores 0-3 big).
        big_clk=2803200000, little_clk=1804800000, big_first=True,
    ),
}


def d22ap_product(path=D22AP_ADT):
    """/product properties of the real D22AP tree, without the syscfg
    placeholders iBoot would fill in (flag bit set) and the node bookkeeping."""
    if not os.path.exists(path):
        print(f'warning: {path} missing, no /product node', file=sys.stderr)
        return None
    root, _ = adt.parse(open(path, 'rb').read())
    for c in root.children:
        if dict((k, v) for k, f, v in c.props).get('name') == b'product\0':
            return [(k, v) for k, f, v in c.props if not f and k not in ('name', 'AAPL,phandle')]
    raise SystemExit(f'{path}: no /product node')


u32 = lambda *v: struct.pack('<%dI' % len(v), *v)
u64 = lambda *v: struct.pack('<%dQ' % len(v), *v)
cstr = lambda s: s.encode() + b'\0'


def node(name, props=(), children=()):
    n = adt.Node()
    n.props = [('name', 0, cstr(name))] + [(k, 0, v) for k, v in props]
    n.children = list(children)
    return n


def build(machine='polaris', qemu=False, highmem=False):
    """Build the ADT for `machine`. qemu=True swaps in QEMU virt's GIC/timer."""
    m = MACHINES[machine]
    phys_base, mem_size = (HIGH_PHYS_BASE, HIGH_MEM_SIZE) if highmem else (PHYS_BASE, MEM_SIZE)
    gicd, gicr, timebase = (QEMU_GICD, QEMU_GICR, QEMU_TIMEBASE) if qemu else (m['gicd'], m['gicr'], m['timebase'])
    vtimer = QEMU_VTIMER_INTID if qemu else m['vtimer_intid']
    seed = os.urandom(64)
    phandle = iter(range(1, 1000))
    ph = lambda: ('AAPL,phandle', u32(next(phandle)))

    chosen = node('chosen', [
        ph(),
        ('dram-base', u64(phys_base)),
        ('dram-size', u64(mem_size)),
        ('random-seed', seed),
        ('debug-enabled', u32(1)),
        ('firmware-version', cstr('polaris-shim' if machine == 'polaris' else 'sweet-shim')),
        ('system-firmware-version', cstr('polaris-shim' if machine == 'polaris' else 'sweet-shim')),
        ('boot-manifest-hash', BOOT_MANIFEST_HASH),
        ('crypto-hash-method', cstr('sha2-384')),
        ('display-scale', u32(3)),
        ('unique-chip-id', struct.pack('<Q', SWEET_ECID)),
        ('chip-id', u32(0x8015)),
        ('certificate-production-status', u32(0)),
        ('effective-production-status-ap', u32(0)),
        ('certificate-security-mode', u32(1)),
        ('effective-security-mode-sep', u32(1)),
    ], [node('memory-map', [ph()]),
        node('asmb', [ph(), ('lp-sip0', u64(0x6f)), ('lp-sip1', u32(1))])])

    # 8 cores, flat MPIDR (reg = core<<8) like SWEET: XNU treats them as one
    # homogeneous cluster (board_config MAX_CPU_CLUSTERS=1). SMP bring-up uses
    # the same scheme SWEET booted with; revisit only with a 2-cluster ADT.
    cpu_nodes = []
    for core in range(1 if qemu else 8):
        big = (core < 4) if m['big_first'] else (core >= (8 - 4))
        cpu_nodes.append(node(f'cpu{core}', [
            ph(),
            ('device_type', cstr('cpu')),
            ('compatible', m['cpu_compat']),
            ('reg', u32(core << 8)),
            ('cpu-id', u32(core)),
            ('cluster-id', u32(0)),
            ('cluster-type', u32(0)),
            ('die-cluster-id', u32(0)),
            ('cluster-core-id', u32(core)),
            ('l2-cache-id', u32(core)),
            ('l3-cache-id', u32(0)),
            ('state', cstr('running' if core == 0 else 'stopped')),
            ('timebase-frequency', u32(timebase)),
            ('clock-frequency', u32(m['big_clk'] if big else m['little_clk'])),
            ('bus-frequency', u32(100000000)),
            ('memory-frequency', u32(1866000000)),
            ('peripheral-frequency', u32(timebase)),
            ('fixed-frequency', u32(timebase)),
        ]))
    cpus = node('cpus', [ph(), ('#address-cells', u32(1)),
                         ('#size-cells', u32(0))], cpu_nodes)

    gic = node('gic', [
        ph(),
        ('compatible', cstr('arm,gic-v3')),
        ('interrupt-controller', b''),
        ('virtual-timer-intid', u32(vtimer)),
        ('reg', u64(gicd - SOC_BASE, m['gicd_size'], gicr - SOC_BASE, m['gicr_size'])),
    ])
    arm_io = node('arm-io', [
        ph(),
        ('device_type', cstr(m['io_devtype'].decode())),
        ('compatible', cstr(m['io_compat'].decode()) + cstr('arm-io')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
        ('ranges', u64(0, SOC_BASE, 0x100000000 - SOC_BASE)),
    ], [gic,
        node('wdt', [ph(), ('no-pmu', u32(1))]),
        node('disp0', [
            ph(),
            ('device_type', cstr('display-subsystem')),
            ('compatible', cstr(('polaris,display' if machine == 'polaris' else 'sweet,display'))),
            ('canvas-width', u32(m['canvas_w'])),
            ('canvas-height', u32(m['canvas_h'])),
        ])])

    fbcon = node('sweet-fbcon', [
        ph(),
        ('reg', u64(m['fb'], m['fb_size'])),
        ('width', u32(m['fb_w'])),
        ('height', u32(m['fb_h'])),
        ('stride', u32(m['fb_stride'])),
    ])

    ufs = node('sweet-ufs', [
        ph(),
        ('compatible', cstr('qcom,ufshc')),
        ('reg', u64(m['ufs'], m['ufs_size'])),
    ])

    defaults = node('defaults', [ph(), ('no-effaceable-storage', u32(1))])

    buttons = node('buttons', [
        ph(),
        ('button-names', cstr('volup') + cstr('voldown') + cstr('hold')),
        ('home-button-type', u32(2)),
        ('opposed-power-vol-buttons', u32(1)),
    ])

    product_props = d22ap_product()
    product = [node('product', [ph()] + product_props)] if product_props else []

    return node('device-tree', [
        ph(),
        ('compatible', m['compatible']),
        ('model', m['model']),
        ('target-type', m['target_type']),
        ('target-sub-type', m['target_sub']),
        ('manufacturer', cstr('Apple Inc.')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
    ], [chosen, defaults, cpus, arm_io, fbcon, buttons] + product + ([] if qemu else [ufs]))


if __name__ == '__main__':
    args = sys.argv[1:]
    machine = 'polaris'
    if '--sweet' in args:
        machine = 'sweet'
    if '--polaris' in args:
        machine = 'polaris'
    root = build(machine=machine, qemu='--qemu' in args, highmem='--highmem' in args)
    blob = adt.serialize(root)
    open(args[0], 'wb').write(blob)
    if '--dump' in args:
        adt.dump(adt.parse(blob)[0])
    print(f'{args[0]}: {len(blob)} bytes ({machine})', file=sys.stderr)
