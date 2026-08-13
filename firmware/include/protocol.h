#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <Arduino.h>

constexpr size_t MAX_RESPONSE_LENGTH = 96;

struct ParsedCommand {
    int id;
    char command[16];
    bool valid;
    bool hasId;
};

bool parseCommandLine(const char* line, ParsedCommand& out);
void sendOk(const ParsedCommand& cmd);
void sendDone(const ParsedCommand& cmd);
void sendStatus(float x, float y, const char* state);
void sendError(int id, const char* code);

#endif
