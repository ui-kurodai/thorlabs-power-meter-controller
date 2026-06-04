# thorlabs-power-meter-controller

Small Python controller for Thorlabs TLPM-compatible optical power meters, intended for use with sensors such as S120C through PM100/PM200/PM400-class consoles.

This package is a clean packaging-oriented controller that uses Python's standard `logging` module. It does not depend on Tinyblack's `GlobalLogger` helper.

## Requirements

- Windows
- Thorlabs Optical Power Monitor / TLPM runtime installed
- `Thorlabs.TLPM_64.Interop.dll` available through the Thorlabs installation or a path passed to `list_devices()` / `connect()`
- Python package dependencies from `pyproject.toml`

## Install From GitHub

```powershell
uv add git+https://github.com/ui-kurodai/thorlabs_power_meter_controller
```

## Basic Usage

```python
from thorlabs_power_meter_controller import ThorlabsPowerMeterController

resources = ThorlabsPowerMeterController.list_devices()
print(resources)

meter = ThorlabsPowerMeterController()
meter.connect(resources[0].resource_name)
meter.set_wavelength_nm(532)
meter.set_power_auto_range(True)
meter.zero_offset(duration_s=2.0)
print(meter.read_power_w())
meter.disconnect()
```

## Attribution

This project was written for packaging and integration convenience after testing ideas from:

- https://github.com/Tinyblack/Python-Driver-for-Thorlabs-power-meter
- https://github.com/Tinyblack/GlobalLogger

Those projects are MIT licensed. This package uses its own implementation style and standard Python logging, but the practical TLPM API calls are informed by the public Tinyblack implementation and Thorlabs' TLPM API.
