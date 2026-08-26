# Serial Protocol

## Transport

- Baud rate: 115200
- Data bits: 8
- Stop bits: 1
- Parity: None
- Flow control: None
- Encoding: ASCII
- Line ending: `\n`

## Grammar

Command format:

```text
$ID=<n> CMD=<COMMAND> [PARAMETERS...]
```

Responses:

```text
@OK ID=<n> CMD=<COMMAND>
@DONE ID=<n> CMD=<COMMAND> [PARAMETERS...]
@STATUS STATE=<STATE> X=<x> Y=<y>
@ALARM CODE=<CODE>
@ERROR ID=<n> CODE=<ERROR>
```

Integer and float values are serialized in decimal form. Example:

```text
$ID=42 CMD=MOVE X=53.400 Y=126.975 F=40.0
```

## Commands

### PING

```text
$ID=<n> CMD=PING
```

Response:

```text
@OK ID=<n> CMD=PING
@DONE ID=<n> CMD=PING
```

### STATUS

```text
$ID=<n> CMD=STATUS
```

Response:

```text
@STATUS STATE=IDLE X=0.000 Y=0.000
```

### HOME

```text
$ID=<n> CMD=HOME
```

### MOVE

```text
$ID=<n> CMD=MOVE X=<mm> Y=<mm> F=<steps/s> A=<steps/s^2>
```

### JOG

```text
$ID=<n> CMD=JOG AXIS=X DIST=<mm> F=<mm/s>
```

### STOP

```text
$ID=<n> CMD=STOP
```

### ESTOP

```text
$ID=<n> CMD=ESTOP
```

### CLEAR_ALARM

```text
$ID=<n> CMD=CLEAR_ALARM
```

### ZERO

```text
$ID=<n> CMD=ZERO X=<mm> Y=<mm>
```

### TRIGGER

```text
$ID=<n> CMD=TRIGGER MS=<duration>
```

## Error Semantics

- `@ERROR` indicates an invalid command or malformed payload.
- `@ALARM` indicates unsafe or hardware fault conditions.
- `@OK` confirms command acceptance.
- `@DONE` confirms operation completion.

## Safety Rules

- Every command must include an ID.
- Only one motion command may be active at a time.
- STOP and ESTOP take priority over normal motion.
- Malformed or partial commands are rejected.
- Serial disconnects must not cause motion.
- The Python-side controller must enforce command timeout.
