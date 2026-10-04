# pyngbsicon

Asynchronous Python client for **NGBS iCON** heating/cooling controllers, using the
controller's local JSON-over-TCP service protocol (TCP port 7992). No cloud, no
runtime dependencies, Python 3.12+.

This is the protocol library behind the
[NGBS iCON Home Assistant integration](https://github.com/robroy1979/ha-ngbs-icon).
The protocol is documented in
[docs/protocol.md](https://github.com/robroy1979/ha-ngbs-icon/blob/main/docs/protocol.md).

```python
import asyncio

from pyngbsicon import IconClient


async def main() -> None:
    # The SYSID is discovered automatically (firmware 1079 and later).
    client = IconClient("192.0.2.10")
    state = await client.get_state()
    for room in state.configured_thermostats.values():
        print(room.name, room.temperature, room.active_setpoint)

    # Returns once the thermostat has adopted the value (about two seconds).
    state = await client.set_setpoints("1.1", heat=22.5)


asyncio.run(main())
```

Writes are confirmed: the thermostat, not the controller, has the final word on a
setpoint. It rounds to 0.5 °C and clamps the value to its allowed range (the clamped
value is returned); a value it discards raises `IconRejectedError`.

Command line:

```
pyngbsicon scan                           # find controllers on the local network
pyngbsicon status 192.0.2.10              # complete state (--json for JSON)
pyngbsicon set 192.0.2.10 1.1 --heat 22.5 # setpoints
pyngbsicon eco 192.0.2.10 on              # system ECO (--thermostat 1.1 for one room)
pyngbsicon lock 192.0.2.10 1.1 on         # child lock
pyngbsicon raw 192.0.2.10 '{"RELOAD": ""}'
```

Licensed under the Business Source License 1.1 — free for end users; see LICENSE.
