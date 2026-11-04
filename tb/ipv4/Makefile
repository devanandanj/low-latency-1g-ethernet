SIM ?= verilator
TOPLEVEL_LANG = verilog
VERILOG_SOURCES = $(CURDIR)/../../rtl/ipv4_parser.sv
TOPLEVEL = ipv4_parser
MODULE = test_ipv4_parser
EXTRA_ARGS += --trace-fst

include $(shell cocotb-config --makefiles)/Makefile.sim
