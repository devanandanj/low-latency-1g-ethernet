/*
 *
 *   Ethernet Parser
 *   github/devanandanj
 *
 *
 */

`default_nettype none

module ethernet_parser (

    input logic gmii_rx_clk,
    input logic reset,

    input logic [47:0]cfg_mac,

    input logic [7:0] s_data,
    input logic       s_valid,
    input logic       s_eof,
    input logic       s_bad,

    output logic [7:0] m_data,
    output logic       m_valid,
    output logic       m_eof,
    output logic       m_bad
  );

  localparam logic[3:0] PAYLOAD  = 4'd14;

  logic[3:0] count;
  logic      mac_ok;
  logic      type_ok;
  logic[7:0] mac_byte;
  logic      keep;

  always_comb begin
    case (count)
      4'd0: mac_byte = cfg_mac[47:40];
      4'd1: mac_byte = cfg_mac[39:32];
      4'd2: mac_byte = cfg_mac[31:24];
      4'd3: mac_byte = cfg_mac[23:16];
      4'd4: mac_byte = cfg_mac[15:8];
      4'd5: mac_byte = cfg_mac[7:0];
      default: mac_byte = '0;
    endcase
  end

  always_ff @( posedge gmii_rx_clk ) begin : header_check
    if (reset || s_eof) begin
      count <= '0;
      mac_ok <= 1'b1;
      type_ok <= 1'b1;
    end else if (s_valid) begin
      if (count < PAYLOAD) count <= count + 1'b1;
      if (count < 4'd6 && s_data != mac_byte) mac_ok <= 1'b0;
      if (count == 4'd12 && s_data != 8'h08) type_ok <= 1'b0;
      if (count == 4'd13 && s_data != 8'h00) type_ok <= 1'b0;
    end
  end

  assign keep = (count == PAYLOAD) && mac_ok && type_ok;

  assign m_data  = s_data;
  assign m_valid = s_valid && keep;
  assign m_eof   = s_eof && keep;
  assign m_bad   = s_bad;

endmodule

`default_nettype wire
