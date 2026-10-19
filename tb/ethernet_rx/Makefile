SIM ?= verilator
TOPLEVEL_LANG = verilog
VERILOG_SOURCES = $(CURDIR)/../../rtl/crc32.sv $(CURDIR)/../../rtl/ethernet_rx.sv
TOPLEVEL = ethernet_rx
MODULE = test_ethernet_rx
EXTRA_ARGS += --trace-fst

include $(shell cocotb-config --makefiles)/Makefile.sim
