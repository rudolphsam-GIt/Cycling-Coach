"""
Average power a course asks for at a target time, from the standard road cycling power equation:
lifting the rider and bike, rolling resistance and air drag, divided by drivetrain efficiency.

It works from average speed, so it reads air drag a little low (drag grows with the cube of speed,
and speed varies over a course), and it counts all the climbing as work with nothing back on the
descents. CdA and Crr are typical road values, not the rider's own. Treat the answer as an estimate.
"""
from __future__ import annotations

G = 9.81                # m/s²
CD_A = 0.32             # drag area (m²), riding on the hoods
RHO = 1.18              # air density (kg/m³), sea level on a mild day
CRR = 0.004             # rolling resistance, good road tyres
DRIVETRAIN_EFF = 0.976  # share of the rider's power that reaches the wheel
BIKE_KG = 8.0           # a typical road bike with bottles


def required_power(distance_km: float, climb_m: float, seconds: float, rider_kg: float,
                   bike_kg: float = BIKE_KG) -> dict | None:
    """Watts for each part ({climb, rolling, air}, measured at the wheel) and the rider's
    average power (total). None when there is no distance or time."""
    if distance_km <= 0 or seconds <= 0:
        return None
    mass = rider_kg + bike_kg
    speed = distance_km * 1000 / seconds                 # m/s
    climb = mass * G * max(climb_m, 0) / seconds
    rolling = CRR * mass * G * speed
    air = 0.5 * RHO * CD_A * speed ** 3
    return {"climb": climb, "rolling": rolling, "air": air,
            "total": (climb + rolling + air) / DRIVETRAIN_EFF, "speed_kph": speed * 3.6}
