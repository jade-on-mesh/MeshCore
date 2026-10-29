"""USB packet log: a radio2 (MediaMesh) packet gets a `RADIO: radio2` line of
its own before its RX/TX line, and nothing else changes.

Compiles the real Dispatcher::logPacketLine with small stand-ins, then checks
the lines against the regex meshcoretomqtt (Cisien/meshcoretomqtt,
bridge/message_parser.py) uses: the RX/TX line still parses, the extra line is
ignored by it, and main-radio output is byte-for-byte what it was.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]

# meshcoretomqtt's patterns, verbatim (bridge/message_parser.py @ 9b4e022).
MCTOMQTT_PACKET = re.compile(
    r"(\d{2}:\d{2}:\d{2}) - (\d{1,2}/\d{1,2}/\d{4}) U: (RX|TX), len=(\d+) \(type=(\d+), route=([A-Z]), payload_len=(\d+)\)"
    r"(?: SNR=(-?\d+) RSSI=(-?\d+) score=(\d+)(?: time=(\d+))?)?"
    r"(?: hash=([0-9A-F]+))?"
    r"(?: \[(.*)\])?$"
)

HARNESS = r'''
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#define MESH_PACKET_LOGGING 1
#define MAX_HASH_SIZE 8
#define PAYLOAD_TYPE_REQ 0
#define PAYLOAD_TYPE_RESPONSE 1
#define PAYLOAD_TYPE_TXT_MSG 2
#define PAYLOAD_TYPE_ADVERT 4
#define PAYLOAD_TYPE_PATH 8
static std::string out;
struct Stream {};
static Stream port;
namespace mesh {
inline Stream& usbLoggingPort() { return port; }
template <size_t CAP = 256> struct SerialLogLine {
  std::string s;
  void printf(const char* f, ...) { char b[CAP]; va_list a; va_start(a, f); vsnprintf(b, sizeof(b), f, a); va_end(a); s += b; }
  void hex(const uint8_t* d, size_t n) { char b[3]; for (size_t i = 0; i < n; i++) { snprintf(b, 3, "%02X", d[i]); s += b; } }
  bool flush(Stream&) { out += s + "\r\n"; return true; }
};
struct Packet {
  uint8_t radio_profile = 0, type = PAYLOAD_TYPE_ADVERT; bool direct = false;
  uint8_t payload[4] = {0xAA, 0xBB, 0, 0}; uint16_t payload_len = 48;
  uint8_t getPayloadType() const { return type; }
  bool isRouteDirect() const { return direct; }
  float getSNR() const { return 9.0f; }
  int getRSSI() const { return -71; }
  void calculatePacketHash(uint8_t* h) const { for (int i = 0; i < MAX_HASH_SIZE; i++) h[i] = uint8_t(0xA0 + i); }
};
struct Dispatcher {
  const char* getLogDateTime() { return "12:34:56 - 29/10/2026 U"; }
  void logPacketLine(const char* direction, const Packet* packet, int len,
                     bool include_rx_metrics, float score, uint32_t air_time);
};
@METHOD@
}
int main() {
  mesh::Dispatcher d;
  mesh::Packet main_rx, r2_rx, r2_tx_direct;
  r2_rx.radio_profile = 1;
  r2_tx_direct.radio_profile = 1; r2_tx_direct.direct = true; r2_tx_direct.type = PAYLOAD_TYPE_TXT_MSG;
  d.logPacketLine("RX", &main_rx, 64, true, 1.0f, 88);
  out += "--\n";
  d.logPacketLine("RX", &r2_rx, 64, true, 1.0f, 88);
  out += "--\n";
  d.logPacketLine("TX", &r2_tx_direct, 64, false, 0.0f, 0);
  fputs(out.c_str(), stdout);
}
'''


class UsbLogRadio2Test(unittest.TestCase):
    def run_harness(self):
        source = (ROOT / "src/Dispatcher.cpp").read_text()
        method = extract_braced(source, "void Dispatcher::logPacketLine(")
        compiler = shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="meshcore-usb-radio2-") as tmp:
            src = Path(tmp) / "log.cpp"
            src.write_text(HARNESS.replace("@METHOD@", method))
            exe = Path(tmp) / "log"
            built = subprocess.run([compiler, "-std=c++17", "-Wall", "-Werror", str(src), "-o", str(exe)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
            self.assertEqual(ran.returncode, 0, ran.stderr)
        blocks, cur = [], []
        for line in ran.stdout.splitlines():
            if line == "--":
                blocks.append(cur); cur = []
            elif line:
                cur.append(line)
        blocks.append(cur)
        return blocks

    def test_radio2_line_precedes_and_main_radio_is_unchanged(self):
        main, r2_rx, r2_tx = self.run_harness()
        main = [l for l in main if l]
        r2_rx = [l for l in r2_rx if l]
        r2_tx = [l for l in r2_tx if l]
        # Main radio: exactly one line, as before.
        self.assertEqual(len(main), 1)
        self.assertNotIn("RADIO", main[0])
        # radio2: the RADIO line, then the same RX line as the main radio.
        self.assertEqual(r2_rx[0], "12:34:56 - 29/10/2026 U RADIO: radio2")
        self.assertEqual(r2_rx[1], main[0])
        self.assertEqual(r2_tx[0], "12:34:56 - 29/10/2026 U RADIO: radio2")
        self.assertTrue(r2_tx[1].startswith("12:34:56 - 29/10/2026 U: TX, len=64"))

    def test_meshcoretomqtt_still_parses_and_skips_the_radio_line(self):
        main, r2_rx, r2_tx = self.run_harness()
        r2_rx = [l for l in r2_rx if l]
        r2_tx = [l for l in r2_tx if l]
        self.assertIsNone(MCTOMQTT_PACKET.match(r2_rx[0]))
        self.assertNotIn("U RAW:", r2_rx[0])
        self.assertFalse(r2_rx[0].startswith("DEBUG"))
        m = MCTOMQTT_PACKET.match(r2_rx[1])
        self.assertIsNotNone(m, r2_rx[1])
        self.assertEqual(m.group(3), "RX")
        self.assertEqual(m.group(12), "A0A1A2A3A4A5A6A7")
        t = MCTOMQTT_PACKET.match(r2_tx[1])
        self.assertIsNotNone(t, r2_tx[1])
        self.assertEqual(t.group(13), "BB -> AA")


if __name__ == "__main__":
    unittest.main()
