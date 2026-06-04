from __future__ import annotations

import logging
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceInfo:
    resource_name: str
    model_name: str = ""
    serial_number: str = ""
    manufacturer: str = ""


@dataclass(frozen=True)
class PowerReading:
    power_w: float
    timestamp: float
    raw_value: float | None = None
    unit: str | None = None


class ThorlabsPowerMeterController:
    """Controller for Thorlabs TLPM-compatible power meters."""

    default_dll_name = "Thorlabs.TLPM_64.Interop"

    def __init__(self, library_path: str | os.PathLike[str] | None = None):
        self.library_path = Path(library_path) if library_path else None
        self._tlpm_class = None
        self._device = None
        self._device_info: DeviceInfo | None = None
        self._zero_offset_w = 0.0

    @property
    def is_connected(self) -> bool:
        return self._device is not None

    @property
    def device_info(self) -> DeviceInfo | None:
        return self._device_info

    @property
    def zero_offset_w(self) -> float:
        return self._zero_offset_w

    @classmethod
    def list_devices(cls, library_path: str | os.PathLike[str] | None = None) -> list[DeviceInfo]:
        tlpm = cls._load_tlpm_class(library_path)
        temp = None
        try:
            from System import IntPtr, Text, UInt32

            temp = tlpm(IntPtr(0))
            _, count = temp.findRsrc()
            devices: list[DeviceInfo] = []
            for index in range(int(count)):
                resource = Text.StringBuilder(2048)
                model = Text.StringBuilder(2048)
                serial = Text.StringBuilder(2048)
                manufacturer = Text.StringBuilder(2048)
                temp.getRsrcName(UInt32(index), resource)
                temp.getRsrcInfo(UInt32(index), model, serial, manufacturer)
                devices.append(
                    DeviceInfo(
                        resource_name=resource.ToString(),
                        model_name=model.ToString(),
                        serial_number=serial.ToString(),
                        manufacturer=manufacturer.ToString(),
                    )
                )
            return devices
        finally:
            if temp is not None:
                try:
                    temp.Dispose()
                except Exception:
                    logger.debug("Failed to dispose temporary TLPM instance", exc_info=True)

    def connect(self, resource_name: str | None = None, reset_device: bool = True, id_query: bool = True) -> None:
        if self.is_connected:
            return
        devices = self.list_devices(self.library_path)
        if not devices:
            raise RuntimeError("No Thorlabs TLPM-compatible power meter was detected.")
        info = self._select_device(devices, resource_name)
        tlpm = self._load_tlpm_class(self.library_path)
        self._device = tlpm(info.resource_name, bool(id_query), bool(reset_device))
        self._device_info = info
        logger.info("Connected Thorlabs power meter %s", info.resource_name)

    def disconnect(self) -> None:
        if self._device is None:
            return
        try:
            self._device.Dispose()
        finally:
            logger.info("Disconnected Thorlabs power meter %s", self._device_info.resource_name if self._device_info else "")
            self._device = None
            self._device_info = None

    def set_timeout_ms(self, timeout_ms: int) -> None:
        self._require_connected()
        self._device.setTimeoutValue(int(timeout_ms))

    def get_timeout_ms(self) -> int:
        self._require_connected()
        _, value = self._device.getTimeoutValue()
        return int(value)

    def set_average_time_s(self, average_time_s: float) -> float:
        self._require_connected()
        average_time = self._clamp(float(average_time_s), self.get_average_time_limits_s())
        self._device.setAvgTime(average_time)
        return average_time

    def get_average_time_s(self) -> float:
        self._require_connected()
        _, value = self._device.getAvgTime(0)
        return float(value)

    def get_average_time_limits_s(self) -> tuple[float, float]:
        self._require_connected()
        _, minimum = self._device.getAvgTime(1)
        _, maximum = self._device.getAvgTime(2)
        return float(minimum), float(maximum)

    def set_wavelength_nm(self, wavelength_nm: float) -> float:
        self._require_connected()
        wavelength = self._clamp(float(wavelength_nm), self.get_wavelength_limits_nm())
        self._device.setWavelength(wavelength)
        return wavelength

    def get_wavelength_nm(self) -> float:
        self._require_connected()
        _, value = self._device.getWavelength(0)
        return float(value)

    def get_wavelength_limits_nm(self) -> tuple[float, float]:
        self._require_connected()
        _, minimum = self._device.getWavelength(1)
        _, maximum = self._device.getWavelength(2)
        return float(minimum), float(maximum)

    def set_power_auto_range(self, enabled: bool = True) -> None:
        self._require_connected()
        self._device.setPowerAutoRange(bool(enabled))

    def set_power_range_w(self, max_range_w: float) -> float:
        self._require_connected()
        power_range = self._clamp(float(max_range_w), self.get_power_range_limits_w())
        self._device.setPowerRange(power_range)
        return power_range

    def get_power_range_w(self) -> float:
        self._require_connected()
        _, value = self._device.getPowerRange(0)
        return float(value)

    def get_power_range_limits_w(self) -> tuple[float, float]:
        self._require_connected()
        _, minimum = self._device.getPowerRange(1)
        _, maximum = self._device.getPowerRange(2)
        return float(minimum), float(maximum)

    def get_sensor_info(self) -> dict[str, Any]:
        self._require_connected()
        from System import Text

        description = [Text.StringBuilder(1024), Text.StringBuilder(1024), Text.StringBuilder(1024)]
        _, sensor_type, sensor_subtype, flags = self._device.getSensorInfo(
            description[0],
            description[1],
            description[2],
        )
        return {
            "name": description[0].ToString(),
            "serial_number": description[1].ToString(),
            "calibration_message": description[2].ToString(),
            "type": int(sensor_type),
            "subtype": int(sensor_subtype),
            "flags": int(flags),
        }

    def read_power_w(self) -> float:
        return self.read_power().power_w

    def read_power(self) -> PowerReading:
        self._require_connected()
        _, raw_value = self._device.measPower()
        _, unit_code = self._device.getPowerUnit()
        unit = "W" if int(unit_code) == 0 else "dBm"
        power_w = self._reading_to_watts(raw_value, unit) - self._zero_offset_w
        return PowerReading(power_w=power_w, timestamp=time.monotonic(), raw_value=float(raw_value), unit=unit)

    def average_power_w(self, duration_s: float, sample_interval_s: float = 0.05) -> dict[str, Any]:
        values: list[float] = []
        deadline = time.monotonic() + max(0.0, float(duration_s))
        while time.monotonic() < deadline:
            values.append(self.read_power_w())
            time.sleep(max(0.0, float(sample_interval_s)))
        if not values:
            values.append(self.read_power_w())
        return self._stats(values)

    def zero_offset(self, duration_s: float = 2.0, sample_interval_s: float = 0.05) -> dict[str, Any]:
        values: list[float] = []
        old_offset = self._zero_offset_w
        self._zero_offset_w = 0.0
        try:
            deadline = time.monotonic() + max(0.0, float(duration_s))
            while time.monotonic() < deadline:
                values.append(self.read_power_w())
                time.sleep(max(0.0, float(sample_interval_s)))
            if not values:
                values.append(self.read_power_w())
            stats = self._stats(values)
            self._zero_offset_w = float(stats["mean_w"])
            logger.info("Set Thorlabs zero offset to %.6g W", self._zero_offset_w)
            return stats
        except Exception:
            self._zero_offset_w = old_offset
            raise

    def _require_connected(self) -> None:
        if self._device is None:
            raise RuntimeError("Thorlabs power meter is not connected.")

    @staticmethod
    def _select_device(devices: list[DeviceInfo], resource_name: str | None) -> DeviceInfo:
        if resource_name is None:
            return devices[0]
        for info in devices:
            if info.resource_name == resource_name:
                return info
        available = ", ".join(info.resource_name for info in devices)
        raise RuntimeError(f"Thorlabs resource {resource_name!r} was not found. Available: {available}")

    @classmethod
    def _load_tlpm_class(cls, library_path: str | os.PathLike[str] | None = None):
        try:
            import clr
        except ImportError as exc:
            raise RuntimeError("pythonnet is required for Thorlabs TLPM control.") from exc

        if library_path is not None:
            path = str(Path(library_path).resolve())
            if path not in sys.path:
                sys.path.insert(0, path)
        try:
            clr.AddReference(cls.default_dll_name)
        except Exception as first_exc:
            dll_path = None
            if library_path is not None:
                candidate = Path(library_path) / f"{cls.default_dll_name}.dll"
                if candidate.exists():
                    dll_path = str(candidate.resolve())
            if dll_path is None:
                raise RuntimeError(
                    "Cannot load Thorlabs.TLPM_64.Interop. Install Thorlabs Optical Power Monitor "
                    "or pass the folder containing Thorlabs.TLPM_64.Interop.dll."
                ) from first_exc
            clr.AddReference(dll_path)

        from Thorlabs.TLPM_64.Interop import TLPM

        return TLPM

    @staticmethod
    def _clamp(value: float, limits: tuple[float, float]) -> float:
        minimum, maximum = limits
        return min(max(value, minimum), maximum)

    @staticmethod
    def _reading_to_watts(value: Any, unit: str) -> float:
        reading = float(value)
        if unit == "W":
            return reading
        if unit == "dBm":
            return 1e-3 * 10 ** (reading / 10.0)
        raise RuntimeError(f"Unsupported power unit: {unit}")

    @staticmethod
    def _stats(values: list[float]) -> dict[str, Any]:
        finite = [value for value in values if math.isfinite(value)]
        if not finite:
            raise RuntimeError("No finite power readings were collected.")
        mean = sum(finite) / len(finite)
        variance = sum((value - mean) ** 2 for value in finite) / len(finite)
        return {
            "mean_w": mean,
            "min_w": min(finite),
            "max_w": max(finite),
            "std_w": variance ** 0.5,
            "n": len(finite),
            "values_w": finite,
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.disconnect()
        return False

    def __del__(self):
        try:
            self.disconnect()
        except Exception:
            pass
