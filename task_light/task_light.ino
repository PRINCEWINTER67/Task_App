/*
  task_light.ino
  ------------------------------------------------------------
  Physical control panel for the Task Status Tracker app (task_app.py).
  Drives:
    - 4 status LEDs (red / yellow / blue / green) showing task urgency
    - a 4-digit 7-segment display (via 74HC595) showing the pending
      task count
    - a 16x2 LCD that shows the task list, one task per button press

  Talks to task_app.py over USB serial at 9600 baud using a tiny
  line-based text protocol (each line ends with '\n'):

    L:<0-4>          urgency light state
                        0 = RED solid   (a task is due within the hour, or overdue)
                        1 = RED blink   (a task is due later today)
                        2 = BLUE solid  (nearest task due tomorrow)
                        3 = YELLOW solid (nearest task due later than tomorrow)
                        4 = GREEN solid (nothing pending)
    C:<0-9999>       number of pending (not-done) tasks -> 7-segment counter
    N:<0-6>          how many task lines follow (resets the button-cycled
                      task list on the LCD)
    I:<name>|<due>   one task line (name + short due label, each already
                      trimmed to <=16 chars by the Python side), sent N
                      times right after an N: line

  Nothing is ever sent back to Python - all button/LCD logic lives here.

  See the wiring reference for the full pin table and physical build
  instructions (LEDs, 74HC595 shift register + PN2222 transistors for the
  4-digit display, LCD1602 + 10K contrast pot).
*/

#include <LiquidCrystal.h>

// ---------------- PIN MAP ----------------
const uint8_t PIN_LED_RED    = 2;
const uint8_t PIN_LED_YELLOW = 3;
const uint8_t PIN_LED_BLUE   = 4;
const uint8_t PIN_LED_GREEN  = 5;
const uint8_t PIN_BUTTON     = 6;   // other leg to GND, uses INPUT_PULLUP

const uint8_t PIN_595_DATA   = 7;   // 74HC595 DS
const uint8_t PIN_595_LATCH  = 8;   // 74HC595 ST_CP
const uint8_t PIN_595_CLOCK  = 9;   // 74HC595 SH_CP

const uint8_t PIN_DIGIT[4]   = {10, 11, 12, 13}; // digit-select transistor bases (D1..D4)

LiquidCrystal lcd(A0, A1, A2, A3, A4, A5); // RS, E, D4, D5, D6, D7

// ---------------- 7-SEGMENT ----------------
// Bit order sent to the 74HC595, Q0..Q7 -> segments a,b,c,d,e,f,g,dp.
// Wire the 8 current-limiting resistors from Q0..Q7 to segments a..dp in
// that order (see wiring reference) and these patterns will read right.
const uint8_t DIGIT_SEGMENTS[10] = {
  0b00111111, // 0
  0b00000110, // 1
  0b01011011, // 2
  0b01001111, // 3
  0b01100110, // 4
  0b01101101, // 5
  0b01111101, // 6
  0b00000111, // 7
  0b01111111, // 8
  0b01101111, // 9
};
const uint8_t SEGMENTS_BLANK = 0b00000000;

int counterValue = 0;
uint8_t muxDigit = 0;
unsigned long lastMuxSwitch = 0;
const unsigned long MUX_INTERVAL_MS = 3;

void writeShiftRegister(uint8_t segments) {
  digitalWrite(PIN_595_LATCH, LOW);
  shiftOut(PIN_595_DATA, PIN_595_CLOCK, MSBFIRST, segments);
  digitalWrite(PIN_595_LATCH, HIGH);
}

void updateCounterDisplay() {
  unsigned long now = millis();
  if (now - lastMuxSwitch < MUX_INTERVAL_MS) return;
  lastMuxSwitch = now;

  // Turn every digit off before latching new segments, so we never briefly
  // show one digit's segments on another digit ("ghosting").
  for (uint8_t i = 0; i < 4; i++) digitalWrite(PIN_DIGIT[i], LOW);

  int clamped = constrain(counterValue, 0, 9999);
  uint8_t digits[4] = {
    (uint8_t)(clamped / 1000),
    (uint8_t)((clamped / 100) % 10),
    (uint8_t)((clamped / 10) % 10),
    (uint8_t)(clamped % 10),
  };

  // Blank leading zeros (show "  12" not "0012"), but always show at least
  // the ones digit, even when the count is 0.
  uint8_t firstSignificant = 0;
  while (firstSignificant < 3 && digits[firstSignificant] == 0) firstSignificant++;

  uint8_t segments = (muxDigit < firstSignificant) ? SEGMENTS_BLANK : DIGIT_SEGMENTS[digits[muxDigit]];

  writeShiftRegister(segments);
  digitalWrite(PIN_DIGIT[muxDigit], HIGH);
  muxDigit = (muxDigit + 1) % 4;
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

// ---------------- BUTTON + LCD TASK BROWSER ----------------
#define MAX_TASKS 6
char taskName[MAX_TASKS][17];
char taskDue[MAX_TASKS][17];
uint8_t taskCount = 0;
uint8_t lcdTaskIndex = 0;
bool lcdShowingTask = false;

bool lastButtonReading = HIGH;
bool buttonState = HIGH;
unsigned long lastDebounceTime = 0;
const unsigned long DEBOUNCE_MS = 40;

void showIdleLcd() {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Press button for");
  lcd.setCursor(0, 1);
  if (taskCount == 0) {
    lcd.print("...nothing due!");
  } else {
    char line[17];
    snprintf(line, sizeof(line), "...%u pending", (unsigned)taskCount);
    lcd.print(line);
  }
  lcdShowingTask = false;
}

void showTaskOnLcd() {
  lcd.clear();
  if (taskCount == 0) {
    lcd.setCursor(0, 0);
    lcd.print("All caught up!");
    lcd.setCursor(0, 1);
    lcd.print("No pending tasks");
    return;
  }
  lcd.setCursor(0, 0);
  lcd.print(taskName[lcdTaskIndex]);
  lcd.setCursor(0, 1);
  char row1[17];
  snprintf(row1, sizeof(row1), "%-11.11s%2u/%1u", taskDue[lcdTaskIndex], (unsigned)(lcdTaskIndex + 1), (unsigned)taskCount);
  lcd.print(row1);
  lcdShowingTask = true;
}

void handleButton() {
  bool reading = digitalRead(PIN_BUTTON);
  if (reading != lastButtonReading) {
    lastDebounceTime = millis();
  }
  if (millis() - lastDebounceTime > DEBOUNCE_MS && reading != buttonState) {
    buttonState = reading;
    if (buttonState == LOW) { // pressed (INPUT_PULLUP -> LOW on press)
      if (!lcdShowingTask) {
        lcdTaskIndex = 0;
      } else {
        uint8_t total = (taskCount == 0) ? 1 : taskCount;
        lcdTaskIndex = (lcdTaskIndex + 1) % total;
      }
      showTaskOnLcd();
    }
  }
  lastButtonReading = reading;
}

// ---------------- SERIAL PROTOCOL ----------------
#define LINE_BUF_LEN 40
char lineBuf[LINE_BUF_LEN];
uint8_t lineLen = 0;
uint8_t taskFillIndex = 0;

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
  } else if (line[0] == 'N' && line[1] == ':') {
    int v = atoi(line + 2);
    if (v < 0) v = 0;
    if (v > MAX_TASKS) v = MAX_TASKS;
    taskCount = (uint8_t)v;
    taskFillIndex = 0;
    lcdTaskIndex = 0;
    showIdleLcd();
  } else if (line[0] == 'I' && line[1] == ':') {
    if (taskFillIndex < taskCount) {
      char *rest = line + 2;
      char *sep = strchr(rest, '|');
      if (sep != NULL) {
        *sep = '\0';
        strncpy(taskName[taskFillIndex], rest, 16);
        taskName[taskFillIndex][16] = '\0';
        strncpy(taskDue[taskFillIndex], sep + 1, 16);
        taskDue[taskFillIndex][16] = '\0';
      } else {
        strncpy(taskName[taskFillIndex], rest, 16);
        taskName[taskFillIndex][16] = '\0';
        taskDue[taskFillIndex][0] = '\0';
      }
      taskFillIndex++;
    }
  }
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
  pinMode(PIN_BUTTON, INPUT_PULLUP);

  pinMode(PIN_595_DATA, OUTPUT);
  pinMode(PIN_595_LATCH, OUTPUT);
  pinMode(PIN_595_CLOCK, OUTPUT);
  for (uint8_t i = 0; i < 4; i++) pinMode(PIN_DIGIT[i], OUTPUT);

  lcd.begin(16, 2);
  showIdleLcd();
  setAllLedsOff();
}

void loop() {
  readSerialLines();
  updateLight();
  updateCounterDisplay();
  handleButton();
}
