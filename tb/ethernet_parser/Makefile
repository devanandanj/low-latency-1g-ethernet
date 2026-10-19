SIM ?= verilator
TOPLEVEL_LANG = verilog
VERILOG_SOURCES = $(CURDIR)/../../rtl/ethernet_parser.sv
TOPLEVEL = ethernet_parser
MODULE = test_ethernet_parser
EXTRA_ARGS += --trace-fst

include $(shell cocotb-config --makefiles)/Makefile.sim
