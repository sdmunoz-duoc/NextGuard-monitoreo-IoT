#include <WiFi.h>
#include "config.h"   // copiar config.h.example a config.h (no se versiona)

const char* ssid = WIFI_SSID;
const char* password = WIFI_PASSWORD;

const unsigned long WIFI_TIMEOUT = 15000;   // ms por intento
const unsigned long RETRY_MIN = 5000;       // ms entre reintentos (backoff)
const unsigned long RETRY_MAX = 60000;

// 1 = baja la potencia de transmisión (ayuda si hay caídas de tensión / AUTH_EXPIRE).
// Pruébalo en 1 y luego en 0 para ver si cambia algo.
#define USE_LOW_TX_POWER 1

volatile uint8_t lastReason = 0;            // último código de desconexión
volatile bool gotReason = false;

// ---------- Traducción de códigos ----------

const char* authName(wifi_auth_mode_t a) {
  switch (a) {
    case WIFI_AUTH_OPEN:            return "ABIERTA";
    case WIFI_AUTH_WEP:             return "WEP";
    case WIFI_AUTH_WPA_PSK:         return "WPA";
    case WIFI_AUTH_WPA2_PSK:        return "WPA2";
    case WIFI_AUTH_WPA_WPA2_PSK:    return "WPA/WPA2";
    case WIFI_AUTH_WPA2_ENTERPRISE: return "WPA2-ENTERPRISE";
    case WIFI_AUTH_WPA3_PSK:        return "WPA3";
    case WIFI_AUTH_WPA2_WPA3_PSK:   return "WPA2/WPA3";
    default:                        return "OTRO";
  }
}

// Códigos WIFI_REASON_* como números para compilar igual en core 2.x y 3.x
void explainReason(uint8_t r) {
  Serial.printf("[MOTIVO %u] ", r);
  switch (r) {
    case 2:   Serial.println("AUTH_EXPIRE: el AP expiró la autenticación. Reintentar; revisar PMF/WPA3."); break;
    case 3:   Serial.println("AUTH_LEAVE: el AP nos desautenticó."); break;
    case 4:   Serial.println("ASSOC_EXPIRE: la asociación expiró."); break;
    case 5:   Serial.println("ASSOC_TOOMANY: el AP alcanzó su máximo de dispositivos."); break;
    case 8:   Serial.println("ASSOC_LEAVE: el AP nos sacó de la red."); break;
    case 14:  Serial.println("MIC_FAILURE: clave incorrecta o incompatibilidad WPA."); break;
    case 15:  Serial.println("4WAY_HANDSHAKE_TIMEOUT: probable CONTRASEÑA INCORRECTA o WPA3/PMF."); break;
    case 200: Serial.println("BEACON_TIMEOUT: se perdió la señal del AP (débil o alimentación)."); break;
    case 201: Serial.println("NO_AP_FOUND: SSID no visible. Revisa nombre, banda 2.4 GHz, distancia."); break;
    case 202: Serial.println("AUTH_FAIL: autenticación fallida. Probable CONTRASEÑA INCORRECTA."); break;
    case 203: Serial.println("ASSOC_FAIL: el AP rechazó la asociación (filtro MAC, AP lleno, canal 12-13)."); break;
    case 204: Serial.println("HANDSHAKE_TIMEOUT: probable CONTRASEÑA INCORRECTA."); break;
    case 205: Serial.println("CONNECTION_FAIL: el AP existe pero rechazó la conexión."); break;
    default:  Serial.println("Motivo no catalogado (ver esp_wifi_types.h)."); break;
  }
}

// ---------- Eventos ----------

void onWiFiEvent(arduino_event_id_t event, arduino_event_info_t info) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      lastReason = info.wifi_sta_disconnected.reason;
      gotReason = true;
      break;
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      Serial.println("[EVENTO] IP obtenida por DHCP.");
      break;
    default:
      break;
  }
}

// ---------- Escaneo ----------

bool scanTarget() {
  Serial.println("--- Escaneo de redes ---");
  int n = WiFi.scanNetworks();
  if (n <= 0) {
    Serial.println("No se detectó ninguna red 2.4 GHz (¿antena/alimentación/zona?).");
    return false;
  }

  bool found = false;
  for (int i = 0; i < n; i++) {
    bool match = (WiFi.SSID(i) == ssid);
    Serial.printf("%s %-24s %s  ch %2d  %4d dBm  %s\n",
                  match ? ">>" : "  ", WiFi.SSID(i).c_str(), WiFi.BSSIDstr(i).c_str(),
                  WiFi.channel(i), WiFi.RSSI(i), authName(WiFi.encryptionType(i)));
    if (match) found = true;
  }
  WiFi.scanDelete();

  if (!found) {
    Serial.printf("[!] '%s' NO aparece. El ESP32 solo ve 2.4 GHz: revisa que el router emita en esa banda.\n", ssid);
  }
  Serial.println("------------------------");
  return found;
}

// ---------- Conexión ----------

bool connectWiFi() {
  gotReason = false;
  lastReason = 0;

  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true, true);   // limpia credenciales previas
  delay(200);
  WiFi.mode(WIFI_STA);

  // Conectar al AP con mejor señal, no al primero encontrado
  WiFi.setScanMethod(WIFI_ALL_CHANNEL_SCAN);
  WiFi.setSortMethod(WIFI_CONNECT_AP_BY_SIGNAL);
#if USE_LOW_TX_POWER
  WiFi.setTxPower(WIFI_POWER_8_5dBm);
#endif

  if (!scanTarget()) {
    Serial.println("Se intentará conectar igualmente...");
  }

  Serial.printf("Intentando conectar a: %s\n", ssid);
  WiFi.begin(ssid, password);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_TIMEOUT) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("=========== CONEXIÓN EXITOSA ===========");
    Serial.print("IP:        "); Serial.println(WiFi.localIP());
    Serial.print("Máscara:   "); Serial.println(WiFi.subnetMask());
    Serial.print("Gateway:   "); Serial.println(WiFi.gatewayIP());
    Serial.print("DNS:       "); Serial.println(WiFi.dnsIP());
    Serial.printf("RSSI:      %d dBm | Canal: %d\n", WiFi.RSSI(), WiFi.channel());
    Serial.print("MAC ESP32: "); Serial.println(WiFi.macAddress());
    Serial.print("BSSID AP:  "); Serial.println(WiFi.BSSIDstr());
    Serial.println("========================================");
    return true;
  }

  Serial.println("============ FALLO DE CONEXIÓN =========");
  Serial.printf("wl_status_t = %d\n", WiFi.status());
  if (gotReason) explainReason(lastReason);
  else Serial.println("Sin evento de desconexión: el AP no respondió (fuera de alcance / banda 5 GHz).");
  Serial.println("========================================");

  WiFi.disconnect(true);
  return false;
}

// ---------- Arduino ----------

unsigned long retryDelay = RETRY_MIN;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== Diagnóstico WiFi ESP32 ===");
  WiFi.onEvent(onWiFiEvent);
  connectWiFi();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("[ALERTA] Sin conexión. Reintento en %lu s\n", retryDelay / 1000);
    delay(retryDelay);
    if (connectWiFi()) retryDelay = RETRY_MIN;
    else retryDelay = min(retryDelay * 2, RETRY_MAX);
  } else {
    Serial.printf("[STATUS] Conectado | RSSI %d dBm\n", WiFi.RSSI());
    delay(5000);
  }
}
