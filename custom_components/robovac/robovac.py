import asyncio
from enum import IntEnum

from homeassistant.components.vacuum import VacuumEntityFeature

from .tuyalocalapi import (
    MAGIC_SUFFIX_BYTES,
    ConnectionException,
    ConnectionTimeoutException,
    InvalidMessage,
    Message,
    MessageDecodeFailed,
    TuyaDevice,
)


class RoboVacEntityFeature(IntEnum):
    """Supported features of the RoboVac entity."""

    EDGE = 1
    SMALL_ROOM = 2
    CLEANING_TIME = 4
    CLEANING_AREA = 8
    DO_NOT_DISTURB = 16
    AUTO_RETURN = 32
    CONSUMABLES = 64
    ROOM = 128
    ZONE = 256
    MAP = 512
    BOOST_IQ = 1024


ROBOVAC_SERIES = {
    "C": [
        "T2103",
        "T2117",
        "T2118",
        "T2119",
        "T2120",
        "T2123",
        "T2128",
        "T2130",
        "T2132",
    ],
    "G": [
        "T1250",
        "T2250",
        "T2251",
        "T2252",
        "T2253",
        "T2254",
        "T2150",
        "T2255",
        "T2256",
        "T2257",
        "T2258",
        "T2259",
        "T2270",
        "T2272",
        "T2273",
    ],
    "L": ["T2181", "T2182", "T2190", "T2192", "T2193", "T2194"],
    "X": ["T2261", "T2262", "T2320"],
}

HAS_MAP_FEATURE = ["T2253", *ROBOVAC_SERIES["L"], *ROBOVAC_SERIES["X"]]

HAS_CONSUMABLES = [
    "T1250",
    "T2181",
    "T2182",
    "T2190",
    "T2193",
    "T2194",
    "T2253",
    "T2256",
    "T2258",
    "T2261",
    "T2273",
    "T2320",
]

ROBOVAC_SERIES_FEATURES = {
    "C": RoboVacEntityFeature.EDGE | RoboVacEntityFeature.SMALL_ROOM,
    "G": RoboVacEntityFeature.CLEANING_TIME
    | RoboVacEntityFeature.CLEANING_AREA
    | RoboVacEntityFeature.DO_NOT_DISTURB
    | RoboVacEntityFeature.AUTO_RETURN,
    "L": RoboVacEntityFeature.CLEANING_TIME
    | RoboVacEntityFeature.CLEANING_AREA
    | RoboVacEntityFeature.DO_NOT_DISTURB
    | RoboVacEntityFeature.AUTO_RETURN
    | RoboVacEntityFeature.ROOM
    | RoboVacEntityFeature.ZONE
    | RoboVacEntityFeature.BOOST_IQ,
    "X": RoboVacEntityFeature.CLEANING_TIME
    | RoboVacEntityFeature.CLEANING_AREA
    | RoboVacEntityFeature.DO_NOT_DISTURB
    | RoboVacEntityFeature.AUTO_RETURN
    | RoboVacEntityFeature.ROOM
    | RoboVacEntityFeature.ZONE
    | RoboVacEntityFeature.BOOST_IQ,
}

ROBOVAC_SERIES_FAN_SPEEDS = {
    "C": ["No Suction", "Standard", "Boost IQ", "Max"],
    "G": ["Standard", "Turbo", "Max", "Boost IQ"],
    "L": ["Quiet", "Standard", "Turbo", "Max"],
    "X": ["Pure", "Standard", "Turbo", "Max"],
}


SUPPORTED_ROBOVAC_MODELS = list(
    set([item for sublist in ROBOVAC_SERIES.values() for item in sublist])
)


class ModelNotSupportedException(Exception):
    """This model is not supported"""


class RoboVac(TuyaDevice):
    """Representation of a Eufy RoboVac Tuya device."""

    def __init__(self, model_code, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model_code = model_code

        if self.model_code not in SUPPORTED_ROBOVAC_MODELS:
            raise ModelNotSupportedException(
                "Model {} is not supported".format(self.model_code)
            )

    async def async_connect(self):
        """Connect without blocking Home Assistant's event loop."""
        if self._connected is True or self._enabled is False:
            return

        self._LOGGER.debug("Connecting to {}".format(self))
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as e:
            raise ConnectionTimeoutException("Connection timed out") from e
        except OSError as e:
            raise ConnectionException(
                "Connection to {} failed: {}".format(self, e)
            ) from e

        self._connected = True

        if self._ping_task is None or self._ping_task.done():
            self._ping_task = asyncio.create_task(self.async_ping(self.ping_interval))

        asyncio.create_task(self._async_handle_message())

    async def async_disconnect(self):
        """Close the current socket and make the next operation reconnect."""
        if self._connected is False:
            return

        self._LOGGER.debug("Disconnected from {}".format(self))
        self._connected = False
        self.last_pong = 0

        writer = self.writer
        self.writer = None
        self.reader = None

        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def async_get(self):
        """Get state only after a connection is established."""
        payload = {"gwId": self.gateway_id, "devId": self.device_id}
        encrypt = False if self.version < (3, 3) else True
        message = Message(Message.GET_COMMAND, payload, encrypt=encrypt, device=self)

        # The original implementation queued the request before connecting, then
        # async_recieve() returned immediately because _connected was still False.
        # That race could leave the first poll with no state and the entity
        # unavailable until a later refresh.
        await self.async_connect()
        self._queue.append(message)
        response = await self.async_recieve(message)
        if response is not None:
            await self.async_update_state(response)

    async def _async_handle_message(self):
        """Handle incoming messages and retire dead sockets promptly."""
        if self._enabled is False or self._connected is False:
            return

        try:
            reader = self.reader
            if reader is None:
                await self.async_disconnect()
                return

            self._response_task = asyncio.create_task(
                reader.readuntil(MAGIC_SUFFIX_BYTES)
            )
            await self._response_task
            response_data = self._response_task.result()
            message = Message.from_bytes(self, response_data, self.cipher)
        except InvalidMessage as e:
            self._LOGGER.debug("Invalid message from {}: {}".format(self, e))
        except MessageDecodeFailed:
            self._LOGGER.debug("Failed to decrypt message from {}".format(self))
        except asyncio.IncompleteReadError as e:
            if self._connected:
                self._LOGGER.debug(
                    "Incomplete read from %s (%d bytes partial)",
                    self,
                    len(e.partial),
                )
                await self.async_disconnect()
            self._response_task = None
            return
        except (ConnectionResetError, OSError) as e:
            self._LOGGER.debug("Connection closed by %s: %s", self, e)
            await self.async_disconnect()
            self._response_task = None
            return
        except Exception:
            self._LOGGER.exception("Unexpected receive error from %s", self)
            await self.async_disconnect()
            self._response_task = None
            return
        else:
            self._LOGGER.debug("Received message from {}: {}".format(self, message))
            if message.sequence in self._listeners:
                sem = self._listeners[message.sequence]
                if isinstance(sem, asyncio.Semaphore):
                    self._listeners[message.sequence] = message
                    sem.release()
            else:
                handler = self._handlers.get(message.command, None)
                if handler is not None:
                    asyncio.create_task(handler(message))

        self._response_task = None
        if self._connected:
            asyncio.create_task(self._async_handle_message())

    def getHomeAssistantFeatures(self):
        supportedFeatures = (
            VacuumEntityFeature.CLEAN_SPOT
            | VacuumEntityFeature.FAN_SPEED
            | VacuumEntityFeature.LOCATE
            | VacuumEntityFeature.PAUSE
            | VacuumEntityFeature.RETURN_HOME
            | VacuumEntityFeature.SEND_COMMAND
            | VacuumEntityFeature.START
            | VacuumEntityFeature.STATE
            | VacuumEntityFeature.STOP
        )

        if self.model_code in HAS_MAP_FEATURE:
            supportedFeatures |= VacuumEntityFeature.MAP

        return supportedFeatures

    def getRoboVacFeatures(self):
        supportedFeatures = ROBOVAC_SERIES_FEATURES[self.getRoboVacSeries()]

        if self.model_code in HAS_MAP_FEATURE:
            supportedFeatures |= RoboVacEntityFeature.MAP

        if self.model_code in HAS_CONSUMABLES:
            supportedFeatures |= RoboVacEntityFeature.CONSUMABLES

        return supportedFeatures

    def getRoboVacSeries(self):
        for series, models in ROBOVAC_SERIES.items():
            if self.model_code in models:
                return series

    def getFanSpeeds(self):
        return ROBOVAC_SERIES_FAN_SPEEDS[self.getRoboVacSeries()]
