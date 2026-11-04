/*
 *
 *   Ethernet TX module
 *   github/devanandanj
 *
 *
 */

`default_nettype none

module ethernet_tx (
    input logic gtx_clk,
    input logic reset,

    input  logic [7:0] s_data,
    input  logic       s_valid,
    input  logic       s_last,
    output logic       s_ready,

    output logic [7:0] gmii_txd,
    output logic       gmii_tx_en,
    output logic       gmii_tx_er
);

  localparam logic [5:0] MIN_LEN = 6'd60;

  typedef enum logic [2:0] {
    IDLE,
    PREAMBLE,
    DATA,
    PAD,
    FCS,
    IFG
  } states_t;

  states_t state;

  logic [3:0] count;
  logic [5:0] frame_len;

  logic [31:0] crc_reg;
  logic [31:0] crc_next;
  logic [31:0] fcs;

  crc32 u_crc (
      .data_in    ((state == PAD) ? 8'h00 : s_data),
      .crc_current(crc_reg),
      .crc_out    (crc_next)
  );

  assign fcs     = ~crc_reg;
  assign s_ready = (state == DATA);

  always_ff @(posedge gtx_clk) begin : tx_fsm
    if (reset) begin
      state      <= IDLE;
      count      <= '0;
      frame_len  <= '0;
      crc_reg    <= 32'hFFFFFFFF;
      gmii_txd   <= '0;
      gmii_tx_en <= 1'b0;
      gmii_tx_er <= 1'b0;
    end else begin
      gmii_tx_er <= 1'b0;
      case (state)
        IDLE: begin
          crc_reg   <= 32'hFFFFFFFF;
          frame_len <= '0;
          if (s_valid) begin
            gmii_txd   <= 8'h55;
            gmii_tx_en <= 1'b1;
            count      <= 4'd1;
            state      <= PREAMBLE;
          end
        end

        PREAMBLE: begin
          gmii_txd <= (count == 4'd7) ? 8'hD5 : 8'h55;
          count    <= count + 1'b1;
          if (count == 4'd7) begin
            count <= '0;
            state <= DATA;
          end
        end

        DATA: begin
          if (s_valid) begin
            gmii_txd <= s_data;
            crc_reg  <= crc_next;
            if (frame_len < MIN_LEN) frame_len <= frame_len + 1'b1;
            if (s_last) state <= (frame_len + 6'd1 < MIN_LEN) ? PAD : FCS;
          end else begin
            gmii_tx_er <= 1'b1;
          end
        end

        PAD: begin
          gmii_txd  <= 8'h00;
          crc_reg   <= crc_next;
          frame_len <= frame_len + 1'b1;
          if (frame_len + 6'd1 == MIN_LEN) state <= FCS;
        end

        FCS: begin
          case (count)
            4'd0:    gmii_txd <= fcs[7:0];
            4'd1:    gmii_txd <= fcs[15:8];
            4'd2:    gmii_txd <= fcs[23:16];
            default: gmii_txd <= fcs[31:24];
          endcase
          count <= count + 1'b1;
          if (count == 4'd3) begin
            count <= '0;
            state <= IFG;
          end
        end

        IFG: begin
          gmii_tx_en <= 1'b0;
          count      <= count + 1'b1;
          if (count == 4'd11) begin
            count <= '0;
            state <= IDLE;
          end
        end

        default: state <= IDLE;
      endcase
    end
  end

endmodule

`default_nettype wire
