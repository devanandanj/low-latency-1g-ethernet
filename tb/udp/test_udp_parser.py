import cocotb
import random
import struct
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge

MY_PORT = 26477
OTHER_PORT = 26478
SRC_PORT = 40000
FCS = b"\xde\xad\xbe\xef"
TRAILER = bytes(6) + FCS    # Ethernet padding + FCS-like bytes


async def setup(dut):
    cocotb.start_soon(Clock(dut.gmii_rx_clk, 8, units="ns").start())  # 125 MHz
    dut.cfg_port.value = MY_PORT
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
    """Send bytes the way the IPv4 parser does: bytes, idle cycle, eof pulse."""
    for byte in frame:
        await cycle(dut, mon, valid=1, data=byte)
    await cycle(dut, mon)                    # rx_dv dropped
    await cycle(dut, mon, eof=1, bad=bad)    # MAC's eof/bad pulse
    for _ in range(3):
        await cycle(dut, mon)


def make_header(payload_len, dst=MY_PORT, length=None):
    """8-byte UDP header. `length` overrides the correct value (payload + 8)."""
    if length is None:
        length = payload_len + 8
    return struct.pack("!HHHH", SRC_PORT, dst, length, 0)


@cocotb.test()
async def test_kept_packet(dut):
    await setup(dut)
    mon = Monitor()
    payload = random.randbytes(40)
    await send_frame(dut, mon, make_header(40) + payload + FCS)
    assert mon.data == list(payload), "payload differs"
    assert mon.eofs == [0], f"eofs={mon.eofs}"


@cocotb.test()
async def test_trims_padding_and_fcs(dut):
    """Only UDP-length bytes come out; what follows the payload is discarded."""
    await setup(dut)
    for length in [1, 10, 300]:     # 300 needs the high length byte
        mon = Monitor()
        payload = random.randbytes(length)
        await send_frame(dut, mon, make_header(length) + payload + TRAILER)
        assert mon.data == list(payload), f"len={length}: payload differs"
        assert mon.eofs == [0], f"len={length}: eofs={mon.eofs}"


@cocotb.test()
async def test_wrong_port(dut):
    """A mismatch in either port byte must drop the packet."""
    await setup(dut)
    for dst in [OTHER_PORT, MY_PORT ^ 0x0100]:
        mon = Monitor()
        await send_frame(dut, mon, make_header(20, dst=dst) + random.randbytes(20))
        assert mon.data == [], f"port {dst}: packet leaked out"
        assert mon.eofs == [], f"port {dst}: eof forwarded"


@cocotb.test()
async def test_length_too_small(dut):
    """UDP length below the 8-byte header is invalid and must not wrap."""
    await setup(dut)
    for length in [0, 3, 7]:
        mon = Monitor()
        await send_frame(dut, mon, make_header(0, length=length) + random.randbytes(20))
        assert mon.data == [], f"length={length}: packet leaked out"
        assert mon.eofs == [], f"length={length}: eof forwarded"


@cocotb.test()
async def test_length_too_large(dut):
    """UDP length running into the FCS must end bad, even by one byte."""
    await setup(dut)
    for extra in [1, 3, 4, 5, 50]:
        mon = Monitor()
        payload = random.randbytes(20)
        header = make_header(20, length=28 + extra)
        await send_frame(dut, mon, header + payload + FCS)
        assert mon.eofs == [1], f"extra={extra}: eofs={mon.eofs}"


@cocotb.test()
async def test_next_after_length_too_large(dut):
    """The trailer count must clear between frames."""
    await setup(dut)
    mon = Monitor()
    await send_frame(dut, mon, make_header(20) + random.randbytes(20) + FCS)
    await send_frame(dut, mon, make_header(20, length=29) + random.randbytes(20) + FCS)
    assert mon.eofs == [0, 1], f"eofs={mon.eofs}"


@cocotb.test()
async def test_empty_payload(dut):
    """Length exactly 8: no bytes out, but the frame still ends."""
    await setup(dut)
    mon = Monitor()
    await send_frame(dut, mon, make_header(0) + TRAILER)
    assert mon.data == [], "bytes came out of an empty payload"
    assert mon.eofs == [0], f"eofs={mon.eofs}"


@cocotb.test()
async def test_bad_passed_through(dut):
    await setup(dut)
    mon = Monitor()
    await send_frame(dut, mon, make_header(20) + random.randbytes(20), bad=1)
    assert mon.eofs == [1], f"bad flag not forwarded: eofs={mon.eofs}"


@cocotb.test()
async def test_drop_then_keep(dut):
    """A dropped packet must not affect the next one."""
    await setup(dut)
    mon = Monitor()
    payload = random.randbytes(20)
    await send_frame(dut, mon, make_header(20, dst=OTHER_PORT) + random.randbytes(20))
    await send_frame(dut, mon, make_header(20) + payload + FCS)
    assert mon.data == list(payload), "second packet payload differs"
    assert mon.eofs == [0], f"eofs={mon.eofs}"


@cocotb.test()
async def test_latency(dut):
    """Payload byte must appear on m_data in the same cycle it arrives."""
    await setup(dut)
    mon = Monitor()
    for byte in make_header(3):
        await cycle(dut, mon, valid=1, data=byte)
    assert mon.data == [], "header bytes leaked"
    for byte in [0xAA, 0xBB, 0xCC]:
        dut.s_valid.value = 1
        dut.s_data.value = byte
        await FallingEdge(dut.gmii_rx_clk)
        assert int(dut.m_valid.value) == 1, f"{byte:#04x}: not valid same cycle"
        assert int(dut.m_data.value) == byte, f"{byte:#04x}: wrong data"
        await RisingEdge(dut.gmii_rx_clk)
