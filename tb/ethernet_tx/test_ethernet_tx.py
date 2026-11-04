import cocotb
import random
import zlib
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge

PREAMBLE = [0x55] * 7 + [0xD5]
MIN_LEN = 60        # minimum frame before the FCS
MIN_GAP = 12        # inter-frame gap in cycles


class Monitor:
    """Records both ends of the loopback, one sample per cycle."""
    def __init__(self):
        self.frames = []    # bytes of each frame seen on GMII
        self.gaps = []      # idle cycles between frames
        self.er = 0         # cycles with gmii_tx_er set
        self.rx_data = []   # bytes out of the RX MAC
        self.rx_eofs = []   # m_bad at each m_eof pulse

    async def run(self, dut):
        current = None
        idle = 0
        while True:
            await FallingEdge(dut.gtx_clk)
            if int(dut.gmii_tx_en.value):
                if current is None:
                    if self.frames:
                        self.gaps.append(idle)
                    current = []
                current.append(int(dut.gmii_txd.value))
                self.er += int(dut.gmii_tx_er.value)
            elif current is not None:
                self.frames.append(current)
                current = None
                idle = 1
            else:
                idle += 1
            if int(dut.m_valid.value):
                self.rx_data.append(int(dut.m_data.value))
            if int(dut.m_eof.value):
                self.rx_eofs.append(int(dut.m_bad.value))


async def setup(dut):
    cocotb.start_soon(Clock(dut.gtx_clk, 8, units="ns").start())  # 125 MHz
    dut.s_data.value = 0
    dut.s_valid.value = 0
    dut.s_last.value = 0
    dut.reset.value = 1
    await RisingEdge(dut.gtx_clk)
    await RisingEdge(dut.gtx_clk)
    dut.reset.value = 0
    mon = Monitor()
    cocotb.start_soon(mon.run(dut))
    return mon


async def send(dut, payload, stall_at=None):
    """Drive one payload, holding each byte until s_ready takes it."""
    for i, byte in enumerate(payload):
        if i == stall_at:       # underrun: s_valid drops for one cycle
            dut.s_valid.value = 0
            await RisingEdge(dut.gtx_clk)
        dut.s_valid.value = 1
        dut.s_data.value = byte
        dut.s_last.value = int(i == len(payload) - 1)
        while True:
            await FallingEdge(dut.gtx_clk)
            ready = int(dut.s_ready.value)
            await RisingEdge(dut.gtx_clk)
            if ready:
                break
    dut.s_valid.value = 0
    dut.s_last.value = 0


async def wait_idle(dut, cycles=30):
    for _ in range(cycles):
        await RisingEdge(dut.gtx_clk)


def expected_frame(payload):
    """What must appear on the wire for this payload."""
    body = payload + bytes(max(0, MIN_LEN - len(payload)))
    return PREAMBLE + list(body) + list(zlib.crc32(body).to_bytes(4, "little"))


@cocotb.test()
async def test_frame_bytes(dut):
    """Preamble, payload and FCS match a frame built in Python."""
    mon = await setup(dut)
    payload = random.randbytes(100)
    await send(dut, payload)
    await wait_idle(dut)
    assert mon.frames == [expected_frame(payload)], "frame differs"


@cocotb.test()
async def test_padding(dut):
    """Lengths around the 60-byte minimum, where off-by-ones live."""
    mon = await setup(dut)
    payloads = [random.randbytes(n) for n in [1, 10, 58, 59, 60, 61]]
    for payload in payloads:
        await send(dut, payload)
    await wait_idle(dut)
    assert mon.frames == [expected_frame(p) for p in payloads], "frames differ"


@cocotb.test()
async def test_long_frame(dut):
    """frame_len stops at 60, so a long frame must not wrap and pad."""
    mon = await setup(dut)
    payload = random.randbytes(1500)
    await send(dut, payload)
    await wait_idle(dut)
    assert mon.frames == [expected_frame(payload)], "frame differs"


@cocotb.test()
async def test_gap_is_minimum(dut):
    """Back-to-back frames: exactly 12 idle cycles, no more and no less."""
    mon = await setup(dut)
    for _ in range(3):
        await send(dut, random.randbytes(70))
    await wait_idle(dut)
    assert len(mon.frames) == 3, f"got {len(mon.frames)} frames"
    assert mon.gaps == [MIN_GAP, MIN_GAP], f"gaps={mon.gaps}"


@cocotb.test()
async def test_underrun(dut):
    """s_valid dropping mid-frame sets tx_er, and RX flags the frame bad."""
    mon = await setup(dut)
    await send(dut, random.randbytes(80), stall_at=30)
    await wait_idle(dut)
    assert mon.er == 1, f"tx_er cycles={mon.er}"
    assert mon.rx_eofs == [1], f"eofs={mon.rx_eofs}"


@cocotb.test()
async def test_loopback(dut):
    """Every TX frame must arrive at RX intact, with a good FCS."""
    mon = await setup(dut)
    expected = []
    for length in [1, 46, 60, 100, 300]:
        payload = random.randbytes(length)
        await send(dut, payload)
        expected += expected_frame(payload)[8:]     # RX strips preamble + SFD
    await wait_idle(dut)
    assert mon.rx_data == expected, "bytes through RX differ"
    assert mon.rx_eofs == [0] * 5, f"eofs={mon.rx_eofs}"
