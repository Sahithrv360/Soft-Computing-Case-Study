/*
  Wemos D1 R1 + R307 fingerprint bridge for the Python case-study app.

  USB serial protocol at 115200 baud (newline-delimited JSON replies):
    PING
    ENROLL <template_id>    (1..999)
    VERIFY <template_id>    (1..999)

  R307 UART defaults to 57600 baud. Adafruit Fingerprint Sensor Library is
  used only for its documented packet protocol. Templates remain on the R307;
  no fingerprint images/templates are sent to the laptop.
*/
#include <SoftwareSerial.h>
#include <Adafruit_Fingerprint.h>

// Requested wiring: Wemos D0 as software-UART RX, D1 as software-UART TX.
// R307 TXD -> D0; R307 RXD -> D1; share ground.
// WARNING: D0/D1 are also the Wemos USB UART pins on this board, so this
// conflicts with the USB Serial command/JSON bridge used by the PC app.
SoftwareSerial r307Serial(D0, D1);

static const uint32_t USB_BAUD = 115200;
static const uint32_t R307_BAUD = 57600;
// R307 user manual factory handshake password; Adafruit library defaults to 0.
static const uint32_t R307_DEFAULT_PASSWORD = 0xFFFFFFFFUL;
static const uint32_t FINGER_TIMEOUT_MS = 20000;
static const uint16_t MAX_TEMPLATE_ID = 999;
String commandLine;
bool sensorReady = false;

Adafruit_Fingerprint finger(&r307Serial, R307_DEFAULT_PASSWORD);

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
    uint8_t result = finger.getImage();
    if (result == FINGERPRINT_OK) return FINGERPRINT_OK;
    if (result != FINGERPRINT_NOFINGER) return result;
    delay(80);
    yield();
  }
  return FINGERPRINT_NOFINGER;
}

bool waitForRemoval(uint32_t timeoutMs) {
  const uint32_t started = millis();
  while (millis() - started < timeoutMs) {
    uint8_t result = finger.getImage();
    if (result == FINGERPRINT_NOFINGER) return true;
    if (result != FINGERPRINT_OK) return false;
    delay(80);
    yield();
  }
  return false;
}

void handlePing() {
  sensorReady = finger.verifyPassword();
  if (!sensorReady) {
    emitError("sensor_not_responding_check_wiring_voltage_baud");
    return;
  }
  finger.getParameters();
  Serial.print(F("{\"event\":\"ping\",\"ok\":true,\"capacity\":"));
  Serial.print(finger.capacity);
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
  uint8_t result = finger.image2Tz(1);
  if (result != FINGERPRINT_OK) { emitError("image_conversion_failed"); return; }
  result = finger.fingerFastSearch();
  if (result == FINGERPRINT_NOTFOUND || result == FINGERPRINT_NOMATCH) {
    Serial.println(F("{\"event\":\"verify\",\"result\":\"no_match\"}"));
    return;
  }
  if (result != FINGERPRINT_OK) { emitError("finger_search_failed"); return; }

  if (finger.fingerID == (uint16_t)templateId) {
    Serial.println(F("{\"event\":\"verify\",\"result\":\"match\"}"));
  } else {
    Serial.println(F("{\"event\":\"verify\",\"result\":\"no_match\"}"));
  }
}

void handleEnroll(int templateId) {
  if (!sensorReady) { emitError("sensor_not_ready_send_PING"); return; }
  if (!validTemplateId(templateId)) { emitError("template_id_must_be_1_to_999"); return; }

  emitProgress("place_first");
  uint8_t capture = waitForFinger(FINGER_TIMEOUT_MS);
  if (capture != FINGERPRINT_OK) { emitError("first_capture_timeout_or_failure"); return; }
  uint8_t result = finger.image2Tz(1);
  if (result != FINGERPRINT_OK) { emitError("first_image_conversion_failed"); return; }

  emitProgress("remove_finger");
  if (!waitForRemoval(FINGER_TIMEOUT_MS)) { emitError("finger_removal_timeout_or_failure"); return; }

  emitProgress("place_second");
  capture = waitForFinger(FINGER_TIMEOUT_MS);
  if (capture != FINGERPRINT_OK) { emitError("second_capture_timeout_or_failure"); return; }
  result = finger.image2Tz(2);
  if (result != FINGERPRINT_OK) { emitError("second_image_conversion_failed"); return; }
  result = finger.createModel();
  if (result != FINGERPRINT_OK) { emitError("fingerprint_samples_did_not_match"); return; }
  result = finger.storeModel((uint16_t)templateId);
  if (result != FINGERPRINT_OK) { emitError("template_storage_failed"); return; }

  Serial.print(F("{\"event\":\"enrolled\",\"template_id\":"));
  Serial.print(templateId);
  Serial.println(F("}"));
}

void processLine(String line) {
  line.trim();
  if (line == "PING") { handlePing(); return; }
  if (line.startsWith("VERIFY ")) {
    int id = line.substring(7).toInt();
    handleVerify(id);
    return;
  }
  if (line.startsWith("ENROLL ")) {
    int id = line.substring(7).toInt();
    handleEnroll(id);
    return;
  }
  emitError("unknown_command");
}

void setup() {
  Serial.begin(USB_BAUD);
  r307Serial.begin(R307_BAUD);
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
    yield();
  }
}
