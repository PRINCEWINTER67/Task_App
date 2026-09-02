/*
  task_light.ino
  ------------------------------------------------------------
  Physical control panel for the Task Status Tracker app (task_app.py).
  Drives:
    - 4 status LEDs (red / yellow / blue / green) showing task urgency
    - a single-digit 7-segment display (common-anode, e.g. 5161AS)
      wired DIRECTLY to Arduino pins (no shift register), showing the
      pending task count

  Talks to task_app.py over USB serial at 9600 baud using a tiny
  line-based text protocol (each line ends with '\n'):

    L:<0-4>          urgency light state
                        0 = RED solid   (a task is due within the hour, or overdue)
                        1 = RED blink   (a task is due later today)
                        2 = BLUE solid  (nearest task due tomorrow)
                        3 = YELLOW solid (nearest task due later than tomorrow)
                        4 = GREEN solid (nothing pending)
    C:<0-9999>       number of pending (not-done) tasks -> shown on the
                      single-digit display, clamped to a single digit
                      (10 or more just shows "9")

  There is no LCD, no button, and no shift register on this build - just
  4 LEDs and one directly-wired 7-segment digit. Any other line the app
  sends (it may still send task-list lines from an older protocol
  version) is silently ignored.
*/

// ---------------- PIN MAP ----------------
const uint8_t PIN_LED_RED    = 2;
const uint8_t PIN_LED_YELLOW = 3;
const uint8_t PIN_LED_BLUE   = 4;
const uint8_t PIN_LED_GREEN  = 5;

// Single-digit 7-segment display (COMMON ANODE, e.g. 5161AS), wired
// directly to these pins - no shift register in between.
const uint8_t PIN_SEG_A  = 7;
const uint8_t PIN_SEG_B  = 8;
const uint8_t PIN_SEG_C  = 9;
const uint8_t PIN_SEG_D  = 10;
const uint8_t PIN_SEG_E  = 11;
const uint8_t PIN_SEG_F  = 12;
const uint8_t PIN_SEG_G  = 13;
const uint8_t PIN_SEG_DP = A0;

const uint8_t SEGMENT_PINS[8] = {
  PIN_SEG_A, PIN_SEG_B, PIN_SEG_C, PIN_SEG_D,
  PIN_SEG_E, PIN_SEG_F, PIN_SEG_G, PIN_SEG_DP
};

// Which segments light up for each digit 0-9. bit0=a ... bit6=g, bit7=dp.
// 1 means "this segment should be on" - showDigit() below inverts that
// into the correct pin level for a common-anode display.
const uint8_t DIGIT_SEGMENTS[10] = {
  0b00111111, // 0: a b c d e f
  0b00000110, // 1: b c
  0b01011011, // 2: a b g e d
  0b01001111, // 3: a b g c d
  0b01100110, // 4: f g b c
  0b01101101, // 5: a f g c d
  0b01111101, // 6: a f g e d c
  0b00000111, // 7: a b c
  0b01111111, // 8: all
  0b01101111, // 9: a b c d f g
};

int counterValue = 0;

void showDigit(int value) {
  // Only one digit fits - clamp anything double-digit to 9 so the
  // display always reads as something sensible instead of wrapping
  // (e.g. 12 pending tasks shows "9", not silently rolling to "2").
  if (value < 0) value = 0;
  if (value > 9) value = 9;
  uint8_t pattern = DIGIT_SEGMENTS[value];
  for (uint8_t i = 0; i < 8; i++) {
    bool segmentOn = (pattern >> i) & 0x01;
    // Common-anode display: pin LOW lights the segment, HIGH turns it off.
    digitalWrite(SEGMENT_PINS[i], segmentOn ? LOW : HIGH);
  }
}

// ---------------- LIGHT STATE ----------------
uint8_t lightState = 4; // start on green/idle until the app sends real state
unsigned long lastBlinkToggle = 0;
bool blinkOn = false;
const unsigned long BLINK_INTERVAL_MS = 500;

void setAllLedsOff() {
  digitalWrite(PIN_LED_RED, LOW);
  digitalWrite(PIN_LED_YELLOW, LOW);
  digitalWrite(PIN_LED_BLUE, LOW);
  digitalWrite(PIN_LED_GREEN, LOW);
}

void updateLight() {
  switch (lightState) {
    case 0: // red solid - due within the hour, or overdue
      setAllLedsOff();
      digitalWrite(PIN_LED_RED, HIGH);
      break;
    case 1: // red blink - due later today
      if (millis() - lastBlinkToggle >= BLINK_INTERVAL_MS) {
        lastBlinkToggle = millis();
        blinkOn = !blinkOn;
      }
      setAllLedsOff();
      digitalWrite(PIN_LED_RED, blinkOn ? HIGH : LOW);
      break;
    case 2: // blue - due tomorrow
      setAllLedsOff();
      digitalWrite(PIN_LED_BLUE, HIGH);
      break;
    case 3: // yellow - due later than tomorrow
      setAllLedsOff();
      digitalWrite(PIN_LED_YELLOW, HIGH);
      break;
    default: // 4 - green, nothing pending
      setAllLedsOff();
      digitalWrite(PIN_LED_GREEN, HIGH);
      break;
  }
}

// ---------------- SERIAL PROTOCOL ----------------
#define LINE_BUF_LEN 24
char lineBuf[LINE_BUF_LEN];
uint8_t lineLen = 0;

void applyLine(char *line) {
  if (line[0] == 'L' && line[1] == ':') {
    int v = atoi(line + 2);
    if (v < 0) v = 0;
    if (v > 4) v = 4;
    lightState = (uint8_t)v;
    blinkOn = true; // restart each new state lit, not mid-blink-off
    lastBlinkToggle = millis();
  } else if (line[0] == 'C' && line[1] == ':') {
    long v = atol(line + 2);
    if (v < 0) v = 0;
    if (v > 9999) v = 9999;
    counterValue = (int)v;
    showDigit(counterValue);
  }
  // Any other line (e.g. leftover N:/I: task-list lines from an older
  // protocol version) is intentionally ignored - no LCD on this build.
}

void readSerialLines() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      lineBuf[lineLen] = '\0';
      if (lineLen > 0) applyLine(lineBuf);
      lineLen = 0;
    } else if (c != '\r') {
      if (lineLen < LINE_BUF_LEN - 1) {
        lineBuf[lineLen++] = c;
      }
    }
  }
}

// ---------------- SETUP / LOOP ----------------
void setup() {
  Serial.begin(9600);

  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_BLUE, OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  setAllLedsOff();

  for (uint8_t i = 0; i < 8; i++) {
    pinMode(SEGMENT_PINS[i], OUTPUT);
  }
  showDigit(0);
}

void loop() {
  readSerialLines();
  updateLight();
}
