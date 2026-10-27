/*
  Arduino Uno + R307 fingerprint bridge for the Python case-study app.

  USB serial protocol at 115200 baud (newline-delimited JSON replies):
    PING
    ENROLL <template_id>    (1..999)
    VERIFY <template_id>    (1..999)
    IDENTIFY                (1:N search; returns matching template ID)

  R307 UART defaults to 57600 baud. Fingerprint templates stay on the sensor.
*/
#include <SoftwareSerial.h>
#include <Adafruit_Fingerprint.h>

// Uno D2 is SoftwareSerial RX; D3 is SoftwareSerial TX.
// Connect R307 TXD -> Uno D2, and Uno D3 -> R307 RXD.
SoftwareSerial r307Serial(2, 3);

static const uint32_t USB_BAUD = 115200;
static const uint32_t R307_DEFAULT_BAUD = 57600;
// R307 manuals specify 0xFFFFFFFF as factory default. Some compatible
// modules/examples use the Adafruit library's default password, 0x00000000.
static const uint32_t R307_MANUAL_PASSWORD = 0xFFFFFFFFUL;
static const uint32_t ADAFRUIT_DEFAULT_PASSWORD = 0x00000000UL;
static const uint32_t FINGER_TIMEOUT_MS = 20000;
static const uint16_t MAX_TEMPLATE_ID = 999;

String commandLine;
bool sensorReady = false;
uint32_t detectedR307Baud = R307_DEFAULT_BAUD;
Adafruit_Fingerprint fingerManualPassword(&r307Serial, R307_MANUAL_PASSWORD);
Adafruit_Fingerprint fingerAdafruitPassword(&r307Serial, ADAFRUIT_DEFAULT_PASSWORD);
Adafruit_Fingerprint *finger = &fingerManualPassword;

void emitError(const char *code) {
  Serial.print(F("{\"event\":\"error\",\"code\":\""));
  Serial.print(code);
  Serial.println(F("\"}"));
}

void emitProgress(const char *step) {
  Serial.print(F("{\"event\":\"progress\",\"step\":\""));
  Serial.print(step);
  Serial.println(F("\"}"));
}

bool validTemplateId(int id) { return id >= 1 && id <= MAX_TEMPLATE_ID; }

uint8_t waitForFinger(uint32_t timeoutMs) {
  const uint32_t started = millis();
  while (millis() - started < timeoutMs) {
    uint8_t result = finger->getImage();
    if (result == FINGERPRINT_OK) return FINGERPRINT_OK;
    if (result != FINGERPRINT_NOFINGER) return result;
    delay(80);
  }
  return FINGERPRINT_NOFINGER;
}

bool waitForRemoval(uint32_t timeoutMs) {
  const uint32_t started = millis();
  while (millis() - started < timeoutMs) {
    uint8_t result = finger->getImage();
    if (result == FINGERPRINT_NOFINGER) return true;
    if (result != FINGERPRINT_OK) return false;
    delay(80);
  }
  return false;
}

void handlePing() {
  // R307 manuals allow baud rates of 9600*N (N=1..12), with 57600 default.
  // Probe the documented rates using only the library's password handshake.
  static const uint32_t baudRates[] = {
    57600, 9600, 19200, 28800, 38400, 48000,
    67200, 76800, 86400, 96000, 105600, 115200
  };
  sensorReady = false;
  emitProgress("checking_sensor_baud");
  for (uint8_t i = 0; i < sizeof(baudRates) / sizeof(baudRates[0]); ++i) {
    r307Serial.end();
    delay(30);
    r307Serial.begin(baudRates[i]);
    delay(30);
    if (fingerManualPassword.verifyPassword()) {
      finger = &fingerManualPassword;
      detectedR307Baud = baudRates[i];
      sensorReady = true;
      break;
    }
    if (fingerAdafruitPassword.verifyPassword()) {
      finger = &fingerAdafruitPassword;
      detectedR307Baud = baudRates[i];
      sensorReady = true;
      break;
    }
  }
  if (!sensorReady) {
    emitError("sensor_not_responding_check_wiring_voltage_baud");
    return;
  }
  finger->getParameters();
  Serial.print(F("{\"event\":\"ping\",\"ok\":true,\"capacity\":"));
  Serial.print(finger->capacity);
  Serial.print(F(",\"sensor_baud\":"));
  Serial.print(detectedR307Baud);
  Serial.println(F("}"));
}

void handleVerify(int templateId) {
  if (!sensorReady) { emitError("sensor_not_ready_send_PING"); return; }
  if (!validTemplateId(templateId)) { emitError("template_id_must_be_1_to_999"); return; }

  emitProgress("place_finger");
  uint8_t capture = waitForFinger(FINGER_TIMEOUT_MS);
  if (capture == FINGERPRINT_NOFINGER) {
    Serial.println(F("{\"event\":\"verify\",\"result\":\"no_match\",\"reason\":\"finger_timeout\"}"));
    return;
  }
  if (capture != FINGERPRINT_OK) { emitError("finger_capture_failed"); return; }
  uint8_t result = finger->image2Tz(1);
  if (result != FINGERPRINT_OK) { emitError("image_conversion_failed"); return; }
  result = finger->fingerFastSearch();
  if (result == FINGERPRINT_NOTFOUND || result == FINGERPRINT_NOMATCH) {
    Serial.println(F("{\"event\":\"verify\",\"result\":\"no_match\"}"));
    return;
  }
  if (result != FINGERPRINT_OK) { emitError("finger_search_failed"); return; }

  if (finger->fingerID == (uint16_t)templateId)
    Serial.println(F("{\"event\":\"verify\",\"result\":\"match\"}"));
  else
    Serial.println(F("{\"event\":\"verify\",\"result\":\"no_match\"}"));
}

void handleIdentify() {
  if (!sensorReady) { emitError("sensor_not_ready_send_PING"); return; }
  emitProgress("place_finger");
  uint8_t capture = waitForFinger(FINGER_TIMEOUT_MS);
  if (capture == FINGERPRINT_NOFINGER) {
    Serial.println(F("{\"event\":\"identify\",\"result\":\"no_match\",\"reason\":\"finger_timeout\"}"));
    return;
  }
  if (capture != FINGERPRINT_OK) { emitError("finger_capture_failed"); return; }
  uint8_t result = finger->image2Tz(1);
  if (result != FINGERPRINT_OK) { emitError("image_conversion_failed"); return; }
  result = finger->fingerSearch(1);
  if (result == FINGERPRINT_NOTFOUND || result == FINGERPRINT_NOMATCH) {
    Serial.println(F("{\"event\":\"identify\",\"result\":\"no_match\"}"));
    return;
  }
  if (result != FINGERPRINT_OK) { emitError("finger_search_failed"); return; }

  Serial.print(F("{\"event\":\"identify\",\"result\":\"match\",\"template_id\":"));
  Serial.print(finger->fingerID);
  Serial.println(F("}"));
}

void handleEnroll(int templateId) {
  if (!sensorReady) { emitError("sensor_not_ready_send_PING"); return; }
  if (!validTemplateId(templateId)) { emitError("template_id_must_be_1_to_999"); return; }

  emitProgress("place_first");
  uint8_t capture = waitForFinger(FINGER_TIMEOUT_MS);
  if (capture != FINGERPRINT_OK) { emitError("first_capture_timeout_or_failure"); return; }
  uint8_t result = finger->image2Tz(1);
  if (result != FINGERPRINT_OK) { emitError("first_image_conversion_failed"); return; }

  emitProgress("remove_finger");
  if (!waitForRemoval(FINGER_TIMEOUT_MS)) { emitError("finger_removal_timeout_or_failure"); return; }

  emitProgress("place_second");
  capture = waitForFinger(FINGER_TIMEOUT_MS);
  if (capture != FINGERPRINT_OK) { emitError("second_capture_timeout_or_failure"); return; }
  result = finger->image2Tz(2);
  if (result != FINGERPRINT_OK) { emitError("second_image_conversion_failed"); return; }
  result = finger->createModel();
  if (result != FINGERPRINT_OK) { emitError("fingerprint_samples_did_not_match"); return; }
  result = finger->storeModel((uint16_t)templateId);
  if (result != FINGERPRINT_OK) { emitError("template_storage_failed"); return; }

  Serial.print(F("{\"event\":\"enrolled\",\"template_id\":"));
  Serial.print(templateId);
  Serial.println(F("}"));
}

void processLine(String line) {
  line.trim();
  if (line == "PING") { handlePing(); return; }
  if (line == "IDENTIFY") { handleIdentify(); return; }
  if (line.startsWith("VERIFY ")) {
    handleVerify(line.substring(7).toInt());
    return;
  }
  if (line.startsWith("ENROLL ")) {
    handleEnroll(line.substring(7).toInt());
    return;
  }
  emitError("unknown_command");
}

void setup() {
  Serial.begin(USB_BAUD);
  r307Serial.begin(R307_DEFAULT_BAUD);
  commandLine.reserve(40);
  delay(300);
}

void loop() {
  while (Serial.available()) {
    char incoming = (char)Serial.read();
    if (incoming == '\n') {
      processLine(commandLine);
      commandLine = "";
    } else if (incoming != '\r' && commandLine.length() < 60) {
      commandLine += incoming;
    } else if (commandLine.length() >= 60) {
      commandLine = "";
      emitError("command_too_long");
    }
  }
}
