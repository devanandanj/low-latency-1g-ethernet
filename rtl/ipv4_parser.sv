/*
 *
 *   IPV4 Parser
 *   github/devanandanj
 *
 *
 */

`default_nettype none

module ipv4_parser (

    input logic gmii_rx_clk,
    input logic reset,

    input logic [31:0] cfg_ip,

    input logic [7:0] s_data,
    input logic       s_valid,
    input logic       s_eof,
    input logic       s_bad,

    output logic [7:0] m_data,
    output logic       m_valid,
    output logic       m_eof,
    output logic       m_bad
);

  localparam logic [4:0] PAYLOAD = 5'd20;

  logic [ 4:0] count;
  logic        ip_ok;
  logic        hdr_ok;
  logic [ 7:0] ip_byte;
  logic        keep;

  logic [ 7:0] hi_byte;
  logic [15:0] sum;
  logic [16:0] add;
  assign add = sum + {hi_byte, s_data};

  always_comb begin
    case (count)
      5'd16:   ip_byte = cfg_ip[31:24];
      5'd17:   ip_byte = cfg_ip[23:16];
      5'd18:   ip_byte = cfg_ip[15:8];
      5'd19:   ip_byte = cfg_ip[7:0];
      default: ip_byte = '0;
    endcase
  end

  always_ff @(posedge gmii_rx_clk) begin : header_check
    if (reset || s_eof) begin
      count  <= '0;
      ip_ok  <= 1'b1;
      hdr_ok <= 1'b1;
      sum    <= '0;
    end else if (s_valid) begin
      if (count < PAYLOAD) count <= count + 1'b1;
      if (count == 5'd0 && s_data != 8'h45) hdr_ok <= 1'b0;  // IPv4, no options
      if (count == 5'd6 && (s_data & 8'h3F) != 0) hdr_ok <= 1'b0;  // not fragmented
      if (count == 5'd7 && s_data != 8'h00) hdr_ok <= 1'b0;
      if (count == 5'd9 && s_data != 8'h11) hdr_ok <= 1'b0;  // UDP
      if (count >= 5'd16 && count <= 5'd19 && s_data != ip_byte) ip_ok <= 1'b0;

      if (count < PAYLOAD) begin
        if (!count[0]) hi_byte <= s_data;
        else sum <= add[15:0] + {15'd0, add[16]};  // carry warps
      end
    end
  end

  assign keep = (count == PAYLOAD) && ip_ok && hdr_ok && (sum == 16'hFFFF);

  assign m_data = s_data;
  assign m_valid = s_valid && keep;
  assign m_eof = s_eof && keep;
  assign m_bad = s_bad;

endmodule

`default_nettype wire
