#include <Arduino.h>
#include "config.h"
#include "protocol.h"

char inputBuffer[MAX_LINE_LENGTH];
size_t inputLength = 0;
float currentX = 0.0f;
float currentY = 0.0f;
char currentState[] = "IDLE";

void sendOk(const ParsedCommand& cmd) {
  char response[MAX_RESPONSE_LENGTH];
  snprintf(response, sizeof(response), "@OK ID=%d CMD=%s\n", cmd.id, cmd.command);
  Serial.print(response);
}

void sendDone(const ParsedCommand& cmd) {
  char response[MAX_RESPONSE_LENGTH];
  snprintf(response, sizeof(response), "@DONE ID=%d CMD=%s\n", cmd.id, cmd.command);
  Serial.print(response);
}

void sendStatus(float x, float y, const char* state) {
  char response[MAX_RESPONSE_LENGTH];
  snprintf(response, sizeof(response), "@STATUS STATE=%s X=%.3f Y=%.3f\n", state, x, y);
  Serial.print(response);
}

void sendError(int id, const char* code) {
  char response[MAX_RESPONSE_LENGTH];
  snprintf(response, sizeof(response), "@ERROR ID=%d CODE=%s\n", id, code);
  Serial.print(response);
}

bool parseCommandLine(const char* line, ParsedCommand& out) {
  out.valid = false;
  out.hasId = false;
  out.id = -1;
  out.command[0] = '\0';

  if (line == nullptr || line[0] != '$') {
    return false;
  }

  char buffer[MAX_LINE_LENGTH];
  snprintf(buffer, sizeof(buffer), "%s", line);

  char* token = strtok(buffer, " \t\r\n");
  if (token == nullptr || strncmp(token, "$ID=", 4) != 0) {
    return false;
  }

  char* cmdToken = strtok(nullptr, " \t\r\n");
  if (cmdToken == nullptr || strncmp(cmdToken, "CMD=", 4) != 0) {
    return false;
  }

  out.id = atoi(token + 4);
  snprintf(out.command, sizeof(out.command), "%s", cmdToken + 4);
  out.hasId = true;
  out.valid = (out.id >= 0 && out.command[0] != '\0');
  return out.valid;
}

bool parseFloatToken(const char* key, const char* value, float& outValue) {
  if (strncmp(key, key, 1) == 0) {
    outValue = atof(value);
    return true;
  }
  return false;
}

void pulseStep(uint8_t pulPin, uint8_t dirPin, uint16_t steps, bool directionPositive, unsigned long delayUs) {
  digitalWrite(dirPin, directionPositive ? HIGH : LOW);
  delayMicroseconds(1000);

  for (uint16_t i = 0; i < steps; ++i) {
    digitalWrite(pulPin, HIGH);
    delayMicroseconds(delayUs);
    digitalWrite(pulPin, LOW);
    delayMicroseconds(delayUs);
  }
}

void processMoveCommand(const ParsedCommand& cmd, const char* line) {
  char temp[96];
  snprintf(temp, sizeof(temp), "%s", line);

  char* token = strtok(temp, " \t");
  token = strtok(nullptr, " \t");
  float xTarget = 0.0f;
  float yTarget = 0.0f;
  float feed = 10.0f;

  while ((token = strtok(nullptr, " \t")) != nullptr) {
    if (strncmp(token, "X=", 2) == 0) {
      xTarget = atof(token + 2);
    } else if (strncmp(token, "Y=", 2) == 0) {
      yTarget = atof(token + 2);
    } else if (strncmp(token, "F=", 2) == 0) {
      feed = atof(token + 2);
    }
  }

  const float deltaX = xTarget - currentX;
  const float deltaY = yTarget - currentY;
  const unsigned long pulseDelay = feed > 0.0f ? (unsigned long)(500000.0f / feed) : 5000UL;

  if (deltaX != 0.0f) {
    const uint16_t stepCount = (uint16_t)abs((int)round(deltaX * STEPS_PER_MM));
    pulseStep(X_PUL_PIN, X_DIR_PIN, stepCount, deltaX > 0.0f, pulseDelay);
    currentX = xTarget;
  }

  if (deltaY != 0.0f) {
    const uint16_t stepCount = (uint16_t)abs((int)round(deltaY * STEPS_PER_MM));
    pulseStep(Y_PUL_PIN, Y_DIR_PIN, stepCount, deltaY > 0.0f, pulseDelay);
    currentY = yTarget;
  }

  sendOk(cmd);
  sendDone(cmd);
}

void processCommand(const ParsedCommand& cmd, const char* line) {
  if (!cmd.valid) {
    sendError(-1, "INVALID_COMMAND");
    return;
  }

  if (strcmp(cmd.command, "PING") == 0) {
    sendOk(cmd);
    sendDone(cmd);
    return;
  }

  if (strcmp(cmd.command, "STATUS") == 0) {
    sendStatus(currentX, currentY, currentState);
    return;
  }

  if (strcmp(cmd.command, "MOVE") == 0) {
    processMoveCommand(cmd, line);
    return;
  }

  sendError(cmd.id, "UNSUPPORTED_COMMAND");
}

void moveAxisPulseBurst(uint8_t pulPin, uint8_t dirPin, uint16_t steps, bool directionPositive, unsigned long delayUs) {
  digitalWrite(dirPin, directionPositive ? HIGH : LOW);
  delay(50);

  for (uint16_t i = 0; i < steps; ++i) {
    digitalWrite(pulPin, HIGH);
    delayMicroseconds(delayUs);
    digitalWrite(pulPin, LOW);
    delayMicroseconds(delayUs);
  }

  digitalWrite(pulPin, LOW);
}

void runDebugPulseBurst() {
  const uint16_t turns = 4;
  const unsigned long delayUs = 2500UL;

  moveAxisPulseBurst(X_PUL_PIN, X_DIR_PIN, STEPS_PER_TURN * turns, true, delayUs);
  moveAxisPulseBurst(Y_PUL_PIN, Y_DIR_PIN, STEPS_PER_TURN * turns, true, delayUs);
}

void setup() {
  pinMode(X_PUL_PIN, OUTPUT);
  pinMode(X_DIR_PIN, OUTPUT);
  pinMode(Y_PUL_PIN, OUTPUT);
  pinMode(Y_DIR_PIN, OUTPUT);
  pinMode(ENABLE_PIN, OUTPUT);
  digitalWrite(X_PUL_PIN, LOW);
  digitalWrite(X_DIR_PIN, LOW);
  digitalWrite(Y_PUL_PIN, LOW);
  digitalWrite(Y_DIR_PIN, LOW);
  digitalWrite(ENABLE_PIN, LOW);

  // Startup debug motion intentionally disabled for normal operation.
  Serial.begin(SERIAL_BAUD);
  delay(500);
  Serial.println("READY");
  inputLength = 0;
  memset(inputBuffer, 0, sizeof(inputBuffer));
}

void loop() {
  while (Serial.available() > 0) {
    char ch = Serial.read();
    if (ch == '\r') {
      continue;
    }

    if (ch == '\n') {
      if (inputLength > 0) {
        inputBuffer[inputLength] = '\0';
        Serial.print("RX:");
        Serial.println(inputBuffer);
        ParsedCommand cmd = {};
        if (parseCommandLine(inputBuffer, cmd)) {
          processCommand(cmd, inputBuffer);
        } else {
          sendError(-1, "INVALID_COMMAND");
        }
        inputLength = 0;
        memset(inputBuffer, 0, sizeof(inputBuffer));
      }
      continue;
    }

    if (inputLength < sizeof(inputBuffer) - 1) {
      inputBuffer[inputLength++] = ch;
    } else {
      inputLength = 0;
      memset(inputBuffer, 0, sizeof(inputBuffer));
      sendError(-1, "MESSAGE_TOO_LONG");
    }
  }
}
