// Ethernet RX module
// github/devanandanj

`default_nettype none

module ethernet_rx (
    input logic gmii_rx_clk,
    input logic reset,

    input logic [7:0] gmii_rxd,    // data rxd
    input logic       gmii_rx_dv,  // data valid
    input logic       gmii_rx_er,  // phy saw line error

    output logic [7:0] m_data,   // data out
    output logic       m_valid,
    output logic       m_bad,    // bad frame
    output logic       m_last    // marks final byte
);

  localparam logic [31:0] CRC_RESIDUE = 32'hDEBB20E3;

  typedef enum logic [1:0] {
    IDLE,
    PREAMBLE,
    DATA,
    DROP
  } states_t;

  states_t state;

  logic [7:0] held_byte;
  logic held_valid;

  logic [31:0] crc_reg;
  logic [31:0] crc_next;
  logic err_seen;

  crc32 u_crc (
      .data_in    (gmii_rxd),
      .crc_current(crc_reg),
      .crc_out    (crc_next)
  );


  always_ff @(posedge gmii_rx_clk) begin : hold_register
    if (reset) begin
      state <= IDLE;
      held_valid <= 1'b0;
      crc_reg <= 32'hFFFFFFFF;
      err_seen <= 1'b0;
      m_data <= '0;
      m_valid <= 1'b0;
      m_last <= 1'b0;
      m_bad <= 1'b0;
    end else begin
      m_valid <= 1'b0;
      m_last  <= 1'b0;
      m_bad   <= 1'b0;
      case (state)
        IDLE: begin
          held_valid <= 1'b0;
          crc_reg    <= 32'hFFFFFFFF;
          err_seen   <= 1'b0;
          if (gmii_rx_dv) begin
            if (gmii_rxd == 8'h55) state <= PREAMBLE;
            else if (gmii_rxd == 8'hD5) state <= DATA;
            else state <= DROP;
          end
        end
        PREAMBLE: begin
          crc_reg <= 32'hFFFFFFFF;
          if (!gmii_rx_dv) state <= IDLE;
          else if (gmii_rxd == 8'hD5) state <= DATA;
          else if (gmii_rxd != 8'h55) state <= DROP;
        end
        DATA: begin
          if (gmii_rx_dv) begin
            if (held_valid) begin
              m_data  <= held_byte;
              m_valid <= 1'b1;
            end
            held_byte <= gmii_rxd;
            held_valid <= 1'b1;
            crc_reg <= crc_next;
            if (gmii_rx_er) err_seen <= 1'b1;
          end else begin
            if (held_valid) begin
              m_data  <= held_byte;
              m_valid <= 1'b1;
              m_last  <= 1'b1;
              m_bad   <= (crc_reg != CRC_RESIDUE) || err_seen;
            end
            held_valid <= 1'b0;
            state <= IDLE;
          end
        end
        DROP: begin
          if (!gmii_rx_dv) state <= IDLE;
        end

        default: state <= IDLE;
      endcase
    end
  end

endmodule

`default_nettype wire
