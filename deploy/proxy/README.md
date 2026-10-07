# The proxy route (technical design section 1.1)

Files for `~/env/assets/proxy_server`, ready to apply; nothing here is applied automatically.

1. `route-slides.conf` -> `proxy_server/conf/route-slides.conf` (included by nginx.conf's `route-*.conf`).
2. `auth-slides.conf.snippet` -> append to `proxy_server/conf/route-entra.conf`.
3. `proxy_server/conf/secrets/slides.conf` (git-ignored), one line, the value of `SLIDES_PROXY_SECRET` in this repo's `.env`:
   `proxy_set_header X-Slides-Proxy-Secret "<the secret>";`
4. Check and reload: `docker exec proxy_server nginx -t -c /etc/nginx/conf-host/nginx.conf` then
   `docker exec proxy_server nginx -s reload -c /etc/nginx/conf-host/nginx.conf`.
5. Sign-out returns to `https://logus2k.com/slides/`: that address must be a redirect URI of the Entra app registration
   (as `https://logus2k.com/cortex/` is), or Microsoft shows its own signed-out page.

Applied on 2026-10-06 (approved by the project owner); the allow-list is any bancoctt.pt account. Step 5 is pending.
