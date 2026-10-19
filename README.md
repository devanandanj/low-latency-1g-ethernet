# Low Latency 1G-Ethernet Implementation

Purpose: To be used in a NASDAQ ITCH Orderbook replication engine.

---

### Interface :
 - GMII, 8 bit data at 125 MHz

### Tools :
 - SystemVerilog RTL
 - cocotb 1.9.2 + Verilator 5.02 for verification
 - Data feed ITCH 5.0 sample data

### Ethernet RX
 - No runt check: frames shorter than 64 bytes but with a valid CRC aren’t flagged.
 - No maximum-length check.
