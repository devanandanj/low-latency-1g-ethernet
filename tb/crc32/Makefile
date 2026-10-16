SIM ?= verilator
TOPLEVEL_LANG = verilog
VERILOG_SOURCES = $(CURDIR)/../../rtl/crc32.sv
TOPLEVEL = crc32
MODULE = test_crc32
EXTRA_ARGS += --trace-fst

include $(shell cocotb-config --makefiles)/Makefile.sim
