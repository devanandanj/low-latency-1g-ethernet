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

  typedef enum logic [1:0] {
    IDLE,
    PREAMBLE,
    DATA,
    DROP
  } states_t;

  states_t state;

  always_ff @(posedge gmii_rx_clk) begin : state_machine

    if (reset) begin
      state <= IDLE;
    end else begin
      case (state)
        IDLE: begin
          if (gmii_rx_dv) begin
            if (gmii_rxd == 8'h55) state <= PREAMBLE;
            else if (gmii_rxd == 8'hD5) state <= DATA;
            else state <= DROP;
          end
        end

        PREAMBLE: begin
          if (!gmii_rx_dv) state <= IDLE;
          else if (gmii_rxd == 8'hD5) state <= DATA;
          else if (gmii_rxd != 8'h55) state <= DROP;
        end

        DATA: begin
          if (!gmii_rx_dv) state <= IDLE;
        end

        DROP: begin
          if (!gmii_rx_dv) state <= IDLE;
        end
        default: state <= IDLE;

      endcase
    end
  end
  assign m_data  = '0;
  assign m_valid = 1'b0;
  assign m_bad   = 1'b0;
  assign m_last  = 1'b0;

endmodule

`default_nettype wire
