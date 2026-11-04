import cocotb
import random
import struct
import zlib
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge

PREAMBLE = bytes([0x55] * 7 + [0xD5])
MIN_LEN = 60        # minimum frame before the FCS
MIN_GAP = 12        # inter-frame gap in cycles
ETH_HDR = 14
IP_HDR = 20
UDP_HDR = 8
TTL_AT = ETH_HDR + 8

MY_MAC = bytes.fromhex("01005e360c01")  # multicast MAC of the feed group
OTHER_MAC = bytes.fromhex("01005e360c02")
SRC_MAC = bytes.fromhex("020000000001")
MY_IP = bytes([233, 54, 12, 1])
OTHER_IP = bytes([233, 54, 12, 2])
SRC_IP = bytes([10, 0, 0, 1])
MY_PORT = 26477
OTHER_PORT = 26478
SRC_PORT = 40000
IPV4 = 0x0800
UDP = 17


async def setup(dut):
    cocotb.start_soon(Clock(dut.gmii_rx_clk, 8, units="ns").start())  # 125 MHz
    cocotb.start_soon(Clock(dut.gtx_clk, 8, units="ns").start())
    dut.cfg_mac.value = int.from_bytes(MY_MAC, "big")
    dut.cfg_ip.value = int.from_bytes(MY_IP, "big")
    dut.cfg_port.value = MY_PORT
    dut.gmii_rxd.value = 0
    dut.gmii_rx_dv.value = 0
    dut.gmii_rx_er.value = 0
    dut.s_data.value = 0
    dut.s_valid.value = 0
    dut.s_last.value = 0
    dut.reset.value = 1
    await RisingEdge(dut.gmii_rx_clk)
    await RisingEdge(dut.gmii_rx_clk)
    dut.reset.value = 0


class Monitor:
    """Collects the stack's output: payload bytes and end-of-frame results."""
    def __init__(self):
        self.data = []
        self.eofs = []      # m_bad value at each m_eof pulse

    def record(self, dut):
        if int(dut.m_valid.value):
            self.data.append(int(dut.m_data.value))
        if int(dut.m_eof.value):
            self.eofs.append(int(dut.m_bad.value))


async def cycle(dut, mon, dv=0, data=0, er=0):
    """Drive one GMII cycle, sample outputs mid-cycle."""
    dut.gmii_rx_dv.value = dv
    dut.gmii_rxd.value = data
    dut.gmii_rx_er.value = er
    await FallingEdge(dut.gmii_rx_clk)
    mon.record(dut)
    await RisingEdge(dut.gmii_rx_clk)


async def send_wire(dut, mon, wire, er_at=None):
    """Send raw GMII bytes, then the inter-frame gap."""
    for i, byte in enumerate(wire):
        await cycle(dut, mon, dv=1, data=byte, er=int(i == er_at))
    for _ in range(MIN_GAP):
        await cycle(dut, mon)


def checksum(header):
    """IPv4 header checksum: ones'-complement sum of ten 16-bit words, inverted."""
    total = sum(struct.unpack("!10H", header))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def make_body(payload, mac=MY_MAC, ip=MY_IP, port=MY_PORT, ethertype=IPV4, extra=0):
    """Ethernet + IPv4 + UDP + payload, padded to the minimum, without FCS.
    `extra` makes the UDP length claim that many bytes more than the payload."""
    eth = mac + SRC_MAC + struct.pack("!H", ethertype)
    h = struct.pack("!BBHHHBBH4s4s", 0x45, 0, IP_HDR + UDP_HDR + len(payload),
                    random.randrange(65536), 0x4000, 64, UDP, 0, SRC_IP, ip)
    h = h[:10] + struct.pack("!H", checksum(h)) + h[12:]
    udp = struct.pack("!HHHH", SRC_PORT, port, UDP_HDR + len(payload) + extra, 0)
    body = eth + h + udp + payload
    return body + bytes(max(0, MIN_LEN - len(body)))


def make_wire(body):
    """What the PHY delivers for this frame: preamble, body, FCS."""
    return PREAMBLE + body + zlib.crc32(body).to_bytes(4, "little")


@cocotb.test()
async def test_good_frame(dut):
    await setup(dut)
    mon = Monitor()
    payload = random.randbytes(100)
    await send_wire(dut, mon, make_wire(make_body(payload)))
    assert mon.data == list(payload), "payload differs"
    assert mon.eofs == [0], f"eofs={mon.eofs}"


@cocotb.test()
async def test_short_payload_trims_padding(dut):
    """Padding and FCS must not come out, even for one byte of payload."""
    await setup(dut)
    for length in [1, 2, 17, 18, 19]:   # 18 exactly fills the 60-byte minimum
        mon = Monitor()
        payload = random.randbytes(length)
        await send_wire(dut, mon, make_wire(make_body(payload)))
        assert mon.data == list(payload), f"len={length}: payload differs"
        assert mon.eofs == [0], f"len={length}: eofs={mon.eofs}"


@cocotb.test()
async def test_corrupted_payload(dut):
    """Speculative cut-through: bytes come out first, m_bad arrives at the end."""
    await setup(dut)
    mon = Monitor()
    payload = random.randbytes(100)
    wire = bytearray(make_wire(make_body(payload)))
    at = len(PREAMBLE) + ETH_HDR + IP_HDR + UDP_HDR + 50
    wire[at] ^= 0x01
    await send_wire(dut, mon, bytes(wire))
    expected = bytearray(payload)
    expected[50] ^= 0x01
    assert mon.data == list(expected), "payload was not passed through"
    assert mon.eofs == [1], f"eofs={mon.eofs}"


@cocotb.test()
async def test_corrupted_fcs(dut):
    """Payload is untouched but the frame must still be reported bad."""
    await setup(dut)
    mon = Monitor()
    payload = random.randbytes(100)
    wire = bytearray(make_wire(make_body(payload)))
    wire[-1] ^= 0x80
    await send_wire(dut, mon, bytes(wire))
    assert mon.data == list(payload), "payload differs"
    assert mon.eofs == [1], f"eofs={mon.eofs}"


@cocotb.test()
async def test_line_error(dut):
    """gmii_rx_er with a good CRC must reach the end of the chain as m_bad."""
    await setup(dut)
    mon = Monitor()
    payload = random.randbytes(100)
    await send_wire(dut, mon, make_wire(make_body(payload)), er_at=70)
    assert mon.data == list(payload), "payload differs"
    assert mon.eofs == [1], f"eofs={mon.eofs}"


@cocotb.test()
async def test_dropped_frames(dut):
    """Each stage drops what isn't for us: nothing comes out, not even eof."""
    await setup(dut)
    payload = random.randbytes(40)
    bad_ttl = bytearray(make_body(payload))
    bad_ttl[TTL_AT] ^= 0x01     # IPv4 checksum no longer matches, FCS still good
    bodies = {
        "mac": make_body(payload, mac=OTHER_MAC),
        "ethertype": make_body(payload, ethertype=0x86DD),
        "ip": make_body(payload, ip=OTHER_IP),
        "port": make_body(payload, port=OTHER_PORT),
        "checksum": bytes(bad_ttl),
    }
    for name, body in bodies.items():
        mon = Monitor()
        await send_wire(dut, mon, make_wire(body))
        assert mon.data == [], f"{name}: packet leaked out"
        assert mon.eofs == [], f"{name}: eof forwarded"


@cocotb.test()
async def test_truncated_then_good(dut):
    """A frame cut off inside a header must leave no state behind in any stage."""
    await setup(dut)
    body = make_body(random.randbytes(40))
    for cut in [ETH_HDR - 5, ETH_HDR + 10, ETH_HDR + IP_HDR + 2]:
        mon = Monitor()
        payload = random.randbytes(40)
        await send_wire(dut, mon, make_wire(body[:cut]))
        assert mon.data == [], f"cut={cut}: bytes leaked out"
        assert mon.eofs == [], f"cut={cut}: eof forwarded"
        await send_wire(dut, mon, make_wire(make_body(payload)))
        assert mon.data == list(payload), f"cut={cut}: next frame differs"
        assert mon.eofs == [0], f"cut={cut}: eofs={mon.eofs}"


@cocotb.test()
async def test_runt_past_headers(dut):
    """Runt that gets through every header: FCS bytes leak out, so m_bad must be set."""
    await setup(dut)
    mon = Monitor()
    body = make_body(random.randbytes(40))
    await send_wire(dut, mon, make_wire(body[:ETH_HDR + IP_HDR + 6]))
    assert mon.eofs == [1], f"eofs={mon.eofs}"


@cocotb.test()
async def test_udp_length_too_large(dut):
    """Good CRC, but UDP length runs into the FCS: must end bad."""
    await setup(dut)
    for extra in [1, 4, 5, 100]:
        mon = Monitor()
        body = make_body(random.randbytes(100), extra=extra)
        await send_wire(dut, mon, make_wire(body))
        assert mon.eofs == [1], f"extra={extra}: eofs={mon.eofs}"


@cocotb.test()
async def test_back_to_back(dut):
    """Random mix at minimum gap: only the good frames come out, in order."""
    await setup(dut)
    mon = Monitor()
    expected = []
    expected_eofs = []
    for _ in range(50):
        payload = random.randbytes(random.randint(1, 1400))
        kind = random.choice(["good", "good", "bad_crc", "mac", "ip", "port"])
        if kind == "mac":
            body = make_body(payload, mac=OTHER_MAC)
        elif kind == "ip":
            body = make_body(payload, ip=OTHER_IP)
        elif kind == "port":
            body = make_body(payload, port=OTHER_PORT)
        else:
            body = make_body(payload)
        wire = bytearray(make_wire(body))
        if kind == "bad_crc":
            wire[-1] ^= 0x01
        if kind in ("good", "bad_crc"):
            expected += list(payload)
            expected_eofs.append(int(kind == "bad_crc"))
        await send_wire(dut, mon, bytes(wire))
    assert mon.data == expected, "payload stream differs"
    assert mon.eofs == expected_eofs, f"eofs={mon.eofs}"


@cocotb.test()
async def test_latency(dut):
    """A payload byte on gmii_rxd must be on m_data in the same cycle."""
    await setup(dut)
    mon = Monitor()
    payload = random.randbytes(40)
    wire = make_wire(make_body(payload))
    first = len(PREAMBLE) + ETH_HDR + IP_HDR + UDP_HDR
    for byte in wire[:first]:
        await cycle(dut, mon, dv=1, data=byte)
    assert mon.data == [], "header bytes leaked"
    for byte in payload:
        dut.gmii_rx_dv.value = 1
        dut.gmii_rxd.value = byte
        await FallingEdge(dut.gmii_rx_clk)
        assert int(dut.m_valid.value) == 1, f"{byte:#04x}: not valid same cycle"
        assert int(dut.m_data.value) == byte, f"{byte:#04x}: wrong data"
        await RisingEdge(dut.gmii_rx_clk)


async def capture_tx(dut):
    """Record one frame off the TX pins."""
    wire = []
    while True:
        await FallingEdge(dut.gtx_clk)
        if int(dut.gmii_tx_en.value):
            assert int(dut.gmii_tx_er.value) == 0, "gmii_tx_er set"
            wire.append(int(dut.gmii_txd.value))
        elif wire:
            return bytes(wire)


async def transmit(dut, body):
    """Drive one frame into the TX stream, holding each byte until accepted."""
    for i, byte in enumerate(body):
        dut.s_valid.value = 1
        dut.s_data.value = byte
        dut.s_last.value = int(i == len(body) - 1)
        while True:
            await FallingEdge(dut.gtx_clk)
            ready = int(dut.s_ready.value)
            await RisingEdge(dut.gtx_clk)
            if ready:
                break
    dut.s_valid.value = 0
    dut.s_last.value = 0


@cocotb.test()
async def test_tx_to_rx(dut):
    """Our TX output, replayed into our RX, gives back the original payload."""
    await setup(dut)
    for length in [1, 17, 18, 500]:     # below 18, TX must add the padding
        mon = Monitor()
        payload = random.randbytes(length)
        body = make_body(payload)
        capture = cocotb.start_soon(capture_tx(dut))
        await transmit(dut, body[:ETH_HDR + IP_HDR + UDP_HDR + length])
        wire = await capture
        assert wire == make_wire(body), f"len={length}: wire bytes differ"
        await send_wire(dut, mon, wire)
        assert mon.data == list(payload), f"len={length}: payload differs"
        assert mon.eofs == [0], f"len={length}: eofs={mon.eofs}"
