SIM ?= verilator
TOPLEVEL_LANG = verilog
VERILOG_SOURCES = $(CURDIR)/../../rtl/crc32.sv $(CURDIR)/../../rtl/ethernet_tx.sv $(CURDIR)/../../rtl/ethernet_rx.sv $(CURDIR)/tx_rx_loopback.sv
TOPLEVEL = tx_rx_loopback
MODULE = test_ethernet_tx
EXTRA_ARGS += --trace-fst

include $(shell cocotb-config --makefiles)/Makefile.sim
