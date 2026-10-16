// CRC Module
// github/devanandanj

`default_nettype none

module crc32 (
    input  logic [ 7:0] data_in,
    input  logic [31:0] crc_current,
    output logic [31:0] crc_out
);


  always_comb begin : crc_logic
    logic [31:0] crc_temp;
    crc_temp = crc_current;
    for (int i = 0; i < 8; i++) begin
      if (crc_temp[0] ^ data_in[i]) crc_temp = (crc_temp >> 1) ^ 32'hEDB88320;
      else crc_temp = crc_temp >> 1;
    end
    crc_out = crc_temp;
  end

endmodule
`default_nettype wire
