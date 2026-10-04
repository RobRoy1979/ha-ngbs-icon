# pyngbsicon

Asynchronous Python client for **NGBS iCON** heating/cooling controllers, using the
controller's local JSON-over-TCP service protocol (TCP port 7992). No cloud, no
runtime dependencies.

This is the protocol library behind the
[NGBS iCON Home Assistant integration](https://github.com/robroy1979/ha-ngbs-icon).
The protocol itself is documented in
[docs/protocol.md](https://github.com/robroy1979/ha-ngbs-icon/blob/main/docs/protocol.md).

```python
import asyncio
from pyngbsicon import IconClient


async def main() -> None:
    # The SYSID is discovered automatically (firmware >= 1079).
    client = IconClient("192.0.2.10")
    state = await client.get_state()
    for thermostat in state.thermostats.values():
        print(thermostat.name, thermostat.temperature, thermostat.active_setpoint)
    await client.set_setpoint("1.1", "heat", 22.5)


asyncio.run(main())
```

Command line:

```
pyngbsicon scan                      # find controllers on the local network
pyngbsicon status 192.0.2.10         # full state
pyngbsicon set 192.0.2.10 1.1 --heat 22.5
```

See the repository for the license.
