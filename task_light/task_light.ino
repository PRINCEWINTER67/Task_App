/*
  task_light.ino
  ------------------------------------------------------------
  Physical control panel for the Task Status Tracker app (task_app.py).
  Drives:
    - 4 status LEDs (red / yellow / blue / green) showing task urgency
    - a 16x2 I2C LCD that toggles on/off with a long button press, and
      while on, automatically rotates through a "how many pending"
      summary screen and each individual pending task

  Talks to task_app.py over USB serial at 9600 baud using a tiny
  line-based text protocol (each line ends with '\n'):

    L:<0-4>          urgency light state
                        0 = RED solid   (a task is due within the hour, or overdue)
                        1 = RED blink   (a task is due later today)
                        2 = BLUE solid  (nearest task due tomorrow)
                        3 = YELLOW solid (nearest task due later than tomorrow)
                        4 = GREEN solid (nothing pending)
    N:<0-6>          how many task lines follow (resets the LCD's list)
    I:<name>|<due>   one task line (name + short due label, each already
                      trimmed to <=16 chars by the Python side), sent N
                      times right after an N: line

  HARDWARE:
    - 4x LED (red/yellow/blue/green) on pins 2-5, each through a
      resistor to GND.
    - 1x push button on pin 6 (INPUT_PULLUP), other leg to GND.
    - 1x 16x2 I2C LCD - just 4 wires (GND, VCC, SDA->A4, SCL->A5), no
      shift register or contrast pot needed, the backpack handles both.
      Needs the "LiquidCrystal I2C" library (Frank de Brabander)
      installed via Library Manager. If the screen shows nothing once
      it's on, try changing LCD_I2C_ADDRESS below from 0x27 to 0x3F -
      those are the two common backpack addresses.
*/

#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// ---------------- PIN MAP ----------------
const uint8_t PIN_LED_RED    = 2;
const uint8_t PIN_LED_YELLOW = 3;
const uint8_t PIN_LED_BLUE   = 4;
const uint8_t PIN_LED_GREEN  = 5;
const uint8_t PIN_BUTTON     = 6;   // other leg to GND, uses INPUT_PULLUP

#define LCD_I2C_ADDRESS 0x27
LiquidCrystal_I2C lcd(LCD_I2C_ADDRESS, 16, 2);

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

// ---------------- TASK LIST (for the LCD) ----------------
#define MAX_TASKS 6
char taskName[MAX_TASKS][17];
char taskDue[MAX_TASKS][17];
uint8_t taskCount = 0;
uint8_t taskFillIndex = 0;

// ---------------- LCD PAGE CYCLING (while the screen is on) ----------------
bool screenOn = false;
uint8_t lcdPageIndex = 0; // 0 = summary, 1..taskCount = that task
unsigned long lastCycleTime = 0;
const unsigned long CYCLE_INTERVAL_MS = 2500;

void drawCurrentPage() {
  lcd.clear();
  if (lcdPageIndex == 0) {
    lcd.setCursor(0, 0);
    lcd.print("Task Tracker");
    lcd.setCursor(0, 1);
    if (taskCount == 0) {
      lcd.print("All caught up!");
    } else {
      char line[17];
      snprintf(line, sizeof(line), "%u pending", (unsigned)taskCount);
      lcd.print(line);
    }
  } else {
    uint8_t i = lcdPageIndex - 1;
    lcd.setCursor(0, 0);
    lcd.print(taskName[i]);
    lcd.setCursor(0, 1);
    lcd.print(taskDue[i]);
  }
}

void updateLcdCycle() {
  if (!screenOn) return;
  if (millis() - lastCycleTime < CYCLE_INTERVAL_MS) return;
  lastCycleTime = millis();
  uint8_t totalPages = taskCount + 1; // summary + one per task
  lcdPageIndex = (lcdPageIndex + 1) % totalPages;
  drawCurrentPage();
}

// ---------------- BUTTON: 3-SECOND LONG PRESS TOGGLES THE SCREEN ----------------
bool lastButtonReading = HIGH;
bool buttonState = HIGH;
unsigned long lastDebounceTime = 0;
const unsigned long DEBOUNCE_MS = 40;

unsigned long pressStartTime = 0;
bool longPressFired = false;
const unsigned long LONG_PRESS_MS = 3000;

void handleButton() {
  bool reading = digitalRead(PIN_BUTTON);
  if (reading != lastButtonReading) {
    lastDebounceTime = millis();
  }
  if (millis() - lastDebounceTime > DEBOUNCE_MS && reading != buttonState) {
    buttonState = reading;
    if (buttonState == LOW) { // just pressed (INPUT_PULLUP -> LOW on press)
      pressStartTime = millis();
      longPressFired = false;
    }
  }
  if (buttonState == LOW && !longPressFired && millis() - pressStartTime >= LONG_PRESS_MS) {
    longPressFired = true;
    screenOn = !screenOn;
    if (screenOn) {
      lcd.backlight();
      lcdPageIndex = 0;
      lastCycleTime = millis();
      drawCurrentPage();
    } else {
      lcd.clear();
      lcd.noBacklight();
    }
  }
  lastButtonReading = reading;
}

// ---------------- SERIAL PROTOCOL ----------------
#define LINE_BUF_LEN 40
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
  } else if (line[0] == 'N' && line[1] == ':') {
    int v = atoi(line + 2);
    if (v < 0) v = 0;
    if (v > MAX_TASKS) v = MAX_TASKS;
    taskCount = (uint8_t)v;
    taskFillIndex = 0;
    if (screenOn) {
      lcdPageIndex = 0;
      lastCycleTime = millis();
      drawCurrentPage();
    }
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
  // C: (old counter-display protocol line) is intentionally ignored -
  // there's no 7-segment display on this build anymore.
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

  pinMode(PIN_BUTTON, INPUT_PULLUP);

  lcd.init();
  lcd.noBacklight(); // screen starts OFF until the button is held 3s
}

void loop() {
  readSerialLines();
  updateLight();
  handleButton();
  updateLcdCycle();
}
