# Home scanner (Docker)

Farmers and Kmart turn away requests from cloud and hosting servers, so this
small container scans them from your home connection and sends the results to
the website and Discord, just like the other scanners.

It reads only public pages that each shop's robots.txt allows, names itself in
every request ("PokeDropNZ/1.0 … personal stock alerts") and waits a few
seconds between pages. Farmers is checked every 20 minutes and Kmart every 30.

## Set up in Dockge (TrueNAS)

1. In Dockge, choose **+ Compose** and name the stack `pokedrop`.
2. Paste in the contents of `docker-compose.yml` from this folder.
3. In the **.env** box, add the lines from `.env.example` with the same values
   the cPanel server uses (Discord webhook, WordPress address and secret).
4. Choose **Deploy**, then open the stack's log. Within a few minutes you
   should see lines like `farmers: 13 products parsed from HTML` and
   `kmart: 46 products listed`.

## Set up with plain Docker

Put `docker-compose.yml` and a filled-in `.env` (copied from `.env.example`)
in a folder on the server, then run `docker compose up -d` and
`docker logs -f pokedrop-home`.

There's nothing to build. A standard Python image downloads the scanner from
GitHub when it starts and updates it about once an hour, so changes reach it
without touching the server. (`Dockerfile` and `entrypoint.sh` are an older way
of doing the same thing and aren't needed.)

## If a shop blocks it

If a scan logs `no products found` or an error such as `403`, that shop isn't
letting this scanner in from your connection either. Switch that shop off by
setting `enabled: false` in `stores-home.yaml` on GitHub (the container picks
the change up within the hour) rather than trying to get round the block.

## Stop or remove

`docker compose down` stops it. Delete the folder to remove it completely.
