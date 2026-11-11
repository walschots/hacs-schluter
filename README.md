# Schluter DITRA-HEAT-E-WiFi (self-healing) for Home Assistant

A drop-in replacement for the built-in `schluter` integration that fixes thermostats getting stuck as **unavailable** after the cloud session expires.

The built-in integration signs in once at startup. When Schluter later invalidates that session, every poll fails with `401 Unauthorized ... /api/thermostats?sessionId=...` until Home Assistant restarts. This version signs in again on its own whenever it gets a 401, then retries the request.

## What's different from the built-in integration

- **Self-healing session.** On a 401 it signs in again and retries once. Parallel calls share a single re-login. Logins are throttled to at most one every 5 minutes, so the account isn't hammered if Schluter keeps rejecting sessions.
- **UI setup.** You set it up through a config flow, and the old `schluter:` YAML block is imported automatically. A real password change triggers a re-authentication prompt in the UI instead of failing silently.
- **Same entities.** Thermostats keep the serial number as their unique ID, so your existing entity IDs, names and areas stay as they are.
- **Extras.** A *Schedule* / *Manual* preset, `hvac_action` (heating or idle), and a *Heating power* sensor (W) for the Energy dashboard.
- **No dependencies.** It needs no external Python packages, only the aiohttp client that Home Assistant already ships.

## Install (HACS)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/walschots/hacs-schluter` with type **Integration**.
2. Install **Schluter DITRA-HEAT-E-WiFi (self-healing)**, then restart Home Assistant.
3. Your existing `schluter:` YAML is imported on that first restart. Check Settings → Devices & services → **Schluter**.
4. Delete the `schluter:` block from `configuration.yaml` and restart once more.

No YAML yet? Go to Settings → Devices & services → **Add integration** → *Schluter* and use your Schluter app email and password.

Because this overrides the core `schluter` domain, Home Assistant logs a "custom integration overrides core" warning. That's expected.

## Troubleshooting

To see each login and the reason for every failure, add this:

```yaml
logger:
  logs:
    custom_components.schluter: debug
```

If the log shows *"Schluter rejected a session that was created less than 5 minutes ago"*, the cloud is rejecting brand-new sessions. That's a problem on Schluter's side (an account or API change), not an expired session.
