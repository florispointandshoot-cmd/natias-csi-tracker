# NATIA'S CSI TRACKER

Publieke pagina: stad (Brussel/Antwerpen) + uren. Geen naam, geen klant.

Live: https://natias-csi-tracker.netlify.app/

## Automatische update (GitHub → Netlify)

Elke dag leest GitHub Actions je Google Calendar en pusht een nieuw rooster. Netlify publiceert dat opnieuw.

### Eenmalig

1. Maak op GitHub een **nieuwe repo** (mag private), alleen met de inhoud van deze map.
2. Secret **`GOOGLE_TOKEN_JSON`**: plak de volledige inhoud van `token.json` (uit de factuurmap).  
   Repo → Settings → Secrets and variables → Actions → New repository secret.
3. Actions aanzetten. Test: Actions → **Rooster bijwerken** → Run workflow.
4. In Netlify: site **natias-csi-tracker** → Project configuration → **Build & deploy** / **Link repository**  
   (of: Add new site → Import from Git → deze repo).  
   Publish directory: `.` (root). Geen build command nodig.
5. Domein laten staan op `natias-csi-tracker.netlify.app`.

### Lokaal (optioneel)

```bash
# vanuit FACTUURSTURENBE, met bestaande token.json
.venv/bin/python waar-ik-werk/publish_status.py
```

## Wachtwoord

Client-side gate. Vraagt opnieuw bij elke refresh.
