import zlib
import random
import cocotb
from cocotb.triggers import Timer

async def crc32_on_dut(dut, data):
    crc = 0xFFFFFFFF
    for i in data:
        dut.crc_current.value = crc
        dut.data_in.value = i
        await Timer(1, units="ns")
        crc = int(dut.crc_out.value)
    return crc ^ 0xFFFFFFFF


@cocotb.test()
async def test_check_value(dut):
    got = await crc32_on_dut(dut, b"123456789")
    assert got == 0xCBF43926, f"got {got:#010x}"

@cocotb.test()
async def test_random(dut):
    for i in range(200):
        data = random.randbytes(i)
        got = await crc32_on_dut(dut, data)
        assert got == zlib.crc32(data)
