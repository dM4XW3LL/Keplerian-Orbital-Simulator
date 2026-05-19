# ─────────────────────────────────────────────────────────────
#  Kepler Orbit Simulator — Makefile
#  Builds kepler.so (Linux) or kepler.dylib (macOS)
# ─────────────────────────────────────────────────────────────

CC      = gcc
CFLAGS  = -O2 -fPIC -Wall -Wextra
SRC     = kepler.c
HDR     = kepler.h

# Detect OS automatically
UNAME := $(shell uname)

ifeq ($(UNAME), Darwin)
    # macOS
    LIB     = kepler.dylib
    LDFLAGS = -shared -lm -Wl,--export-dynamic
else
    # Linux (default)
    LIB     = kepler.so
    LDFLAGS = -shared -lm -Wl,--export-dynamic
endif

.PHONY: all clean run

all: $(LIB)
	@echo "Built $(LIB) successfully."
	@echo "Run the simulator with: python3 orbit_sim.py"

$(LIB): $(SRC) $(HDR)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(SRC)

run: $(LIB)
	python3 orbit_sim.py

clean:
	rm -f kepler.so kepler.dylib
	@echo "Cleaned build artifacts."
