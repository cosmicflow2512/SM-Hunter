# SMS Hunter for Unraid

Headless SMS reservation monitor with a dedicated Gluetun tunnel and Pushover
notifications. The hunter refuses to reserve a number unless its public VPN
egress reports country code `TR`.

## Prepare the repository

1. Create a new public repository named `sms-hunter-unraid`.
2. Run `python3 prepare_repository.py your-lowercase-github-name`. This fills
   the image and template URLs automatically.
3. Upload all files, including the hidden `.github` directory, and push to the
   `main` branch.
4. Open the repository's Actions tab and wait for **Build and publish
   container** to complete.
5. Open the newly created `sms-hunter` package and change its visibility to
   **Public** so Unraid can pull it without registry credentials.

## Install the Unraid templates

Install `sms-hunter-gluetun` first, then `sms-hunter`. Either add this repository
under **Docker → Add Container → Template repositories**, or download both raw
XML files to:

```text
/boot/config/plugins/dockerMan/templates-user/
```

The hunter template intentionally uses:

```text
Network: container:sms-hunter-gluetun
```

It therefore cannot start correctly until the dedicated Gluetun container is
running and healthy.

## Secrets

Enter the WireGuard private key, SMS API key, Pushover application token, and
Pushover user key only in Unraid's template fields. Do not commit `.env` files
or secrets to the repository.

## Safety defaults

- Dedicated VPN container and cache path
- VPN country check before reservation
- Maximum price of 5 per reservation
- One reservation per application run
- Read-only filesystem and no Linux capabilities in the hunter
- No exposed ports
- No automatic hunter restart after a regular exit
