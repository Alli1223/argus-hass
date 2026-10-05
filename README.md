# Argus for Home Assistant

A custom integration that brings an [Argus](https://github.com/Alli1223/Argus) server's systems into
Home Assistant, so you can put them on dashboards and build automations and alerts on them.

Each host in Argus becomes a device:

| Entity | What it shows |
| --- | --- |
| Online | Whether the host's agent is reporting (connectivity). |
| Problem | On while any Argus alert is firing for the host; `severity` says the worst. |
| CPU usage, Memory usage, Fullest disk | Percentages from the latest reading. |
| Load (1 min), Network in, Network out | Load average, and traffic in Mbit/s. |
| Highest temperature | The hottest sensor right now; `sensors` lists every reading. |
| Firing alerts | How many Argus alerts are firing for the host, with their titles. |
| Container *name* | One per Docker container: on while it runs, with its state, health and restarts. |
| Last boot, Agent update | Diagnostics. |
| Swap usage, one sensor per temperature sensor | Off by default; turn them on in the entity settings. |

An **Argus** device for the server has **Firing alerts** (with counts per severity) and **Hosts
online** (with the names of any offline).

When an Argus alert starts or stops firing, Home Assistant gets an `argus_alert_fired` or
`argus_alert_resolved` event with `alert_id`, `host_id`, `host_name`, `title`, `severity`, `metric`,
`value`, `threshold` and `fired_at`.

## Requirements

- Argus 0.9.0 or later, which adds API tokens.
- Home Assistant 2025.3 or later.

## Install

With [HACS](https://hacs.xyz): **HACS → ⋮ → Custom repositories**, add
`https://github.com/Alli1223/argus-hass` as an **Integration**, then install **Argus** and restart
Home Assistant.

By hand: copy `custom_components/argus` into your Home Assistant `config/custom_components/` folder
and restart.

## Set up

1. In Argus, open **Account** and create an **API token** named, say, *Home Assistant*. Copy it; it
   starts with `argus_at_` and is shown once.
2. In Home Assistant, **Settings → Devices & services → Add integration → Argus**.
3. Enter the address you open Argus at and the token.

API tokens only read, so Home Assistant cannot change anything in Argus. The integration sees the hosts
the token's owner sees: all of them for an administrator. If the token is revoked, Home Assistant asks
for a new one.

Argus is read every 30 seconds; change it under the integration's **Configure**.

## Examples

Notify when a host stops reporting:

```yaml
automation:
  - alias: Server offline
    triggers:
      - trigger: state
        entity_id: binary_sensor.nas_online
        to: "off"
        for: "00:02:00"
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "{{ state_attr('binary_sensor.nas_online', 'friendly_name') }} stopped reporting to Argus."
```

Pass Argus's own alerts on, whatever host they are for:

```yaml
automation:
  - alias: Argus alert
    triggers:
      - trigger: event
        event_type: argus_alert_fired
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.severity == 'Critical' }}"
    actions:
      - action: notify.mobile_app_phone
        data:
          title: "Argus: {{ trigger.event.data.host_name }}"
          message: "{{ trigger.event.data.title }}"
```

Or use the sensors directly, such as a numeric state trigger on
`sensor.nas_highest_temperature` above 80.

## Removing hosts

Devices for hosts deleted from Argus stay until you delete them: open the device and choose
**Delete**. Hosts still in Argus can't be deleted here.
