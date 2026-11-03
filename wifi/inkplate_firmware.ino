/*
 * ==============================================================================
 * E-Ink Tischkarte – ESP32 / Inkplate 10 WLAN Firmware
 * ==============================================================================
 * 
 * Weg B: "Das Display fragt selbst nach" (Direktes WLAN)
 * 
 * Funktionsweise:
 *  1. Aus Deep Sleep aufwachen.
 *  2. WLAN verbinden (mit Timeout).
 *  3. HTTP GET Anfrage: /api/displays/002/manifest
 *  4. JSON parsen und Bildversion mit RTC-gespeicherter Version vergleichen.
 *  5. Falls neuere Version vorhanden:
 *     - Bild per HTTP herunterladen
 *     - In den E-Ink Puffer zeichnen
 *     - Display aktualisieren (inkplate.display())
 *     - Neue Versionsnummer im RTC-Speicher sichern
 *  6. Falls Version unverändert:
 *     - Kein Download nötig (spart bis zu 90% Energie!)
 *  7. WLAN trennen und für z.B. 15 Minuten (900s) in den ESP32 Deep Sleep gehen.
 * 
 * Benötigte Bibliotheken (im Arduino Library Manager):
 *  - Inkplate (von Soldered Electronics / e-radionica)
 *  - ArduinoJson (v6 oder v7)
 *  - HTTPClient (ESP32 Standardbibliothek)
 *  - WiFi (ESP32 Standardbibliothek)
 * ==============================================================================
 */

#include "Inkplate.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ------------------------------------------------------------------------------
// Konfiguration: WLAN & Server
// ------------------------------------------------------------------------------
const char* WIFI_SSID     = "DEIN_WLAN_NAME";
const char* WIFI_PASSWORD = "DEIN_WLAN_PASSWORT";

// Host-Adresse des Backends (z.B. IP des Servers im lokalen Netzwerk)
const char* BACKEND_HOST  = "http://192.168.1.100:8000";
const char* DEVICE_ID     = "display_002";

// Deep Sleep Dauer in Mikrosekunden (z.B. 15 Minuten = 900 Sekunden = 900 * 1000000ULL)
#define SLEEP_SECONDS 900
#define uS_TO_S_FACTOR 1000000ULL

// ------------------------------------------------------------------------------
// Persistenter RTC-Speicher (übersteht Deep Sleep Zyklen)
// ------------------------------------------------------------------------------
RTC_DATA_ATTR int local_image_version = 0;
RTC_DATA_ATTR int boot_count = 0;

// Inkplate Display Objekt (1-Bit Schwarz/Weiß Modus für schnelle Refreshes)
Inkplate display(INKPLATE_1BIT);

// ------------------------------------------------------------------------------
// Hilfsfunktion: WLAN Verbindung herstellen mit Timeout
// ------------------------------------------------------------------------------
bool connectWiFi(int timeout_seconds = 15) {
    Serial.printf("[WiFi] Verbinde mit %s ...\n", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int elapsed = 0;
    while (WiFi.status() != WL_CONNECTED && elapsed < timeout_seconds * 10) {
        delay(100);
        Serial.print(".");
        elapsed++;
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("[WiFi] Verbunden! IP: %s (RSSI: %d dBm)\n", 
                      WiFi.localIP().toString().c_str(), WiFi.RSSI());
        return true;
    } else {
        Serial.println("[WiFi] Fehler: Verbindung fehlgeschlagen (Timeout).");
        return false;
    }
}

// ------------------------------------------------------------------------------
// Hauptablauf (Setup führt alles aus und leitet sofort Deep Sleep ein)
// ------------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    boot_count++;
    Serial.println("\n--- E-Ink Tischkarte Wake-Up ---");
    Serial.printf("Boot-Zähler: %d | Aktuelle lokale Bildversion: %d\n", boot_count, local_image_version);

    // Inkplate Initialisieren
    display.begin();

    // 1. WLAN verbinden
    if (!connectWiFi()) {
        Serial.println("[Setup] Breche ab wegen fehlendem WLAN. Gehe in Deep Sleep.");
        goToDeepSleep();
        return;
    }

    // 2. Manifest vom Server abfragen
    String manifestUrl = String(BACKEND_HOST) + "/api/displays/" + DEVICE_ID + "/manifest";
    Serial.printf("[HTTP] Frage Manifest ab: %s\n", manifestUrl.c_str());

    HTTPClient http;
    http.begin(manifestUrl);
    http.setTimeout(5000);
    int httpCode = http.GET();

    if (httpCode != HTTP_CODE_OK) {
        Serial.printf("[HTTP] Fehler beim Manifest-Abruf: %d\n", httpCode);
        http.end();
        goToDeepSleep();
        return;
    }

    String payload = http.getString();
    http.end();
    Serial.printf("[HTTP] Antwort: %s\n", payload.c_str());

    // 3. JSON analysieren
    StaticJsonDocument<512> doc;
    DeserializationError error = deserializeJson(doc, payload);
    if (error) {
        Serial.printf("[JSON] Parsing fehlgeschlagen: %s\n", error.c_str());
        goToDeepSleep();
        return;
    }

    int server_version = doc["version"] | 0;
    const char* image_rel_url = doc["image_url"] | "";

    Serial.printf("[Version] Server-Version: %d (Lokal: %d)\n", server_version, local_image_version);

    // 4. Prüfen, ob eine neuere Version existiert
    if (server_version > local_image_version || local_image_version == 0) {
        Serial.println("[Update] Neue Bildversion erkannt! Lade Bild herunter...");

        String fullImageUrl = String(image_rel_url);
        if (!fullImageUrl.startsWith("http")) {
            fullImageUrl = String(BACKEND_HOST) + fullImageUrl;
        }

        // Inkplate Hilfsfunktion: Bild direkt von HTTP in den Display-Puffer zeichnen
        // Unterstützt PNG / JPEG / BMP
        display.clearDisplay();
        int drawResult = display.drawImage(fullImageUrl.c_str(), 0, 0, false, false);

        if (drawResult == 1) {
            Serial.println("[Display] Bild erfolgreich dekodiert. Starte E-Ink Refresh...");
            display.display();
            local_image_version = server_version;
            Serial.printf("[Display] Update abgeschlossen! Neue Version: %d\n", local_image_version);
        } else {
            Serial.printf("[Display] FEHLER beim Zeichnen des Bildes (Code: %d)\n", drawResult);
        }
    } else {
        Serial.println("[Update] Bildversion unverändert. Kein Download nötig (Energie gespart!).");
    }

    // 5. In den Schlafmodus wechseln
    goToDeepSleep();
}

void loop() {
    // Bleibt leer, da das System nach setup() direkt in den Deep Sleep wechselt
}

// ------------------------------------------------------------------------------
// Deep Sleep Routine
// ------------------------------------------------------------------------------
void goToDeepSleep() {
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    Serial.printf("[Power] WLAN deaktiviert. Gehe in Deep Sleep für %d Sekunden...\n\n", SLEEP_SECONDS);
    Serial.flush();

    esp_sleep_enable_timer_wakeup((uint64_t)SLEEP_SECONDS * uS_TO_S_FACTOR);
    esp_deep_sleep_start();
}
