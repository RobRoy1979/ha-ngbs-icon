# Security policy

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting
("Security" tab → "Report a vulnerability") on
https://github.com/robroy1979/ha-ngbs-icon.

## What the integration stores

* The controller's address and **SYSID** are stored in Home Assistant's config entry
  storage, like the credentials of any other integration. The SYSID is also the
  default password of the controller's web interface, so it is shortened to its last
  four digits in logs and removed from diagnostics downloads.
* The integration only talks to the controller on your local network; it makes no
  connections to the internet and collects no telemetry.

## Your controller

The iCON controller runs an old embedded operating system and web server. Keep it
on your local network: do not forward its ports (80, 502, 7992) to the internet, and
change the web interface password from the default if you use the web interface.
