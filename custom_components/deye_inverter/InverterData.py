import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, TypeVar

from pysolarmanv5.pysolarmanv5 import PySolarmanV5, NoSocketAvailableError

from .const import (
    CORE_REGISTER_BLOCKS,
    DEFAULT_MOD,
    DEFAULT_MODBUS_TIMEOUT,
    OPTIONAL_REGISTER_BLOCKS,
)
from .InverterDataParser import parse_raw
from .profiles import get_profile

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")

# How long to wait before reading a written register back a second time.
# The inverter sometimes still reports the old value right after a write,
# especially when several writes arrive in quick succession.
WRITE_SETTLE_SECONDS = 1.0


class ModbusReadError(Exception):
    """Raised when reading registers from the inverter fails."""


class ModbusWriteError(Exception):
    """Raised when a write is refused, fails, or does not read back."""


def _block_report(
    start: int, end: int, regs: Optional[List[int]], error: Optional[str] = None
) -> Dict[str, Any]:
    """Describe one block read, for the diagnostics download."""
    report: Dict[str, Any] = {
        "range": f"0x{start:04X}-0x{end:04X}",
        "expected": end - start + 1,
        "received": len(regs) if regs is not None else 0,
        "ok": regs is not None,
    }
    if error is not None:
        report["error"] = error
    if regs is not None:
        report["registers"] = {f"0x{start + i:04X}": v for i, v in enumerate(regs)}
        report["hex"] = " ".join(f"{v:04X}" for v in regs)
    return report


@dataclass(frozen=True)
class DeviceCapabilities:
    """What the inverter reports about itself, when it reports it."""

    rated_power: Optional[float] = None  # W
    mppts: Optional[int] = None
    phases: Optional[int] = None


def test_connection(host: str, port: int, serial: str) -> DeviceCapabilities:
    """Open a connection, read one register and the device capabilities.

    Raises on a failed connection; the capability read is best-effort, since
    not every device exposes those registers. Blocking: must run in an
    executor.
    """
    modbus = PySolarmanV5(
        host,
        int(serial),
        port=port,
        mb_slave_id=1,
        timeout=DEFAULT_MODBUS_TIMEOUT,
        verbose=False,
        auto_reconnect=False,
        logger=_LOGGER,
    )
    try:
        modbus.read_holding_registers(
            register_addr=CORE_REGISTER_BLOCKS[0][0], quantity=1
        )
        return _read_capabilities(modbus)
    finally:
        try:
            modbus.disconnect()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass


def _read_capabilities(modbus: PySolarmanV5) -> DeviceCapabilities:
    """Read rated power (0x0010-0x0011) and the counts packed in 0x0012."""
    try:
        regs = modbus.read_holding_registers(register_addr=0x0010, quantity=3)
        low, high, counts = regs[0], regs[1], regs[2]
        # 32-bit value, low word first, in 0.1 W steps
        rated_power = (((high << 16) | low) & 0xFFFFFFFF) * 0.1
        # The counts are only meaningful once the register is populated
        mppts = (counts & 0x0F00) >> 8 if counts >= 0x0101 else None
        phases = counts & 0x000F if counts >= 0x0101 else None
        _LOGGER.debug(
            "Device capabilities: %s W, %s MPPTs, %s phases",
            rated_power,
            mppts,
            phases,
        )
        return DeviceCapabilities(
            rated_power=rated_power or None, mppts=mppts, phases=phases
        )
    except Exception as e:
        _LOGGER.debug("Device capability registers unavailable: %s", e)
        return DeviceCapabilities()


class InverterData:
    """
    Sends Modbus RTU over TCP requests to the inverter using PySolarmanV5,
    which handles framing, unit id, and checksum internally.
    """

    def __init__(
        self,
        host: str,
        port: int = 8899,
        serial: str = "1",
        hass=None,
        config_entry=None,
        mod: int = DEFAULT_MOD,
    ):
        self._host = host
        self._port = port
        self._serial = int(serial)
        self._hass = hass
        self._config_entry = config_entry
        self._profile = get_profile(mod)
        self._error_count = 0
        self._max_errors = 5
        # Kept for the diagnostics download: the last registers read, and how
        # each block fared
        self.last_raw: List[Optional[int]] = []
        self.last_blocks: List[Dict[str, Any]] = []
        # The datalogger speaks to one client over one socket: a write must
        # not interleave with the register reads of a poll in progress.
        self._lock = asyncio.Lock()

        try:
            self._modbus = self._create_client()
        except NoSocketAvailableError as e:
            _LOGGER.warning("No socket available when connecting to inverter: %s", e)
            raise

    def _create_client(self) -> PySolarmanV5:
        """Open a connection to the datalogger (blocking)."""
        return PySolarmanV5(
            self._host,
            self._serial,
            port=self._port,
            mb_slave_id=1,
            timeout=DEFAULT_MODBUS_TIMEOUT,
            verbose=False,
            auto_reconnect=True,
            logger=_LOGGER,
        )

    def _reconnect(self) -> None:
        """Replace the client after its socket died (blocking).

        If the datalogger refuses, the dead client stays in place and the
        next call tries again.
        """
        try:
            self._modbus.disconnect()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass
        self._modbus = self._create_client()
        _LOGGER.info("Reconnected to the datalogger")

    def _call(self, fn: Callable[[PySolarmanV5], T]) -> T:
        """Run one library call, reconnecting once if the socket is gone.

        The datalogger drops its local client now and then and refuses new
        connections for a few seconds afterwards. The library reconnects
        once, in its reader thread, at the moment the socket closes, which is
        exactly when the datalogger still says no; from then on every call
        fails with "Connection already closed" until the client is replaced.
        """
        try:
            return fn(self._modbus)
        except NoSocketAvailableError as e:
            _LOGGER.info("Datalogger connection lost (%s), reconnecting", e)
            self._reconnect()
            return fn(self._modbus)

    async def fetch_data(self) -> Dict[str, Any]:
        """Reads the register blocks and returns the parsed dictionary."""
        async with self._lock:
            return await self._read_all()

    async def _read_all(self) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()

        def read_block(addr: int, length: int) -> list[int]:
            regs = self._call(
                lambda m: m.read_holding_registers(register_addr=addr, quantity=length)
            )
            # A short answer would shift every later register in the flat
            # list, quietly turning one metric's value into another's
            if len(regs) != length:
                raise ModbusReadError(
                    f"Block 0x{addr:04X}: asked for {length} registers, "
                    f"got {len(regs)}"
                )
            return regs

        raw: List[Optional[int]] = []
        blocks: List[Dict[str, Any]] = []

        try:
            for start, end in CORE_REGISTER_BLOCKS:
                length = end - start + 1
                regs = await loop.run_in_executor(None, read_block, start, length)
                _LOGGER.debug("Regs block 0x%04X (%d): %s", start, length, regs)
                raw.extend(regs)
                blocks.append(_block_report(start, end, regs))
                await asyncio.sleep(0.1)
            self._error_count = 0  # Reset on success
        except Exception as e:
            _LOGGER.error("Error reading registers: %s", e)
            self._error_count += 1
            if self._error_count >= self._max_errors:
                _LOGGER.error(
                    "Max consecutive read errors reached (%d). Reloading integration.",
                    self._max_errors,
                )
                await self._trigger_reload()
            raise ModbusReadError(str(e)) from e

        # Optional blocks (device info, work mode): some devices do not
        # expose them, so a failure only skips their metrics for this cycle.
        for start, end in OPTIONAL_REGISTER_BLOCKS:
            length = end - start + 1
            try:
                regs = await loop.run_in_executor(None, read_block, start, length)
                _LOGGER.debug("Regs block 0x%04X (%d): %s", start, length, regs)
                raw.extend(regs)
                blocks.append(_block_report(start, end, regs))
            except Exception as e:
                _LOGGER.debug(
                    "Optional register block 0x%04X unavailable: %s", start, e
                )
                raw.extend([None] * length)
                blocks.append(_block_report(start, end, None, error=str(e)))
            await asyncio.sleep(0.1)

        _LOGGER.debug("RAW registers (total %d): %s", len(raw), raw)

        self.last_raw = raw
        self.last_blocks = blocks

        return parse_raw(raw, self._profile)

    async def write_registers(self, addr: int, values: Sequence[int]) -> List[int]:
        """Write consecutive holding registers and verify them by reading back.

        Returns what the inverter holds afterwards. Raises ModbusWriteError
        if the inverter refuses the write or ignores it, so a caller never
        believes a setting changed when it did not. A value the inverter
        adjusts (rounds or clamps) counts as written.
        """
        values = [int(v) for v in values]
        if not values:
            raise ModbusWriteError("Nothing to write")
        for value in values:
            if not 0 <= value <= 0xFFFF:
                raise ModbusWriteError(
                    f"Register 0x{addr:04X}: {value} is not a 16-bit value"
                )
        loop = asyncio.get_running_loop()
        async with self._lock:
            return await loop.run_in_executor(
                None, self._write_and_verify, addr, values, None
            )

    async def update_register(self, addr: int, mask: int, value: int) -> int:
        """Change only the bits under ``mask`` of one register.

        Reads the register, replaces the masked bits with those of ``value``,
        and writes the result back, all under the one lock so no poll runs in
        between. Returns the value written. Used for registers that pack
        several settings into one word, such as the time-of-use enable.
        """
        loop = asyncio.get_running_loop()
        async with self._lock:
            current = await loop.run_in_executor(None, self._read_one, addr)
            new = (current & ~mask & 0xFFFF) | (value & mask)
            if new != current:
                stored = await loop.run_in_executor(
                    None, self._write_and_verify, addr, [new], [current]
                )
                return stored[0]
            return new

    def _read_some(self, addr: int, quantity: int, what: str) -> List[int]:
        """Read a few holding registers for a write (blocking)."""
        try:
            regs = list(
                self._call(
                    lambda m: m.read_holding_registers(
                        register_addr=addr, quantity=quantity
                    )
                )
            )
        except Exception as e:
            raise ModbusWriteError(f"Register 0x{addr:04X}: {what} failed: {e}") from e
        if len(regs) != quantity:
            raise ModbusWriteError(
                f"Register 0x{addr:04X}: asked for {quantity} registers, "
                f"got {len(regs)}"
            )
        return [int(r) for r in regs]

    def _read_one(self, addr: int) -> int:
        """Read a single holding register (blocking)."""
        return self._read_some(addr, 1, "read")[0]

    def _write_and_verify(
        self, addr: int, values: List[int], before: Optional[List[int]]
    ) -> List[int]:
        """Write registers and read them back (blocking).

        Always uses Modbus function 16 (write multiple registers), even for a
        single one: Deye inverters refuse function 6 (write single register)
        with an Acknowledge exception and leave the register unchanged.

        The inverter may store something other than what was asked, e.g.
        start times rounded to five minutes, so the read-back is compared
        with the value held before the write: changed means written, even
        if adjusted; unchanged means the inverter ignored it.
        """
        if before is None:
            before = self._read_some(addr, len(values), "read before write")
        try:
            self._call(
                lambda m: m.write_multiple_holding_registers(
                    register_addr=addr, values=values
                )
            )
        except Exception as e:
            raise ModbusWriteError(f"Register 0x{addr:04X}: write failed: {e}") from e
        _LOGGER.debug("Wrote registers 0x%04X: %s", addr, values)

        after = self._read_some(addr, len(values), "read back after write")
        if after == before and after != values:
            # Give the inverter a moment before calling it ignored
            time.sleep(WRITE_SETTLE_SECONDS)
            after = self._read_some(addr, len(values), "read back after write")
        if after == values:
            return after
        if after != before:
            _LOGGER.info(
                "Register 0x%04X: asked for %s, inverter stored %s", addr, values, after
            )
            return after
        raise ModbusWriteError(
            f"Register 0x{addr:04X}: inverter kept {before}, ignoring {values}"
        )

    async def _trigger_reload(self):
        if not self._hass or not self._config_entry:
            _LOGGER.error("Cannot reload: 'hass' or 'config_entry' is missing.")
            return
        # Fire and forget: awaiting the reload here would deadlock, since it
        # tears down the coordinator this fetch is running under.
        self._hass.async_create_task(
            self._hass.config_entries.async_reload(self._config_entry.entry_id)
        )
