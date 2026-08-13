#ifndef CONFIG_H
#define CONFIG_H

constexpr unsigned long SERIAL_BAUD = 115200;
constexpr size_t MAX_LINE_LENGTH = 128;
constexpr uint8_t DEFAULT_STATE = 0;

// Hardware wiring for initial prototype:
// X axis: Arduino D3 -> DM556 X +PUL, Arduino D2 -> DM556 X +DIR
// Y axis: Arduino D7 -> DM556 Y +PUL, Arduino D6 -> DM556 Y +DIR
// DM556 -PUL and -DIR should be tied to the Arduino ground reference.
constexpr uint8_t X_PUL_PIN = 3;
constexpr uint8_t X_DIR_PIN = 2;
constexpr uint8_t Y_PUL_PIN = 7;
constexpr uint8_t Y_DIR_PIN = 6;
constexpr uint8_t ENABLE_PIN = 8;

// Motor calibration:
// NEMA 17 stepper with 4mm pitch lead screw
// Measured: 1 turn = 4 mm linear movement
constexpr uint16_t STEPS_PER_TURN = 400;
constexpr float LEAD_SCREW_PITCH_MM = 4.0f;
constexpr float MM_PER_STEP = LEAD_SCREW_PITCH_MM / STEPS_PER_TURN;  // 0.01 mm/step
constexpr float STEPS_PER_MM = STEPS_PER_TURN / LEAD_SCREW_PITCH_MM; // 100 steps/mm

#endif
