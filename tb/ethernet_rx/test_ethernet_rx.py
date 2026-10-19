import cocotb
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
