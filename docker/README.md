# Home scanner (Docker)

Farmers and Kmart turn away requests from cloud and hosting servers, so this
small container scans them from your home connection and sends the results to
the website and Discord, just like the other scanners.

It reads only public pages that each shop's robots.txt allows, names itself in
every request ("PokeDropNZ/1.0 … personal stock alerts") and waits a few
seconds between pages. Farmers is checked every 20 minutes and Kmart every 30.

## Set up

1. On your Docker server, get this folder:
   `git clone https://github.com/kreyastus/pokemon-drop-alerts-nz.git`
   then `cd pokemon-drop-alerts-nz/docker`.
2. Copy `.env.example` to `.env` (`cp .env.example .env`) and fill in the
   same values the cPanel server uses (Discord webhook, WordPress address and
   secret).
3. Run `docker compose up -d --build`.
4. Check it's working: `docker logs -f pokedrop-home`. Within a few minutes
   you should see lines like `farmers: 13 products parsed from HTML` and
   `kmart: 46 products listed`.

The container fetches the scanner code from GitHub when it starts and updates
it about once an hour, so changes reach it without a rebuild.

## If a shop blocks it

If a scan logs `no products found` or an error such as `403`, that shop isn't
letting this scanner in from your connection either. Switch that shop off by
setting `enabled: false` in `stores-home.yaml` on GitHub (the container picks
the change up within the hour) rather than trying to get round the block.

## Stop or remove

`docker compose down` stops it. Delete the folder to remove it completely.
