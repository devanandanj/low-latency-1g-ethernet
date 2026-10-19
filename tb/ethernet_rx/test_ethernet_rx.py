import cocotb
import zlib
import random
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

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

async def send_byte(dut, dv, byte):
    dut.gmii_rx_dv.value = dv
    dut.gmii_rxd.value = byte
    await RisingEdge(dut.gmii_rx_clk)
    await Timer(1, units="ns")
    return int(dut.state.value)

async def send_and_collect(dut, dv, byte, recieved, lasts):
    state = await send_byte(dut, dv, byte)
    if int(dut.m_valid.value) == 1:
        recieved.append(int(dut.m_data.value))
        lasts.append(int(dut.m_last.value))
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

    payload = [0x11, 0x22, 0x33, 0x44]
    recieved = []
    lasts = []

    for byte in [0x55] * 7 + [0xD5]:
        await send_and_collect(dut, 1, byte, recieved, lasts)
        assert recieved == [], f"output during preamble: {recieved}"

    for byte in payload:
            await send_and_collect(dut, 1, byte, recieved, lasts)
    for _ in range(3):
            await send_and_collect(dut, 0, 0x00, recieved, lasts)
    assert recieved == payload, f"bytes: got {[hex(b) for b in recieved]}"
    assert lasts == [0, 0, 0, 1], f"last flags: got {lasts}"

def make_frame(payload):
    """Payload followed by its 4-byte Ethernet FCS (CRC-32, little-endian)."""
    return payload + zlib.crc32(payload).to_bytes(4, "little")


async def send_frame(dut, frame, er_index=None):
    """Drive preamble + SFD + frame, then idle cycles. Returns (bytes, lasts, bads)."""
    received, lasts, bads = [], [], []

    async def tick(dv, byte, er=0):
        dut.gmii_rx_er.value = er
        await send_byte(dut, dv, byte)
        if int(dut.m_valid.value) == 1:
            received.append(int(dut.m_data.value))
            lasts.append(int(dut.m_last.value))
            bads.append(int(dut.m_bad.value))

    for byte in [0x55] * 7 + [0xD5]:
        await tick(1, byte)
    for i, byte in enumerate(frame):
        await tick(1, byte, 1 if i == er_index else 0)
    for _ in range(3):
        await tick(0, 0x00)
    return received, lasts, bads


@cocotb.test()
async def test_crc_good_frame(dut):
    await setup(dut)
    for length in [1, 10, 46, 100]:
        frame = make_frame(random.randbytes(length))
        received, lasts, bads = await send_frame(dut, frame)
        assert received == list(frame), f"len={length}: bytes differ"
        assert lasts[-1] == 1 and sum(lasts) == 1, f"len={length}: lasts={lasts}"
        assert bads[-1] == 0, f"len={length}: good frame flagged bad"


@cocotb.test()
async def test_crc_bit_flip(dut):
    await setup(dut)
    for _ in range(20):
        frame = bytearray(make_frame(random.randbytes(60)))
        pos = random.randrange(len(frame))
        frame[pos] ^= 1 << random.randrange(8)   # flip one random bit
        received, lasts, bads = await send_frame(dut, bytes(frame))
        assert bads[-1] == 1, f"bit flip at byte {pos} not detected"


@cocotb.test()
async def test_rx_er(dut):
    await setup(dut)
    frame = make_frame(random.randbytes(60))      # CRC is correct...
    received, lasts, bads = await send_frame(dut, frame, er_index=20)
    assert bads[-1] == 1, "rx_er during frame not flagged"   # ...but rx_er marks it bad
