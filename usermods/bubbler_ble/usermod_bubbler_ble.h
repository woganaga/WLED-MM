#pragma once

/*
 * BubblerTotem Web-BLE bridge usermod (WLEDMM/Bubbler fork).
 *
 * Exposes a minimal GATT service so a Web Bluetooth page can control the
 * totem without WiFi:
 *   - RX characteristic (write): a small WLED JSON-API state command,
 *     e.g. {"on":false} / {"ps":3} / {"bri":128} /
 *     {"MultiRelay":{"relay":0,"cycle":"t"}}. Applied on the main loop.
 *   - TX characteristic (read/notify): compact status JSON
 *     {"fx":"<name>","pl":<id>,"on":0|1,"bri":<n>,"mot":0|1,"cyc":0|1}
 *     notified whenever it changes (~1s poll).
 *
 * UUIDs match the original Bubbler-pio remote so the hosted page carries over.
 */

#include "wled.h"
#include <NimBLEDevice.h>

#define BUBBLER_BLE_SERVICE_UUID "7a5a1000-0002-4b70-8f1a-9d6e9c9a2b10"
#define BUBBLER_BLE_RX_UUID      "7a5a1001-0002-4b70-8f1a-9d6e9c9a2b10"
#define BUBBLER_BLE_TX_UUID      "7a5a1002-0002-4b70-8f1a-9d6e9c9a2b10"

class BubblerBLEUsermod : public Usermod {

  private:
    bool initDone = false;
    NimBLEServer* bleServer = nullptr;
    NimBLECharacteristic* rxChr = nullptr;
    NimBLECharacteristic* txChr = nullptr;

    // command handoff: BLE host task writes, WLED main loop consumes
    volatile bool cmdPending = false;
    char cmdBuf[192];

    char lastStatus[128] = {0};
    unsigned long lastStatusCheck = 0;
    bool clientConnected = false;

    class ServerCB : public NimBLEServerCallbacks {
        BubblerBLEUsermod* um;
      public:
        ServerCB(BubblerBLEUsermod* u) : um(u) {}
        void onConnect(NimBLEServer* s) { um->clientConnected = true; }
        void onDisconnect(NimBLEServer* s) {
          um->clientConnected = false;
          NimBLEDevice::startAdvertising();
        }
    };

    class RxCB : public NimBLECharacteristicCallbacks {
        BubblerBLEUsermod* um;
      public:
        RxCB(BubblerBLEUsermod* u) : um(u) {}
        void onWrite(NimBLECharacteristic* c) {
          if (um->cmdPending) return; // previous command not consumed yet - drop
          std::string v = c->getValue();
          if (v.length() == 0 || v.length() >= sizeof(um->cmdBuf)) return;
          memcpy(um->cmdBuf, v.data(), v.length());
          um->cmdBuf[v.length()] = '\0';
          um->cmdPending = true;
        }
    };

    void buildStatus(char* out, size_t maxLen) {
      Segment& seg = strip.getMainSegment();
      char fxRaw[48] = {0};
      extractModeName(seg.mode, nullptr, fxRaw, sizeof(fxRaw)-1);
      // keep printable ASCII only (names carry trailing unicode glyphs)
      char fx[32]; size_t j = 0;
      for (size_t k = 0; fxRaw[k] && j < sizeof(fx)-1; k++) {
        char ch = fxRaw[k];
        if (ch >= 32 && ch < 127 && ch != '"' && ch != '\\') fx[j++] = ch;
      }
      while (j > 0 && fx[j-1] == ' ') j--; // trim trailing spaces
      fx[j] = '\0';

      int mot = 0, cyc = 0;
      #ifdef USERMOD_MULTI_RELAY
      MultiRelay* mr = (MultiRelay*) usermods.lookup(USERMOD_ID_MULTI_RELAY);
      if (mr) {
        mot = mr->relayState(0) ? 1 : 0;
        cyc = mr->relayCycling(0) ? 1 : 0;
      }
      #endif

      snprintf(out, maxLen, "{\"fx\":\"%s\",\"pl\":%d,\"on\":%d,\"bri\":%d,\"mot\":%d,\"cyc\":%d}",
               fx, (int)currentPlaylist, bri > 0 ? 1 : 0, (int)briLast > 0 && bri == 0 ? (int)briLast : (int)bri, mot, cyc);
    }

  public:

    void setup() {
      // the ESP32 WiFi driver aborts on connect if modem sleep is disabled
      // while Bluetooth is active - force it on (runs before initConnection)
      noWifiSleep = false;

      NimBLEDevice::init("BubblerTotem");
      NimBLEDevice::setMTU(185);
      bleServer = NimBLEDevice::createServer();
      bleServer->setCallbacks(new ServerCB(this));

      NimBLEService* svc = bleServer->createService(BUBBLER_BLE_SERVICE_UUID);
      rxChr = svc->createCharacteristic(BUBBLER_BLE_RX_UUID,
                NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
      rxChr->setCallbacks(new RxCB(this));
      txChr = svc->createCharacteristic(BUBBLER_BLE_TX_UUID,
                NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);
      svc->start();

      NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
      adv->addServiceUUID(BUBBLER_BLE_SERVICE_UUID);
      adv->setScanResponse(true);
      adv->start();

      initDone = true;
    }

    void connected() {} // WiFi - not relevant

    void loop() {
      if (!initDone) return;

      if (cmdPending) {
        if (requestJSONBufferLock(20)) {
          doc.clear();
          DeserializationError err = deserializeJson(doc, (const char*)cmdBuf);
          if (!err) {
            deserializeState(doc.as<JsonObject>(), CALL_MODE_DIRECT_CHANGE);
            stateUpdated(CALL_MODE_DIRECT_CHANGE);
          }
          releaseJSONBufferLock();
          cmdPending = false; // consumed; if the buffer was busy we retry next loop
        }
      }

      if (millis() - lastStatusCheck > 700) {
        lastStatusCheck = millis();
        char status[128];
        buildStatus(status, sizeof(status));
        if (strcmp(status, lastStatus) != 0) {
          strcpy(lastStatus, status);
          if (txChr) {
            txChr->setValue((uint8_t*)status, strlen(status));
            if (clientConnected) txChr->notify();
          }
        }
      }
    }

    void addToJsonInfo(JsonObject& root) {
      JsonObject user = root["u"];
      if (user.isNull()) user = root.createNestedObject("u");
      JsonArray infoArr = user.createNestedArray(F("Bubbler BLE"));
      infoArr.add(clientConnected ? F("connected") : F("advertising"));
    }

    uint16_t getId() { return USERMOD_ID_UNSPECIFIED; }
};
