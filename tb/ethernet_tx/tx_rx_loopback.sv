// Test wrapper: TX output wired into RX, so every test also checks that
// the two MACs agree on the frame format.

`default_nettype none

module tx_rx_loopback (
    input logic gtx_clk,
    input logic reset,

    input  logic [7:0] s_data,
    input  logic       s_valid,
    input  logic       s_last,
    output logic       s_ready,

    output logic [7:0] gmii_txd,
    output logic       gmii_tx_en,
    output logic       gmii_tx_er,

    output logic [7:0] m_data,
    output logic       m_valid,
    output logic       m_eof,
    output logic       m_bad
);

  ethernet_tx u_tx (.*);

  ethernet_rx u_rx (
      .gmii_rx_clk(gtx_clk),
      .reset,
      .gmii_rxd   (gmii_txd),
      .gmii_rx_dv (gmii_tx_en),
      .gmii_rx_er (gmii_tx_er),
      .m_data,
      .m_valid,
      .m_eof,
      .m_bad
  );

endmodule

`default_nettype wire
