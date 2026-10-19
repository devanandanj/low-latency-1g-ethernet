import cocotb
import random
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge

MY_MAC = bytes.fromhex("01005e000001")      # multicast MAC of the feed
OTHER_MAC = bytes.fromhex("01005e000002")
SRC_MAC = bytes.fromhex("aabbccddeeff")
IPV4 = b"\x08\x00"
VLAN = b"\x81\x00"


async def setup(dut):
    cocotb.start_soon(Clock(dut.gmii_rx_clk, 8, units="ns").start())  # 125 MHz
    dut.cfg_mac.value = int.from_bytes(MY_MAC, "big")
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
    """Send frame bytes the way the MAC does: bytes, one idle cycle, eof pulse."""
    for byte in frame:
        await cycle(dut, mon, valid=1, data=byte)
    await cycle(dut, mon)                    # rx_dv dropped
    await cycle(dut, mon, eof=1, bad=bad)    # MAC's eof/bad pulse
    for _ in range(3):
        await cycle(dut, mon)


def make_frame(dst, ethertype, payload):
    return dst + SRC_MAC + ethertype + payload


@cocotb.test()
async def test_kept_frame(dut):
    """Frame for our MAC with EtherType IPv4: payload comes out, header doesn't."""
    await setup(dut)
    mon = Monitor()
    payload = random.randbytes(50)
    await send_frame(dut, mon, make_frame(MY_MAC, IPV4, payload))
    assert mon.data == list(payload), "payload differs"
    assert mon.eofs == [0], f"eofs={mon.eofs}"


@cocotb.test()
async def test_wrong_mac(dut):
    await setup(dut)
    mon = Monitor()
    await send_frame(dut, mon, make_frame(OTHER_MAC, IPV4, random.randbytes(50)))
    assert mon.data == [], "frame for another MAC leaked out"
    assert mon.eofs == [], "eof forwarded for a dropped frame"


@cocotb.test()
async def test_wrong_mac_each_byte(dut):
    """A mismatch in any single MAC byte must drop the frame."""
    await setup(dut)
    for i in range(6):
        mon = Monitor()
        dst = bytearray(MY_MAC)
        dst[i] ^= 0xFF
        await send_frame(dut, mon, make_frame(bytes(dst), IPV4, random.randbytes(20)))
        assert mon.data == [], f"mismatch in MAC byte {i} not caught"


@cocotb.test()
async def test_wrong_ethertype(dut):
    await setup(dut)
    for ethertype in [VLAN, b"\x86\xdd", b"\x08\x06", b"\x00\x00"]:
        mon = Monitor()
        await send_frame(dut, mon, make_frame(MY_MAC, ethertype, random.randbytes(20)))
        assert mon.data == [], f"EtherType {ethertype.hex()} not dropped"
        assert mon.eofs == [], f"EtherType {ethertype.hex()}: eof forwarded"


@cocotb.test()
async def test_short_frame(dut):
    """Frame that ends before the payload: nothing out, no eof."""
    await setup(dut)
    mon = Monitor()
    await send_frame(dut, mon, MY_MAC + SRC_MAC)    # 12 bytes only
    assert mon.data == [] and mon.eofs == [], "short frame produced output"


@cocotb.test()
async def test_bad_passed_through(dut):
    await setup(dut)
    mon = Monitor()
    await send_frame(dut, mon, make_frame(MY_MAC, IPV4, random.randbytes(30)), bad=1)
    assert mon.eofs == [1], f"bad flag not forwarded: eofs={mon.eofs}"


@cocotb.test()
async def test_drop_then_keep(dut):
    """A dropped frame must not affect the next one."""
    await setup(dut)
    mon = Monitor()
    payload = random.randbytes(40)
    await send_frame(dut, mon, make_frame(OTHER_MAC, IPV4, random.randbytes(40)))
    await send_frame(dut, mon, make_frame(MY_MAC, IPV4, payload))
    assert mon.data == list(payload), "second frame payload differs"
    assert mon.eofs == [0], f"eofs={mon.eofs}"


@cocotb.test()
async def test_latency(dut):
    """Payload byte must appear on m_data in the same cycle it arrives."""
    await setup(dut)
    mon = Monitor()
    header = MY_MAC + SRC_MAC + IPV4
    for byte in header:
        await cycle(dut, mon, valid=1, data=byte)
    assert mon.data == [], "header bytes leaked"
    for byte in [0x45, 0x00, 0x11]:
        dut.s_valid.value = 1
        dut.s_data.value = byte
        await FallingEdge(dut.gmii_rx_clk)
        assert int(dut.m_valid.value) == 1, f"{byte:#04x}: not valid same cycle"
        assert int(dut.m_data.value) == byte, f"{byte:#04x}: wrong data"
        await RisingEdge(dut.gmii_rx_clk)
