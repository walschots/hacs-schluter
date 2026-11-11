# Schluter DITRA-HEAT-E-WiFi (self-healing) for Home Assistant

A drop-in replacement for the built-in `schluter` integration that fixes thermostats getting stuck as **unavailable** after the cloud session expires.

The built-in integration signs in once at startup. When Schluter later invalidates that session, every poll fails with `401 Unauthorized ... /api/thermostats?sessionId=...` until Home Assistant restarts. This version signs in again on its own whenever it gets a 401, then retries the request.

## What's different from the built-in integration

- **Self-healing session.** On a 401 it signs in again and retries once. Parallel calls share a single re-login.
- **Account-safe login backoff.** At most one login every 5 minutes, stretching to 15, 30 and 60 minutes after consecutive failures. The limit is shared per account and saved to disk, so Home Assistant's setup retries, reloads and restarts can't bypass it. If Schluter rejects brand-new sessions 4 times in a row (an outage or a locked account), the integration stops logging in and shows a re-authenticate prompt instead.
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

If the log shows *"Schluter rejected a brand-new session"*, the cloud is refusing fresh logins, usually an outage or a temporary account lock. The integration backs off on its own (*"next login attempt in N min"*). If you can't sign in to the Schluter app either, disable the integration until the app works again, then re-enable it.

If you get a re-authenticate prompt, first check that the Schluter app accepts your password, then enter it in Home Assistant. A successful re-authentication clears the backoff.
