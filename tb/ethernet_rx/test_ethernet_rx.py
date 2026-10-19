import cocotb
import zlib
import random
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

IDLE, PREAMBLE, DATA, DROP = 0, 1, 2, 3     # follow same order

async def setup(dut):
    cocotb.start_soon(Clock(dut.gmii_rx_clk, 8, units="ns").start()) # 125MHz
    dut.gmii_rx_dv.value = 0
    dut.gmii_rx_er.value = 0
    dut.gmii_rxd.value   = 0
    dut.reset.value = 1
    await RisingEdge(dut.gmii_rx_clk)
    await RisingEdge(dut.gmii_rx_clk)
    dut.reset.value = 0

async def send_and_sample(dut, dv, byte, er=0):
    """One clock cycle. Returns (state after the edge, outputs sampled mid-cycle)."""
    dut.gmii_rx_dv.value = dv
    dut.gmii_rxd.value = byte
    dut.gmii_rx_er.value = er
    # Mid-cycle: inputs and state belong to the same cycle, so this is
    # exactly what the next stage's flip-flops capture at the rising edge.
    await FallingEdge(dut.gmii_rx_clk)
    out = {
        "valid": int(dut.m_valid.value),
        "data": int(dut.m_data.value),
        "eof": int(dut.m_eof.value),
        "bad": int(dut.m_bad.value),
    }
    await RisingEdge(dut.gmii_rx_clk)
    await Timer(1, units="ns")
    return int(dut.state.value), out

async def send_byte(dut, dv, byte):
    state, _ = await send_and_sample(dut, dv, byte)
    return state

@cocotb.test()
async def test_good_frame(dut):
    await setup(dut)

    for n in range(7):
        state = await send_byte(dut, 1, 0x55)
        assert state == PREAMBLE, f"preamble byte {n}: state = {state}"

    state = await send_byte(dut, 1, 0xD5)
    assert state == DATA, f"after SFD: state = {state}"

    for byte in [0x11, 0x22, 0x33]:
        state = await send_byte(dut, 1, byte)
        assert state == DATA, f"data byte {byte:#04x}: state = {state}"

    state = await send_byte(dut, 0, 0x00)
    assert state == IDLE, f"after frame end: state = {state}"

@cocotb.test()
async def test_short_preamble(dut):
    await setup(dut)

    state = await send_byte(dut, 1, 0xD5)
    assert state == DATA, f"after SFD: state = {state}"

    for byte in [0x11, 0x22, 0x33]:
        state = await send_byte(dut, 1, byte)
        assert state == DATA, f"data byte {byte:#04x}: state = {state}"

    state = await send_byte(dut, 0, 0x00)
    assert state == IDLE, f"after frame end: state = {state}"

@cocotb.test()
async def test_dv_drop_in_preamble(dut):
    await setup(dut)

    for n in range(3):
        state = await send_byte(dut, 1, 0x55)
        assert state == PREAMBLE, f"preamble byte {n}: state = {state}"

    # rx_dv drops before the SFD: frame abandoned
    state = await send_byte(dut, 0, 0x00)
    assert state == IDLE, f"after dv drop: state = {state}"


@cocotb.test()
async def test_bad_start(dut):
    await setup(dut)

    # first byte is neither 55 nor D5: drop the frame
    state = await send_byte(dut, 1, 0x42)
    assert state == DROP, f"after bad first byte: state = {state}"

    # garbage, including bytes that LOOK like 55 / D5: must stay in DROP
    for byte in [0x55, 0xD5, 0x99, 0x55]:
        state = await send_byte(dut, 1, byte)
        assert state == DROP, f"garbage byte {byte:#04x}: state = {state}"

    # bad frame ends
    state = await send_byte(dut, 0, 0x00)
    assert state == IDLE, f"after bad frame end: state = {state}"

    # a good frame right after must work normally
    state = await send_byte(dut, 1, 0x55)
    assert state == PREAMBLE, f"next frame preamble: state = {state}"
    state = await send_byte(dut, 1, 0xD5)
    assert state == DATA, f"next frame SFD: state = {state}"


@cocotb.test()
async def test_broken_preamble(dut):
    await setup(dut)

    state = await send_byte(dut, 1, 0x55)
    assert state == PREAMBLE, f"preamble: state = {state}"

    # a wrong byte inside the preamble
    state = await send_byte(dut, 1, 0x77)
    assert state == DROP, f"after broken preamble: state = {state}"

    state = await send_byte(dut, 0, 0x00)
    assert state == IDLE, f"after frame end: state = {state}"


@cocotb.test()
async def test_reset_mid_frame(dut):
    await setup(dut)

    # leave the module stuck mid-frame in DATA, then reset
    await send_byte(dut, 1, 0xD5)
    state = await send_byte(dut, 1, 0x11)
    assert state == DATA, f"before reset: state = {state}"

    await setup(dut)   # reset while rx_dv is still... re-driven to 0 by setup
    state = int(dut.state.value)
    assert state == IDLE, f"after reset: state = {state}"

@cocotb.test()
async def test_output_bytes(dut):
    await setup(dut)
    mon = Monitor()
    payload = [0x11, 0x22, 0x33, 0x44]
    await send_frame(dut, bytes(payload), mon)
    assert mon.data == payload, f"bytes: got {[hex(b) for b in mon.data]}"
    assert len(mon.eofs) == 1, f"expected 1 eof pulse, got {len(mon.eofs)}"


def make_frame(payload):
    """Payload followed by its 4-byte Ethernet FCS (CRC-32, little-endian)."""
    return payload + zlib.crc32(payload).to_bytes(4, "little")


class Monitor:
    """Collects what the MAC outputs: data bytes and end-of-frame results."""
    def __init__(self):
        self.data = []      # every byte seen with m_valid = 1
        self.eofs = []      # m_bad value of every m_eof pulse

    def record(self, out):
        if out["valid"]:
            self.data.append(out["data"])
        if out["eof"]:
            self.eofs.append(out["bad"])


async def send_frame(dut, frame, mon, er_index=None, gap=3):
    """Drive preamble + SFD + frame, then `gap` idle cycles."""
    for byte in [0x55] * 7 + [0xD5]:
        _, out = await send_and_sample(dut, 1, byte)
        mon.record(out)
    for i, byte in enumerate(frame):
        _, out = await send_and_sample(dut, 1, byte, 1 if i == er_index else 0)
        mon.record(out)
    for _ in range(gap):
        _, out = await send_and_sample(dut, 0, 0x00)
        mon.record(out)


@cocotb.test()
async def test_latency(dut):
    """A data byte must appear on m_data in the same cycle it is driven."""
    await setup(dut)
    for byte in [0x55] * 7 + [0xD5]:
        await send_and_sample(dut, 1, byte)
    for byte in [0x11, 0x22, 0x33]:
        _, out = await send_and_sample(dut, 1, byte)
        assert out["valid"] == 1, f"{byte:#04x}: m_valid not set in the same cycle"
        assert out["data"] == byte, f"{byte:#04x}: m_data = {out['data']:#04x}"


@cocotb.test()
async def test_crc_good_frame(dut):
    await setup(dut)
    for length in [1, 10, 46, 100]:
        mon = Monitor()
        frame = make_frame(random.randbytes(length))
        await send_frame(dut, frame, mon)
        assert mon.data == list(frame), f"len={length}: bytes differ"
        assert mon.eofs == [0], f"len={length}: eofs={mon.eofs}"


@cocotb.test()
async def test_crc_bit_flip(dut):
    await setup(dut)
    for _ in range(20):
        mon = Monitor()
        frame = bytearray(make_frame(random.randbytes(60)))
        pos = random.randrange(len(frame))
        frame[pos] ^= 1 << random.randrange(8)   # flip one random bit
        await send_frame(dut, bytes(frame), mon)
        assert mon.eofs == [1], f"bit flip at byte {pos} not detected"


@cocotb.test()
async def test_rx_er(dut):
    await setup(dut)
    mon = Monitor()
    frame = make_frame(random.randbytes(60))      # CRC is correct...
    await send_frame(dut, frame, mon, er_index=20)
    assert mon.eofs == [1], "rx_er during frame not flagged"   # ...but rx_er marks it bad


@cocotb.test()
async def test_back_to_back(dut):
    """Two frames separated by the minimum 12-byte inter-frame gap."""
    await setup(dut)
    mon = Monitor()
    f1 = make_frame(random.randbytes(46))
    f2 = make_frame(random.randbytes(46))
    await send_frame(dut, f1, mon, gap=12)
    await send_frame(dut, f2, mon, gap=3)
    assert mon.data == list(f1) + list(f2), "bytes of the two frames differ"
    assert mon.eofs == [0, 0], f"eofs={mon.eofs}"


@cocotb.test()
async def test_truncated_frame(dut):
    """rx_dv drops partway through the data: frame must end bad."""
    await setup(dut)
    mon = Monitor()
    frame = make_frame(random.randbytes(60))
    await send_frame(dut, frame[:10], mon)        # only the first 10 bytes
    assert mon.data == list(frame[:10]), "truncated bytes differ"
    assert mon.eofs == [1], f"truncated frame not flagged: eofs={mon.eofs}"
