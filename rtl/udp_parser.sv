/*
 *
 *   UDP Parser
 *   github/devanandanj
 *
 *
 */

`default_nettype none

module udp_parser (

    input logic gmii_rx_clk,
    input logic reset,

    input logic [15:0] cfg_port,

    input logic [7:0] s_data,
    input logic       s_valid,
    input logic       s_eof,
    input logic       s_bad,

    output logic [7:0] m_data,
    output logic       m_valid,
    output logic       m_eof,
    output logic       m_bad
);

  localparam logic [3:0] PAYLOAD = 4'd8;
  localparam logic [2:0] FCS_LEN = 3'd4;

  logic [ 3:0] count;
  logic        port_ok;
  logic        len_ok;
  logic        keep;

  logic [ 7:0] len_hi;  // high byte
  logic [15:0] remaining; // payload bytes left
  logic [ 2:0] trailer;  // bytes after the payload, stops at FCS_LEN

  always_ff @(posedge gmii_rx_clk) begin : header_check
    if (reset || s_eof) begin
      count   <= '0;
      port_ok <= 1'b1;
      len_ok  <= 1'b1;
      trailer <= '0;
    end else if (s_valid) begin
      if (count < PAYLOAD) count <= count + 1'b1;
      if (count == 4'd2 && s_data != cfg_port[15:8]) port_ok <= 1'b0;
      if (count == 4'd3 && s_data != cfg_port[7:0]) port_ok <= 1'b0;
      if (count == 4'd4) len_hi <= s_data;
      if (count == 4'd5) remaining <= {len_hi, s_data} - 16'd8;
      if (count == 4'd5 && {len_hi, s_data} < 16'd8) len_ok <= 1'b0;
      if (count == PAYLOAD && remaining != 0) remaining <= remaining - 1'b1;
      if (count == PAYLOAD && remaining == 0 && trailer < FCS_LEN) trailer <= trailer + 1'b1;
    end
  end

  assign keep = (count == PAYLOAD) && port_ok && len_ok;

  assign m_data = s_data;
  assign m_valid = s_valid && keep && (remaining != 0);
  assign m_eof = s_eof && keep;
  // Fewer than 4 bytes after the payload: UDP length ran into the FCS
  assign m_bad = s_bad || (trailer < FCS_LEN);

endmodule

`default_nettype wire
