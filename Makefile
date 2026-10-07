# make dev | check | ui
# dev    the app on http://localhost:2720 in its container (proxy headers: see tests/ui/lib.mjs)
# check  lint, then the backend tests in the test image (where LibreOffice Impress renders, with the templates' fonts
#        from fonts/: licensed, mounted, never in the image; see docs/licenses.md)
# ui     browser screenshots and checks at every width and theme, and M1 end to end (the app must be running; look at tests/ui/out/)
# a11y   the accessibility audit (axe-core, WCAG 2.2 AA; keyboard) at desktop, tablet and phone in both themes, against
#        the e2e app, started fresh as e2e does: tests/ui/out/a11y-<width>-<theme>.json
# e2e    the assistant (M3), the knowledge base (M4), voice (M5, from a recording), the project's memory (M6), edits by hand and hands-free voice (M7) end to end in the browser, against the real app with the scripted model (tests/e2e/fake_app.py),
#        started fresh from the test image so the code under test is the code on disk; desktop light and dark, Portuguese,
#        tablet. Then tests/ui/out/i18n-misses.json lists interface text the Portuguese dictionary lacks.
# eval   search recall (SP-7, tests/eval/recall.json, the real reranker), then the editing evaluation (SP-5) against the
#        real configured model: tests/eval/requests.json, every request alone;
#        prints targeting accuracy and writes tests/eval/out/ (every request's calls, reply and changes). Not CI.
.PHONY: dev check ui e2e a11y eval

dev:
	docker compose build && docker compose up -d slides

check:
	.venv/bin/ruff check backend
	docker build -q --build-arg BASE_IMAGE=slides-base:lo-2 --target test -t slides-test . >/dev/null
	docker run --rm -v $$PWD/fonts:/usr/share/fonts/slides:ro slides-test

ui:
	cd tests/ui && node shots.mjs && node m1.mjs 1440 light && node m1.mjs 1440 dark && node m1.mjs 834 light

e2e:
	docker build -q --build-arg BASE_IMAGE=slides-base:lo-2 --target test -t slides-test . >/dev/null
	-docker rm -f slides-e2e >/dev/null 2>&1
	docker run -d --name slides-e2e -p 2722:2722 -u $$(id -u):$$(id -g) -e HOME=/tmp -v $$PWD:/src -w /src -v $$PWD/fonts:/usr/share/fonts/slides:ro \
	  -e FAKE_SCRIPT=/src/tests/e2e/out/script.json slides-test python tests/e2e/fake_app.py >/dev/null
	for i in $$(seq 60); do curl -sf -o /dev/null http://localhost:2722/ -H 'X-Slides-Proxy-Secret: e2e-secret' \
	  -H 'X-Auth-Request-Email: probe@example.com' && break; sleep 1; done
	cd tests/ui && export SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret && rm -f out/i18n-misses.json \
	  && node vad.test.mjs && node security.mjs \
	  && node m3.mjs 1440 light && node m3.mjs 1440 dark && node m3.mjs 1440 light pt && node m3.mjs 834 light \
	  && node m4.mjs 1440 light && node m4.mjs 1440 dark && node m4.mjs 1440 light pt && node m4.mjs 834 light \
	  && node m5.mjs 1440 light pt && node m5.mjs 1440 dark en && node m5.mjs 834 light pt \
	  && node m6.mjs 1440 light en && node m6.mjs 1440 dark pt && node m6.mjs 834 light pt \
	  && node m7.mjs 1440 light en && node m7.mjs 1440 dark pt && node m7.mjs 834 light pt \
	  && node m7v.mjs 1440 light pt && node m7v.mjs 1440 dark en && node m7v.mjs 834 light pt; \
	  status=$$?; docker rm -f slides-e2e >/dev/null; exit $$status

a11y:
	docker build -q --build-arg BASE_IMAGE=slides-base:lo-2 --target test -t slides-test . >/dev/null
	-docker rm -f slides-e2e >/dev/null 2>&1
	docker run -d --name slides-e2e -p 2722:2722 -u $$(id -u):$$(id -g) -e HOME=/tmp -v $$PWD:/src -w /src -v $$PWD/fonts:/usr/share/fonts/slides:ro \
	  -e FAKE_SCRIPT=/src/tests/e2e/out/script.json slides-test python tests/e2e/fake_app.py >/dev/null
	for i in $$(seq 60); do curl -sf -o /dev/null http://localhost:2722/ -H 'X-Slides-Proxy-Secret: e2e-secret' \
	  -H 'X-Auth-Request-Email: probe@example.com' && break; sleep 1; done
	cd tests/ui && export SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret \
	  && node a11y.mjs 1440 light && node a11y.mjs 1440 dark && node a11y.mjs 834 light && node a11y.mjs 834 dark \
	  && node a11y.mjs 390 light && node a11y.mjs 390 dark; \
	  status=$$?; docker rm -f slides-e2e >/dev/null; exit $$status

eval:
	docker build -q --build-arg BASE_IMAGE=slides-base:lo-2 --target test -t slides-test . >/dev/null
	# on both networks, as the app: agent_server and Cortex (logus2k_network), the reranker (cortex-kb)
	-docker rm -f slides-eval >/dev/null 2>&1
	docker create --name slides-eval --network logus2k_network -u $$(id -u):$$(id -g) -e HOME=/tmp -v $$PWD:/src -w /src -v $$PWD/fonts:/usr/share/fonts/slides:ro \
	  --env-file .env slides-test sh -c 'python tests/eval/recall.py && python tests/eval/run.py' >/dev/null
	docker network connect cortex-kb slides-eval
	docker start -a slides-eval; status=$$?; docker rm -f slides-eval >/dev/null; exit $$status
