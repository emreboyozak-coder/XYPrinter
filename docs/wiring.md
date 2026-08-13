# Wiring Notes

## Initial motion pin mapping

- Arduino digital pin 3 -> DM556 +PUL
- Arduino digital pin 2 -> DM556 +DIR
- Arduino GND -> DM556 ground reference
- DM556 ENA, limit, home, and emergency-stop wiring remain to be finalized in Phase 3+

This mapping is intentionally simple and should be verified with an oscilloscope or logic tester before driving the motor at full current.
