SIM ?= verilator
TOPLEVEL_LANG = verilog
RTL = $(CURDIR)/../../rtl
VERILOG_SOURCES = $(RTL)/crc32.sv $(RTL)/ethernet_rx.sv $(RTL)/ethernet_tx.sv $(RTL)/ethernet_parser.sv $(RTL)/ipv4_parser.sv $(RTL)/udp_parser.sv $(RTL)/eth_stack.sv
TOPLEVEL = eth_stack
MODULE = test_eth_stack
EXTRA_ARGS += --trace-fst

include $(shell cocotb-config --makefiles)/Makefile.sim
