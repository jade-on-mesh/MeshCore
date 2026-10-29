"""USB packet log: a repeater or room server that receives a packet on radio2
(MediaMesh) prints `RADIO: radio2` between the packet's RAW and RX lines, and
nothing else changes.

Compiles the real MyMesh::logRxRaw of both roles with small stand-ins, then
checks the lines against the patterns meshcoretomqtt (Cisien/meshcoretomqtt,
bridge/message_parser.py) uses: its RAW handling and RX pattern are untouched,
and the extra line matches neither. The shared Dispatcher (and so every
Companion build) must not carry the marker.
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
#include <string>
#define MESH_PACKET_LOGGING 1
#define MESH_PACKET_LOGGING_COMPACT 0
static std::string out;
struct Stream {};
static Stream port;
namespace mesh {
inline Stream& usbLoggingPort() { return port; }
inline bool isUsbPacketLoggingAllowed() { return true; }
inline bool serialLogCompactPacket(Stream&, char, const uint8_t*, size_t) { return true; }
template <size_t CAP = 256> struct SerialLogLine {
  std::string s;
  void printf(const char* f, ...) { char b[CAP]; va_list a; va_start(a, f); vsnprintf(b, sizeof(b), f, a); va_end(a); s += b; }
  void hex(const uint8_t* d, size_t n) { char b[3]; for (size_t i = 0; i < n; i++) { snprintf(b, 3, "%02X", d[i]); s += b; } }
  bool flush(Stream&) { out += s + "\n"; return true; }
};
}
struct Radio { uint8_t profile = 0; uint8_t receiveProfile() const { return profile; } };
struct MyMesh {
  Radio radio; Radio* _radio = &radio;
  const char* getLogDateTime() { return "12:34:56 - 29/10/2026 U"; }
  void logRxRaw(float snr, float rssi, const uint8_t raw[], int len);
};
@METHOD@
int main() {
  MyMesh m;
  const uint8_t raw[] = {0x15, 0xA3, 0x01};
  m.logRxRaw(9.0f, -71.0f, raw, sizeof(raw));
  out += "--\n";
  m.radio.profile = 1;
  m.logRxRaw(9.0f, -71.0f, raw, sizeof(raw));
  fputs(out.c_str(), stdout);
}
'''


class UsbLogRadio2Test(unittest.TestCase):
    def run_role(self, role):
        source = (ROOT / "examples" / role / "MyMesh.cpp").read_text()
        method = extract_braced(source, "void MyMesh::logRxRaw(")
        compiler = shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="meshcore-usb-radio2-") as tmp:
            src = Path(tmp) / "log.cpp"
            src.write_text(HARNESS.replace("@METHOD@", method))
            exe = Path(tmp) / "log"
            built = subprocess.run([compiler, "-std=c++17", "-Wall", "-Werror", "-Wno-unused-parameter",
                                    str(src), "-o", str(exe)], capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
            self.assertEqual(ran.returncode, 0, ran.stderr)
        main, radio2 = ran.stdout.split("--\n")
        return main.splitlines(), radio2.splitlines()

    def check_role(self, role):
        main, radio2 = self.run_role(role)
        # Main radio: just the RAW line, as before.
        self.assertEqual(main, ["12:34:56 - 29/10/2026 U RAW: 15A301"])
        # radio2: the same RAW line, then the marker.
        self.assertEqual(radio2, ["12:34:56 - 29/10/2026 U RAW: 15A301",
                                  "12:34:56 - 29/10/2026 U RADIO: radio2"])
        marker = radio2[1]
        # meshcoretomqtt: not a packet, not RAW, not DEBUG, so it is skipped.
        self.assertIsNone(MCTOMQTT_PACKET.match(marker))
        self.assertNotIn("U RAW:", marker)
        self.assertFalse(marker.startswith("DEBUG"))

    def test_repeater(self):
        self.check_role("simple_repeater")

    def test_room_server(self):
        self.check_role("simple_room_server")

    def test_shared_dispatcher_and_companions_are_unchanged(self):
        # Full Companion images are packed to the byte; the marker lives only
        # in the repeater and room server hooks.
        self.assertNotIn("RADIO: radio2", (ROOT / "src/Dispatcher.cpp").read_text())
        for path in (ROOT / "examples/companion_radio").rglob("*.cpp"):
            self.assertNotIn("RADIO: radio2", path.read_text(errors="ignore"), str(path))


if __name__ == "__main__":
    unittest.main()
