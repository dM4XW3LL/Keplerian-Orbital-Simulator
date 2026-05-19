# Kepler Orbit Simulator

A real-time orbital mechanics simulator using Kepler's equation.

**Architecture:** C physics engine (Newton-Raphson solver) compiled as a 
shared library, called from a Python/Tkinter GUI via `ctypes`.

## Features
- Spawn arbitrary Keplerian orbits around the Sun
- Built-in presets for all solar system planets
- Adjustable simulation speed and trail length
- Auto-fills orbital period via Kepler's 3rd law

## Build & Run
```bash
make              # compile C shared library
python3 orbit_sim.py
```
**Note: On windows make should be replaced by:

gcc -gcc -O2 -fPIC -shared -o kepler.dll kepler.c -lm
**

## Requirements
- gcc
- Python 3.10+, matplotlib, numpy
