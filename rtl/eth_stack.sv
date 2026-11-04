/*
 *
 *   Ethernet stack top level
 *   github/devanandanj
 *
 *
 */

`default_nettype none

module eth_stack (
    input logic gmii_rx_clk,
    input logic gtx_clk,
    input logic reset,

    input logic [47:0] cfg_mac,
    input logic [31:0] cfg_ip,
    input logic [15:0] cfg_port,

    input logic [7:0] gmii_rxd,
    input logic       gmii_rx_dv,
    input logic       gmii_rx_er,

    output logic [7:0] m_data,   // UDP payload
    output logic       m_valid,
    output logic       m_eof,
    output logic       m_bad,

    input  logic [7:0] s_data,   // frame to send, without FCS
    input  logic       s_valid,
    input  logic       s_last,
    output logic       s_ready,

    output logic [7:0] gmii_txd,
    output logic       gmii_tx_en,
    output logic       gmii_tx_er
);

  logic [7:0] mac_data;
  logic       mac_valid;
  logic       mac_eof;
  logic       mac_bad;

  logic [7:0] eth_data;
  logic       eth_valid;
  logic       eth_eof;
  logic       eth_bad;

  logic [7:0] ip_data;
  logic       ip_valid;
  logic       ip_eof;
  logic       ip_bad;

  ethernet_rx u_rx (
      .gmii_rx_clk,
      .reset,
      .gmii_rxd,
      .gmii_rx_dv,
      .gmii_rx_er,
      .m_data (mac_data),
      .m_valid(mac_valid),
      .m_bad  (mac_bad),
      .m_eof  (mac_eof)
  );

  ethernet_parser u_eth (
      .gmii_rx_clk,
      .reset,
      .cfg_mac,
      .s_data (mac_data),
      .s_valid(mac_valid),
      .s_eof  (mac_eof),
      .s_bad  (mac_bad),
      .m_data (eth_data),
      .m_valid(eth_valid),
      .m_eof  (eth_eof),
      .m_bad  (eth_bad)
  );

  ipv4_parser u_ipv4 (
      .gmii_rx_clk,
      .reset,
      .cfg_ip,
      .s_data (eth_data),
      .s_valid(eth_valid),
      .s_eof  (eth_eof),
      .s_bad  (eth_bad),
      .m_data (ip_data),
      .m_valid(ip_valid),
      .m_eof  (ip_eof),
      .m_bad  (ip_bad)
  );

  udp_parser u_udp (
      .gmii_rx_clk,
      .reset,
      .cfg_port,
      .s_data (ip_data),
      .s_valid(ip_valid),
      .s_eof  (ip_eof),
      .s_bad  (ip_bad),
      .m_data,
      .m_valid,
      .m_eof,
      .m_bad
  );

  ethernet_tx u_tx (.*);

endmodule

`default_nettype wire
