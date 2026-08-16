"""Piece 23.2 (revised Piece 36): category -> spec-field definitions for the
inventory item form. The 439-item Vixinman solar catalog (vendors, items,
tools, vehicles) that used to seed a fresh database is gone — a household
starts with an empty inventory and adds only what it actually has; these
category/spec-field definitions are the part that's still generic enough to
keep, since they just describe what fields to show when someone does add an
item in one of these categories."""

# Category -> ordered spec field names (cleaned headers).
INVENTORY_CATEGORY_SPECS = {
    'Battery': ['Type', 'Voltage', 'AH Rating', 'Max Discharge', 'Max Charge', 'Bulk Volts', 'Absorb Volts', 'Float Volts', 'Temp Comp (mV/deg C)', 'Absorb Min', 'EQ Volts', 'EQ Time (Min)', 'Capacity'],
    'Generator': ['Rating', 'Output Breaker (A)'],
    'Inverter': ['Pout Rated (kW)', 'Pout 30 min surge', 'Vout', 'Iout Max', 'Phase', 'Vin Max', 'DC Input Power Max (W)', 'Pout 1 min surge (kW)', 'Vin Min', 'Battery Voltage'],
    'Charge Controller': ['Max Output (Amps)', 'Max Input (Volts)', 'Min Input (Volts)', 'System Voltage (Volts)', 'Max Solar (Watts)'],
    'Optimizer': ['Rating', 'Vin Max', 'Isc max', 'Iin max', 'Iout max', 'Vout max', 'Vout off', 'Minimum String Length', 'Maximum String Length', 'Maximum Power Per String'],
    'PV': ['Rating', 'Vmp', 'Imp', 'Voc', 'Isc'],
    'Breaker': ['Rating'],
    'Breaker Panel': [],
    'Controls': [],
    'Electrical': [],
    'Wire': [],
    'Monitoring': [],
    'Enclosure': [],
    'Pumping': [],
    'Racking': [],
}
