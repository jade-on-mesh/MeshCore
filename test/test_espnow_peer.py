"""Exercise saved ESP-NOW destinations, live CLI application and SDK sends."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

STORAGE_CHECKS = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
#include <helpers/CLICommandUtils.h>
#include "ESPNowPeerSettings.h"
#include "settings_under_test.cpp"
struct NodePrefs {bool bridge_enabled=true,espnow_bridge_enabled=true;};
struct Callbacks {
  unsigned restarts=0,stops=0;bool restart_ok=true;
  bool restartEspNowBridge(){++restarts;return restart_ok;}
  bool setEspNowBridgeState(bool enable){assert(!enable);++stops;return true;}
};
struct CommonCLI {
  NodePrefs prefs;Callbacks callbacks;
  NodePrefs* _prefs=&prefs;Callbacks* _callbacks=&callbacks;
  bool handleEspNowPeerCommand(const char*,char*);
};
@CLI_METHOD@

static const uint8_t Peer[]={2,16,32,48,64,80};
static const uint8_t Other[]={4,16,32,48,64,80};
static const uint8_t Broadcast[]={255,255,255,255,255,255};
static void expect(const uint8_t* address) {
  uint8_t actual[6];assert(mesh::bridge::copyEspNowPeer(actual));
  assert(!memcmp(actual,address,6));
}

int main(int argc,char** argv) {
  assert(argc==2);using namespace mesh::bridge;
  MemoryFS fs;const char* path="/espnow_peer";
  const std::vector<uint8_t> legacy={1,8,4,7,9};fs.files["/com_prefs"]=legacy;
  uint8_t output[6]={9,9,9,9,9,9};char reply[160];
  assert(!copyEspNowPeer(output)&&output[0]==9);
  loadEspNowPeerSettings(&fs);expect(Broadcast);
  assert(fs.files.size()==1);
  if(!strcmp(argv[1],"storage")) {
    assert(parseEspNowPeer("02:10:20:30:40:50",output)&&!memcmp(output,Peer,6));
    assert(parseEspNowPeer("aa:bb:cc:dd:ee:fe",output)&&output[0]==0xaa);
    for(const char* invalid:{"","broadcast ","Broadcast","00:00:00:00:00:00",
        "03:10:20:30:40:50","FF:FF:FF:FF:FF:FF","02-10-20-30-40-50",
        "02:10:20:30:40:5Z","02:10:20:30:40:50 trailing","02:10:20:30:40"}) {
      memset(output,9,6);assert(!parseEspNowPeer(invalid,output));
      for(uint8_t value:output)assert(value==9);
    }
    assert(!parseEspNowPeer(nullptr,output)&&!parseEspNowPeer("broadcast",nullptr));
    assert(parseEspNowPeer("broadcast",output)&&!memcmp(output,Broadcast,6));
    assert(saveEspNowPeer(Peer));expect(Peer);const auto good=fs.files.at(path);
    assert(good.size()==14&&!memcmp(good.data(),"ENP\1",4));
    loadEspNowPeerSettings(&fs);expect(Peer);
    formatEspNowPeer(reply,sizeof(reply));assert(!strcmp(reply,"> 02:10:20:30:40:50"));
    char bounded[]={'x','x','x','z'};formatEspNowPeer(bounded,3);
    assert(!bounded[2]&&bounded[3]=='z');
    fs.fail_write=true;assert(!saveEspNowPeer(Other));expect(Peer);
    assert(fs.files.at(path)==good);fs.fail_write=false;
    fs.fail_write_after=4;assert(!saveEspNowPeer(Other));expect(Peer);
    assert(fs.files.at(path)==good);fs.fail_write_after=-1;
    fs.fail_after_publication=true;assert(!saveEspNowPeer(Other));
    assert(!espNowPeerSettingsHealthy()&&!copyEspNowPeer(output));
    const auto published=fs.files.at(path);assert(published!=good);
    fs.fail_after_publication=false;fs.fail_read_open=false;
    assert(!saveEspNowPeer(Peer)&&fs.files.at(path)==published);
    loadEspNowPeerSettings(&fs);expect(Other);assert(saveEspNowPeer(Peer));
    for(size_t bit=0;bit<good.size()*8;++bit) {
      fs.files[path]=good;fs.files[path][bit/8]^=uint8_t(1U<<(bit%8));
      loadEspNowPeerSettings(&fs);assert(!copyEspNowPeer(output));
    }
    assert(saveEspNowPeer(Peer));
    for(size_t size=0;size<good.size();++size) {
      fs.files[path]={good.begin(),good.begin()+size};
      loadEspNowPeerSettings(&fs);assert(!copyEspNowPeer(output));
    }
    assert(saveEspNowPeer(Peer));fs.files[path].push_back(0);
    loadEspNowPeerSettings(&fs);assert(!copyEspNowPeer(output));assert(saveEspNowPeer(Peer));
    fs.fail_read_open=true;loadEspNowPeerSettings(&fs);assert(!copyEspNowPeer(output));
    fs.fail_read_open=false;assert(!saveEspNowPeer(Other)&&fs.files.at(path)==good);
    loadEspNowPeerSettings(&fs);expect(Peer);
    fs.fail_read_after=4;loadEspNowPeerSettings(&fs);assert(!copyEspNowPeer(output));
    fs.fail_read_after=-1;assert(!saveEspNowPeer(Other));loadEspNowPeerSettings(&fs);
    fs.fail_metadata=true;loadEspNowPeerSettings(&fs);assert(!copyEspNowPeer(output));
    fs.fail_metadata=false;assert(!saveEspNowPeer(Other));loadEspNowPeerSettings(&fs);
    fs.files["/espnow_peer.bak"]=good;fs.files.erase(path);
    loadEspNowPeerSettings(&fs);expect(Peer);assert(fs.files.at(path)==good);
    fs.files["/espnow_peer.bak"]=good;fs.files.erase(path);fs.fail_rename=1;
    loadEspNowPeerSettings(&fs);assert(!copyEspNowPeer(output));
    assert(fs.files.at("/espnow_peer.bak")==good&&!saveEspNowPeer(Other));
    loadEspNowPeerSettings(&fs);expect(Peer);
    loadEspNowPeerSettings(nullptr);assert(!copyEspNowPeer(output)&&!saveEspNowPeer(Other));
  } else {
    CommonCLI cli;
    auto run=[&](const char* command){strcpy(reply,"untouched");return cli.handleEspNowPeerCommand(command,reply);};
    assert(run("get espnow.peer")&&!strcmp(reply,"> broadcast"));
    for(const char* command:{"set espnow.peer","set espnow.peer invalid","get espnow.peer extra"})
      assert(run(command)&&!strncmp(reply,"Error:",6));
    assert(!run("get espnow.peerXYZ")&&!strcmp(reply,"untouched"));
    assert(run("set espnow.peer 02:10:20:30:40:50")&&!strncmp(reply,"OK",2));
    expect(Peer);assert(cli.callbacks.restarts==1);
    assert(run("set espnow.peer 02:10:20:30:40:50")&&strstr(reply,"unchanged"));
    assert(cli.callbacks.restarts==1);
    const auto good=fs.files.at(path);
    fs.fail_write=true;assert(run("set espnow.peer broadcast")&&!strncmp(reply,"Error:",6));
    expect(Peer);assert(fs.files.at(path)==good&&cli.callbacks.restarts==1&&cli.callbacks.stops==0);
    fs.fail_write=false;cli.callbacks.restart_ok=false;
    assert(run("set espnow.peer 04:10:20:30:40:50")&&strstr(reply,"failed to restart"));
    expect(Other);assert(cli.callbacks.restarts==2&&cli.callbacks.stops==1);
    cli.callbacks.restart_ok=true;cli.prefs.bridge_enabled=cli.prefs.espnow_bridge_enabled=false;
    assert(run("set espnow.peer\tbroadcast")&&!strncmp(reply,"OK",2));
    expect(Broadcast);assert(cli.callbacks.restarts==2);
    fs.fail_after_publication=true;
    assert(run("set espnow.peer 02:10:20:30:40:50")&&strstr(reply,"blocked"));
    assert(!espNowPeerSettingsHealthy()&&cli.callbacks.stops==2);
    assert(run("get espnow.peer")&&strstr(reply,"blocked"));
  }
  assert(fs.files.at("/com_prefs")==legacy);
}
'''

SDK_CHECKS = r'''
int main(){
 Backend backend;mesh::wireless::control().begin(backend);
 NodePrefs prefs;prefs.bridge_format=mesh::bridge::ESPNOW_FORMAT_WRAPPED;
 mesh::PacketManager mgr;mesh::RTCClock rtc;
 auto p=packet(0x40);
 std::vector<uint8_t> legacy;
 { ESPNowBridge bridge(&prefs,&mgr,&rtc);bridge.begin();
   assert(bridge._initialized&&ps_writes==1&&wifi_ps==WIFI_PS_NONE);
   assert(added_peers.back()[0]==255);
   bridge.sendPacket(&p);bridge.loop();complete(bridge);
   assert(sent.size()==1&&sent_peers.back()[0]==255);legacy=sent.back();bridge.end(); }
 const uint8_t destination[]={2,16,32,48,64,80};
 memcpy(mesh::bridge::configured_peer,destination,6);
 { ESPNowBridge bridge(&prefs,&mgr,&rtc);bridge.begin();
   assert(bridge._initialized&&!memcmp(added_peers.back().data(),destination,6));
   bridge.sendPacket(&p);bridge.loop();
   assert(sent.back()==legacy&&!memcmp(sent_peers.back().data(),destination,6));
   const unsigned initial=send_calls;
   for(unsigned attempt=0;attempt<3;++attempt){
     complete(bridge,ESP_NOW_SEND_FAIL);assert(unsigned(send_calls)==initial+attempt);
     now_ms+=19;bridge.loop();assert(unsigned(send_calls)==initial+attempt);
     ++now_ms;bridge.loop();assert(unsigned(send_calls)==initial+attempt+1);
   }
   complete(bridge,ESP_NOW_SEND_FAIL);assert(!bridge._tx_count);
   assert(bridge._stats.tx.callback_fail==4&&bridge._stats.tx.drops==1);
   bridge.end();assert(!memcmp(removed_peers.back().data(),destination,6)); }
 // A failed first raw fragment retries before its sibling, to the same peer.
 prefs.bridge_format=mesh::bridge::ESPNOW_FORMAT_RAW;
 { ESPNowBridge bridge(&prefs,&mgr,&rtc);bridge.begin();auto large=packet(0x44,255);
   const size_t first=sent.size();bridge.sendPacket(&large);bridge.loop();
   assert(sent.size()==first+1);const auto first_frame=sent.back();
   complete(bridge,ESP_NOW_SEND_FAIL);assert(sent.size()==first+1);
   now_ms+=20;bridge.loop();assert(sent.size()==first+2&&sent.back()==first_frame);
   complete(bridge);assert(sent.size()==first+3&&sent.back()!=first_frame);
   complete(bridge);assert(!bridge._tx_count);
   for(size_t i=first;i<sent_peers.size();++i)assert(!memcmp(sent_peers[i].data(),destination,6));
   bridge.end(); }
 // An unreadable saved peer cannot silently fall back to broadcast.
 mesh::bridge::peer_settings_ready=false;
 { ESPNowBridge bridge(&prefs,&mgr,&rtc);const auto before=added_peers.size();bridge.begin();
   assert(!bridge._initialized&&added_peers.size()==before&&!espnow_active);
   assert(bridge._stats.error.stage==mesh::bridge::diag::Stage::PeerConfig); }
 mesh::bridge::peer_settings_ready=true;
 // Shared WiFi owns its modem policy; bridge startup must leave it alone.
 backend.wifi=true;sdk_initialized=sdk_started=true;sdk_mode=WIFI_STA;
 wifi_ps=WIFI_PS_MIN_MODEM;const unsigned previous_ps=ps_writes;
 { ESPNowBridge bridge(&prefs,&mgr,&rtc);bridge.begin();
   assert(bridge._initialized&&ps_writes==previous_ps&&wifi_ps==WIFI_PS_MIN_MODEM);
   bridge.end();assert(sdk_started&&wifi_ps==WIFI_PS_MIN_MODEM); }
 backend.wifi=false;failure=19;
 { ESPNowBridge bridge(&prefs,&mgr,&rtc);bridge.begin();
   assert(!bridge._initialized&&!espnow_active&&!sdk_initialized);
   assert(bridge._stats.error.stage==mesh::bridge::diag::Stage::WiFiPowerSave); }
}
'''


class EspNowPeerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = os.environ.get("CXX") or shutil.which("g++") or "c++"
        cls.flags = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                      "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else [])

    def compile(self, source, executable, includes, defines=()):
        result = subprocess.run([self.compiler, "-std=c++17", "-O1", "-Wall", "-Wextra",
            "-Wno-sign-compare", *self.flags, *["-D"+d for d in defines],
            *["-I"+str(p) for p in includes], str(source), "-o", str(executable)],
            capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_storage_parser_and_cli_use_real_transaction_and_command(self):
        from test_radio_receive_contract import method
        with tempfile.TemporaryDirectory(prefix="espnow-peer-settings-") as tmp:
            folder = Path(tmp)
            (folder / "helpers").mkdir()
            mock = (ROOT / "test/fixtures/radio_profiles/mocks/helpers/IdentityStore.h").read_text()
            mock = mock.replace("  bool fail_read_open = false;", "  bool fail_read_open = false;\n"
                "  bool fail_after_publication = false;\n  bool fail_metadata = false;")
            mock = mock.replace("    files[to] = files[from]; files.erase(from); return true;",
                '    files[to] = files[from]; files.erase(from);\n'
                '    if(fail_after_publication && !strcmp(to,"/espnow_peer")) fail_read_open=true;\n'
                '    return true;')
            (folder / "IdentityStore.h").write_text(mock)
            (folder / "helpers/IdentityStore.h").write_text('#include "../IdentityStore.h"\n')
            (folder / "FilePresence.h").write_text('''#pragma once
#include "IdentityStore.h"
namespace mesh {template<class FS> bool filePresence(FS* fs,const char* path,bool& present) {
  if(!fs||!path||fs->fail_metadata)return false;present=fs->exists(path);return true;
}}
''')
            for name in ("ESPNowPeerSettings.h", "ContactFileTransaction.h", "CheckedSettingsFile.h"):
                (folder / name).write_bytes((ROOT / "src/helpers" / name).read_bytes())
            (folder / "settings_under_test.cpp").write_bytes((ROOT / "src/helpers/ESPNowPeerSettings.cpp").read_bytes())
            cli = method((ROOT / "src/helpers/CommonCLI.cpp").read_text(), "bool CommonCLI::handleEspNowPeerCommand(")
            source = folder / "test.cpp"
            source.write_text(STORAGE_CHECKS.replace("@CLI_METHOD@", cli))
            for combined in (False, True):
                binary = folder / ("combined" if combined else "standalone")
                defines = ["ESP32_PLATFORM=1", "WITH_ESPNOW_BRIDGE=1"]
                if combined:
                    defines.append("WITH_RS232_BRIDGE=1")
                self.compile(source, binary, [folder, ROOT / "src", ROOT / "src/helpers"], defines)
                for scenario in ("storage", "cli"):
                    result = subprocess.run([str(binary), scenario], capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_actual_sdk_peer_send_retry_and_power_policy_across_versions(self):
        from test_bridge_recovery import code, COMMON
        with tempfile.TemporaryDirectory(prefix="espnow-unicast-sdk-") as tmp:
            folder = Path(tmp)
            source = folder / "test.cpp"
            source.write_text(code()+COMMON+SDK_CHECKS)
            for version in (40400, 50200, 50500):
                binary = folder / ("sdk-"+str(version))
                self.compile(source, binary, [ROOT / "src"], ["ESP32=1", "WITH_ESPNOW_BRIDGE=1",
                    "WITH_RS232_BRIDGE=1", "ESP_IDF_VERSION="+str(version),
                    "ESP_IDF_VERSION_MAJOR="+str(version//10000)])
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_non_espnow_build_has_no_storage_or_peer_symbols(self):
        with tempfile.TemporaryDirectory(prefix="no-espnow-peer-") as tmp:
            obj = Path(tmp) / "peer.o"
            result = subprocess.run([self.compiler, "-std=c++17", "-DNRF52_PLATFORM=1", "-c",
                str(ROOT / "src/helpers/ESPNowPeerSettings.cpp"), "-o", str(obj)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.check_output(["nm", "-C", str(obj)], text=True)
            self.assertNotRegex(symbols, r"EspNowPeer|settings_fs|selected|healthy")


if __name__ == "__main__":
    unittest.main()
