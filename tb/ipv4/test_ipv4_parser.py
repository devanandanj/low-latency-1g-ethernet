import cocotb
import random
import struct
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge

MY_IP = bytes([233, 54, 12, 1])         # multicast group of the feed
OTHER_IP = bytes([233, 54, 12, 2])
SRC_IP = bytes([10, 0, 0, 1])
UDP = 17
TCP = 6


async def setup(dut):
    cocotb.start_soon(Clock(dut.gmii_rx_clk, 8, units="ns").start())  # 125 MHz
    dut.cfg_ip.value = int.from_bytes(MY_IP, "big")
    dut.s_data.value = 0
    dut.s_valid.value = 0
    dut.s_eof.value = 0
    dut.s_bad.value = 0
    dut.reset.value = 1
    await RisingEdge(dut.gmii_rx_clk)
    await RisingEdge(dut.gmii_rx_clk)
    dut.reset.value = 0


class Monitor:
    """Collects the parser's output: payload bytes and end-of-frame results."""
    def __init__(self):
        self.data = []
        self.eofs = []      # m_bad value at each m_eof pulse

    def record(self, dut):
        if int(dut.m_valid.value):
            self.data.append(int(dut.m_data.value))
        if int(dut.m_eof.value):
            self.eofs.append(int(dut.m_bad.value))


async def cycle(dut, mon, valid=0, data=0, eof=0, bad=0):
    """Drive one cycle of the input stream, sample outputs mid-cycle."""
    dut.s_valid.value = valid
    dut.s_data.value = data
    dut.s_eof.value = eof
    dut.s_bad.value = bad
    await FallingEdge(dut.gmii_rx_clk)
    mon.record(dut)
    await RisingEdge(dut.gmii_rx_clk)


async def send_frame(dut, mon, frame, bad=0):
    """Send bytes the way the Ethernet parser does: bytes, idle cycle, eof pulse."""
    for byte in frame:
        await cycle(dut, mon, valid=1, data=byte)
    await cycle(dut, mon)                    # rx_dv dropped
    await cycle(dut, mon, eof=1, bad=bad)    # MAC's eof/bad pulse
    for _ in range(3):
        await cycle(dut, mon)


def checksum(header):
    """IPv4 header checksum: ones'-complement sum of ten 16-bit words, inverted."""
    total = sum(struct.unpack("!10H", header))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def make_header(dst=MY_IP, proto=UDP, ver_ihl=0x45, flags=0x4000, ident=None):
    """20-byte IPv4 header with a correct checksum. Defaults are a good packet."""
    if ident is None:
        ident = random.randrange(65536)
    h = struct.pack("!BBHHHBBH4s4s", ver_ihl, 0, 60, ident, flags, 64, proto, 0,
                    SRC_IP, dst)
    return h[:10] + struct.pack("!H", checksum(h)) + h[12:]


@cocotb.test()
async def test_kept_packet(dut):
    """Good packet: payload comes out, IP header doesn't."""
    await setup(dut)
    mon = Monitor()
    payload = random.randbytes(40)
    await send_frame(dut, mon, make_header() + payload)
    assert mon.data == list(payload), "payload differs"
    assert mon.eofs == [0], f"eofs={mon.eofs}"


@cocotb.test()
async def test_random_packets(dut):
    """Random IDs give different sums, exercising the carry wrap."""
    await setup(dut)
    for ident in [0xFFFF] + [random.randrange(65536) for _ in range(50)]:
        mon = Monitor()
        payload = random.randbytes(20)
        await send_frame(dut, mon, make_header(ident=ident) + payload)
        assert mon.data == list(payload), f"ident={ident:#06x}: payload differs"


@cocotb.test()
async def test_dropped_packets(dut):
    await setup(dut)
    cases = {
        "wrong IP": make_header(dst=OTHER_IP),
        "TCP": make_header(proto=TCP),
        "IP options": make_header(ver_ihl=0x46),
        "more fragments": make_header(flags=0x2000),
        "fragment offset": make_header(flags=0x0001),
    }
    for name, header in cases.items():
        mon = Monitor()
        await send_frame(dut, mon, header + random.randbytes(20))
        assert mon.data == [], f"{name}: packet leaked out"
        assert mon.eofs == [], f"{name}: eof forwarded"


@cocotb.test()
async def test_bad_checksum(dut):
    """One flipped bit in the checksum field must drop the packet."""
    await setup(dut)
    for bit in range(16):
        mon = Monitor()
        header = bytearray(make_header())
        header[10 + bit // 8] ^= 1 << (bit % 8)
        await send_frame(dut, mon, bytes(header) + random.randbytes(20))
        assert mon.data == [], f"checksum bit {bit} flip not caught"


@cocotb.test()
async def test_bad_passed_through(dut):
    await setup(dut)
    mon = Monitor()
    await send_frame(dut, mon, make_header() + random.randbytes(20), bad=1)
    assert mon.eofs == [1], f"bad flag not forwarded: eofs={mon.eofs}"


@cocotb.test()
async def test_short_then_good(dut):
    """A packet ending inside the header must not affect the next one."""
    await setup(dut)
    mon = Monitor()
    payload = random.randbytes(20)
    await send_frame(dut, mon, make_header()[:12])
    await send_frame(dut, mon, make_header() + payload)
    assert mon.data == list(payload), "second packet payload differs"
    assert mon.eofs == [0], f"eofs={mon.eofs}"


@cocotb.test()
async def test_latency(dut):
    """Payload byte must appear on m_data in the same cycle it arrives."""
    await setup(dut)
    mon = Monitor()
    for byte in make_header():
        await cycle(dut, mon, valid=1, data=byte)
    assert mon.data == [], "header bytes leaked"
    for byte in [0xAA, 0xBB, 0xCC]:
        dut.s_valid.value = 1
        dut.s_data.value = byte
        await FallingEdge(dut.gmii_rx_clk)
        assert int(dut.m_valid.value) == 1, f"{byte:#04x}: not valid same cycle"
        assert int(dut.m_data.value) == byte, f"{byte:#04x}: wrong data"
        await RisingEdge(dut.gmii_rx_clk)
