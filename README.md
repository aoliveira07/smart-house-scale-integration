# Smart House Scale — Home Assistant Integration

Native Home Assistant integration for the Smart House Scale project.

It uses Home Assistant's Bluetooth stack (including Bluetooth Proxy), waits for
stabilized Xiaomi scale readings, deduplicates advertisements, and sends
measurements to the central Smart House API using the configured Bearer token.

Install through HACS as a custom integration, then add **Smart House Scale** in
Home Assistant and configure the scale MAC address, API URL, token, and session
window.

The dashboard App is published separately at:
https://github.com/aoliveira07/smart-house-scale

License: MIT.
