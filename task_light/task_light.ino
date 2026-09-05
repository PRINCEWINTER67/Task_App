/*
  task_light.ino
  ------------------------------------------------------------
  Physical control panel for the Task Status Tracker app (task_app.py).
  Drives:
    - 4 status LEDs (red / yellow / blue / green) showing task urgency
    - a 16x2 I2C LCD, navigated with an analog joystick module:
        click (short)  -> toggle the screen on/off. This never changes
                           when the lights themselves are due to switch -
                           it only shows/hides the screen.
        click (5s hold) -> full shutdown: LCD shows "SHUT DOWN" for 5s
                           then goes dark, and every LED forces off too,
                           even if a task would otherwise light one up.
                           Holding it again for 5s wakes everything back
                           up to its current real status immediately.
        up / down      -> move to the previous/next task (shows its name)
        left           -> show the total pending count
        right          -> show the currently-selected task's due date

  Talks to task_app.py over USB serial at 9600 baud using a tiny
  line-based text protocol (each line ends with '\n'):

    L:<0-4>          urgency light state
                        0 = RED solid   (a task is due within the hour, or overdue)
                        1 = RED blink   (a task is due later today)
                        2 = BLUE solid  (nearest task due tomorrow)
                        3 = YELLOW solid (nearest task due later than tomorrow)
                        4 = GREEN solid (nothing pending)
    N:<0-6>          how many task lines follow (resets the joystick's list)
    I:<name>|<due>   one task line (name + short due label, each already
                      trimmed to <=16 chars by the Python side), sent N
                      times right after an N: line

  HARDWARE:
    - 4x LED (red/yellow/blue/green) on pins 2-5, each through a
      resistor to GND.
    - 1x analog joystick module, wired directly (no breadboard needed):
      GND->GND, +5V->5V, VRx->A0, VRy->A1, SW->D6 (INPUT_PULLUP).
    - 1x 16x2 I2C LCD - 4 wires (GND, VCC, SDA->A4, SCL->A5). Needs the
      "LiquidCrystal I2C" library (Frank de Brabander) installed via
      Library Manager. Blank screen once it's on? Try changing
      LCD_I2C_ADDRESS below from 0x27 to 0x3F - the two common backpack
      addresses.

    NOTE: whether "up" reads as a high or low analog value depends on
    which way your specific joystick happens to be oriented - if
    up/down or left/right come out swapped or backwards once you test
    it, that's a one-line fix in handleJoystick() below (swap the two
    branches for that axis), not a rewiring issue.
*/

#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// ---------------- PIN MAP ----------------
const uint8_t PIN_LED_RED    = 2;
const uint8_t PIN_LED_YELLOW = 3;
const uint8_t PIN_LED_BLUE   = 4;
const uint8_t PIN_LED_GREEN  = 5;

const uint8_t PIN_JOY_SW  = 6;   // joystick click, INPUT_PULLUP
const uint8_t PIN_JOY_VRX = A0;  // joystick left/right
const uint8_t PIN_JOY_VRY = A1;  // joystick up/down

#define LCD_I2C_ADDRESS 0x27
LiquidCrystal_I2C lcd(LCD_I2C_ADDRESS, 16, 2);

// ---------------- LIGHT STATE ----------------
uint8_t lightState = 4; // start on green/idle until the app sends real state
unsigned long lastBlinkToggle = 0;
bool blinkOn = false;
const unsigned long BLINK_INTERVAL_MS = 500;

// Full shutdown override (5-second joystick hold) - forces LEDs off and
// the LCD dark regardless of lightState/screenOn, without changing
// either of those, so waking up resumes exactly where things really are.
bool systemShutdown = false;

void setAllLedsOff() {
  digitalWrite(PIN_LED_RED, LOW);
  digitalWrite(PIN_LED_YELLOW, LOW);
  digitalWrite(PIN_LED_BLUE, LOW);
  digitalWrite(PIN_LED_GREEN, LOW);
}

void updateLight() {
  if (systemShutdown) {
    setAllLedsOff();
    return;
  }
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

// ---------------- LCD VIEW STATE ----------------
bool screenOn = false;
uint8_t taskIndex = 0;

enum ViewMode { MODE_NAME, MODE_DATE, MODE_COUNT };
ViewMode viewMode = MODE_NAME;

void drawCurrentPage() {
  lcd.clear();
  if (viewMode == MODE_COUNT || taskCount == 0) {
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
    return;
  }

  lcd.setCursor(0, 0);
  lcd.print(taskName[taskIndex]);
  lcd.setCursor(0, 1);
  if (viewMode == MODE_DATE) {
    char line[17];
    snprintf(line, sizeof(line), "Due: %s", taskDue[taskIndex]);
    lcd.print(line);
  } else { // MODE_NAME
    char line[17];
    snprintf(line, sizeof(line), "Task %u/%u", (unsigned)(taskIndex + 1), (unsigned)taskCount);
    lcd.print(line);
  }
}

void redrawIfOn() {
  if (screenOn) drawCurrentPage();
}

// ---------------- SHUTDOWN (5-second joystick hold) ----------------
bool shutdownMessageActive = false;
unsigned long shutdownMessageStart = 0;
const unsigned long SHUTDOWN_MESSAGE_MS = 5000;

void enterShutdown() {
  systemShutdown = true;
  shutdownMessageActive = true;
  shutdownMessageStart = millis();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("SHUT DOWN");
}

void exitShutdown() {
  systemShutdown = false;
  shutdownMessageActive = false;
  if (screenOn) {
    lcd.backlight();
    drawCurrentPage();
  } else {
    lcd.noBacklight();
  }
}

void updateShutdownMessage() {
  if (shutdownMessageActive && millis() - shutdownMessageStart >= SHUTDOWN_MESSAGE_MS) {
    shutdownMessageActive = false;
    lcd.clear();
    lcd.noBacklight();
  }
}

// ---------------- JOYSTICK: short click toggles screen, 5s hold
// toggles shutdown, tilt navigates ----------------
bool lastSwReading = HIGH;
bool swState = HIGH;
unsigned long lastSwDebounce = 0;
const unsigned long DEBOUNCE_MS = 40;

unsigned long pressStartTime = 0;
bool longPressFired = false;
const unsigned long LONG_PRESS_MS = 5000;

const int TILT_LOW = 340;   // below this = tilted toward "low" side
const int TILT_HIGH = 680;  // above this = tilted toward "high" side
enum Direction { DIR_NONE, DIR_UP, DIR_DOWN, DIR_LEFT, DIR_RIGHT };
Direction lastDirection = DIR_NONE;

void handleJoystickClick() {
  bool reading = digitalRead(PIN_JOY_SW);
  if (reading != lastSwReading) {
    lastSwDebounce = millis();
  }
  if (millis() - lastSwDebounce > DEBOUNCE_MS && reading != swState) {
    swState = reading;
    if (swState == LOW) { // just pressed (INPUT_PULLUP -> LOW on press)
      pressStartTime = millis();
      longPressFired = false;
    } else { // just released
      if (!longPressFired && !systemShutdown) {
        // short click - toggle the screen only, lights are untouched
        screenOn = !screenOn;
        if (screenOn) {
          lcd.backlight();
          taskIndex = 0;
          viewMode = MODE_NAME;
          drawCurrentPage();
        } else {
          lcd.clear();
          lcd.noBacklight();
        }
      }
    }
  }
  if (swState == LOW && !longPressFired && millis() - pressStartTime >= LONG_PRESS_MS) {
    longPressFired = true;
    if (systemShutdown) {
      exitShutdown();
    } else {
      enterShutdown();
    }
  }
  lastSwReading = reading;
}

void handleJoystickTilt() {
  int x = analogRead(PIN_JOY_VRX);
  int y = analogRead(PIN_JOY_VRY);

  Direction dir = DIR_NONE;
  if (y < TILT_LOW) dir = DIR_UP;
  else if (y > TILT_HIGH) dir = DIR_DOWN;
  else if (x < TILT_LOW) dir = DIR_LEFT;
  else if (x > TILT_HIGH) dir = DIR_RIGHT;

  if (systemShutdown) {
    // Keep tracking the tilt so a held direction doesn't fire a
    // surprise step the instant the system wakes back up.
    lastDirection = dir;
    return;
  }

  // Only act on the moment the stick moves from centered into a
  // direction - not continuously while held over, so one tilt = one step.
  if (dir != DIR_NONE && lastDirection == DIR_NONE) {
    switch (dir) {
      case DIR_UP:
        if (taskCount > 0) {
          taskIndex = (taskIndex == 0) ? taskCount - 1 : taskIndex - 1;
          viewMode = MODE_NAME;
        }
        break;
      case DIR_DOWN:
        if (taskCount > 0) {
          taskIndex = (taskIndex + 1) % taskCount;
          viewMode = MODE_NAME;
        }
        break;
      case DIR_LEFT:
        viewMode = MODE_COUNT;
        break;
      case DIR_RIGHT:
        viewMode = MODE_DATE;
        break;
      default:
        break;
    }
    redrawIfOn();
  }
  lastDirection = dir;
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
    taskIndex = 0;
    redrawIfOn();
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

  pinMode(PIN_JOY_SW, INPUT_PULLUP);

  lcd.init();
  lcd.noBacklight(); // screen starts OFF until the joystick is clicked
}

void loop() {
  readSerialLines();
  updateLight();
  handleJoystickClick();
  handleJoystickTilt();
  updateShutdownMessage();
}
