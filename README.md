# Event Kitchen Planner

A self-hosted web app that helps a head cook plan food for events, from a small
backpacking group up to 100+ people in a camp or small-industrial kitchen.

Pick meals from a shared recipe repository, set a head count per meal, and print:

1. **Shopping list**: merged across all meals, scaled, rounded up to purchasable pack sizes,
   grouped by store section (checkboxes, CSV).
2. **Timeline**: when to prep, start and add each thing, interleaved across every meal of the
   event and worked backward from serve times, respecting your equipment and number of cooks.
   Conflicts are printed prominently. There is a per-day view and a per-station view.
3. **Recipe sheets**: each recipe scaled to its head count, with batch splits spelled out
   ("Make 3 batches of ~40 servings").

It is a planning tool: print everything before the event. There is no on-site mode.

Your data is never locked in. Recipes, ingredients, kitchens and events export to plain
YAML/JSON and import back (`planner export`, `planner import`, or the *Import / export* page).

---

## Quick start

```bash
docker run -d --name kitchen-planner -p 8080:8080 -v planner-data:/data \
  ghcr.io/<owner>/<repo>:latest
```

Open <http://localhost:8080>, click **Load demo data** on the dashboard (13 recipes, 3 kitchens,
a 120-person weekend), open the *Fall Camp Weekend* event and press **Generate plan**.

`<owner>/<repo>` is this repository, lower-case (for example `ghcr.io/alice/cooking-planner`).
See [GHCR access](#ghcr-access-public-package-or-pull-with-a-token) if the package is private.

### docker-compose

```yaml
services:
  planner:
    image: ghcr.io/<owner>/<repo>:latest   # or pin a tag such as :v0.1.0
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      PLANNER_DATA_DIR: /data
      PLANNER_PAGE_SIZE: Letter            # or A4
      # PLANNER_PASSWORD: change-me         # optional shared password
    volumes:
      - planner-data:/data
    user: "568:568"
volumes:
  planner-data:
```

A ready-to-edit copy is in [`docker-compose.yml`](docker-compose.yml).

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PLANNER_DATA_DIR` | `/data` | Where **all** state lives: the SQLite database, exports, caches. |
| `PLANNER_PASSWORD` | unset | If set, the whole app needs this one shared password (no user accounts). `/healthz` stays open. Use it on a private network. |
| `PLANNER_PAGE_SIZE` | `Letter` | Default print/PDF page size, `Letter` or `A4`. Every plan page also has a Letter/A4 switch. |
| `PORT` | `8080` | Port the app listens on. |
| `PLANNER_BASE_URL` | unset | Optional public URL, reserved for links when the app sits behind a reverse proxy. |

The container runs as a non-root user (uid/gid **568**, the default `apps` user on TrueNAS SCALE),
declares `/data` as a `VOLUME`, applies database migrations automatically at start-up, and has a
`HEALTHCHECK` on `/healthz`. It writes nowhere except `/data`.

---

## TrueNAS SCALE

These steps use the Docker-based Apps screen of recent SCALE releases. Menu names move around
a little between releases; the ideas stay the same.

1. **Create a dataset for the app data.** *Datasets -> Add Dataset*, for example
   `tank/apps/kitchen-planner`. If your release offers a dataset preset for apps, choose it.
2. **Let the container user write to it.** The image runs as `apps` (uid/gid 568). Open the
   dataset's *Permissions -> Edit* and either make `apps`/`apps` the owner, or add an ACL entry
   giving the `apps` user (or group) *Modify*/full control, then tick *Apply permissions
   recursively*. If this is wrong the app stops at start-up with
   *"Cannot write to the data folder /data ... check the dataset's ACL"* in its log.
3. **Install the app.** *Apps -> Discover Apps -> Custom App* (or *Install via YAML*):
   * **Image repository:** `ghcr.io/<owner>/<repo>` (lower-case), **Tag:** `latest` or a version
     such as `v0.1.0`.
   * **Port:** container port `8080` -> a node port of your choice (for example `30080`).
   * **Storage:** *Host Path*, host path = your dataset (`/mnt/tank/apps/kitchen-planner`),
     mount path = `/data`.
   * **User and group:** `568` / `568`.
   * **Environment (optional):** `PLANNER_PASSWORD`, `PLANNER_PAGE_SIZE`.
4. Open `http://<truenas-ip>:30080`. The first start creates and migrates the database in the
   dataset.

**Updating.** Your data is in the dataset, so updating never touches it. Edit the app and change
the tag (or, with `latest`, save the app again so the newer image is pulled), then let it redeploy.
Pinning a version tag is the safer habit; you decide when to move.

**Backing up.**
* Snapshot the dataset (*Data Protection -> Periodic Snapshot Tasks*). SQLite runs in WAL mode so a
  snapshot is always consistent after a crash-recovery.
* For a portable copy, export to plain files: open the app's shell (*Apps -> your app -> Shell*)
  and run `planner export /data/exports`, or use the app's **Import / export** page and
  download the YAML. Restore with `planner import /data/exports --replace`.

### GHCR access (public package, or pull with a token)

The Docker workflow publishes `ghcr.io/<owner>/<repo>` on pushes to `main` and on `v*` tags.

* **Easiest: make the package public.** On GitHub open your profile (or organisation) ->
  *Packages* -> the package -> *Package settings* -> *Change visibility* -> *Public*. Anyone,
  including TrueNAS, can then pull without logging in.
* **Keep it private and pull with a token.** Create a personal access token (classic) with the
  `read:packages` scope. On the TrueNAS shell run
  `docker login ghcr.io -u <github-username>` and paste the token as the password (some SCALE
  releases also have a registry-credentials field in the Apps settings). Then install or update the
  app as above.
* A package published from a private repository starts out private. If a pull says
  "unauthorized" or "not found", it is almost always visibility or a missing token, or an
  upper-case letter in the image name (GHCR names are lower-case).

---

## Using it

* **Ingredients** are the shared catalog. Each has a store section, optional density (g/ml, needed
  to merge cups and pounds), optional trim yield (for example 0.8 for onions) and purchase pack
  sizes (`#10 can = 3000 g`, `50 lb bag`, `1 gal jug`).
* **Recipes** carry tags (`backpacking`, `bulk`, `one-pot`, `no-cook`, ...), a base serving count, ingredients
  (`linear`, `fixed` or `stepped` scaling) and steps. A step has a duration and hands-on time, how the time
  scales with size, dependencies, equipment (`burner, pot@40`), make-ahead windows and optional food-safety
  holds. Steps that use sized equipment are copied once per batch.
* **Kitchen profiles** list the equipment (with capacities), the number of cooks and working hours. Presets:
  *Backpacking (1 stove, 1 pot)*, *Camp kitchen (2 ovens, 6 burners, large pots)* and *Home kitchen*.
* **Events** pick a kitchen, days and meals (recipes, head count, portion factor, diet splits) and a pantry.
  The builder validates live, for example when a recipe is tagged `backpacking-only` but the kitchen is a camp kitchen.
* **Generate plan** has a tab per output, each with a print view (Letter or A4), a PDF download and a CSV where it makes sense.

Things to know about the numbers (details in [`docs/SPEC.md`](docs/SPEC.md) and [`docs/SCHEDULER.md`](docs/SCHEDULER.md)):

* Amounts are exact fractions; nothing is a float, so `1/3 cup x 37` does not drift.
* Volume and weight are only merged through an ingredient's density. With no density the amounts stay
  on separate lines and a warning is shown. Nothing is guessed.
* The scheduler is greedy and deterministic. If the kitchen cannot do what the plan asks, you still get a
  schedule, with the conflicts printed at the top of the timeline.
* Food-safety hints (hot at or above 135 F, cold at or below 41 F, 4 hours out of temperature) are
  informational warnings, not guarantees.

## Command line

```bash
planner seed                              # load the bundled demo data
planner export ./backup [--format json]   # one YAML/JSON file per kind
planner import ./backup [--replace]       # file or folder; checked fully before anything is written
planner plan event.yaml --out ./out --pdf # all outputs for an event file (add --data to use files, not the DB)
planner serve --port 8080                 # run the web app
```

## Adding an output

An output is one module in `src/planner/generators/` plus a template; no route or menu edits.
See [`docs/ADDING_A_GENERATOR.md`](docs/ADDING_A_GENERATOR.md). Stubs for cost, allergens,
equipment and pack weight are in `generators/_stubs/`.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check src tests && ruff format --check src tests
mypy src                 # strict on planner.core
pytest                   # core coverage gate is 90%
planner serve
docker build -t planner:dev . && scripts/smoke-test.sh planner:dev
```

WeasyPrint needs Pango at run time (`libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b`); the Docker
image includes it. The layout is described in [`docs/SPEC.md`](docs/SPEC.md); decisions are in
[`docs/DECISIONS.md`](docs/DECISIONS.md) and history is in [`CHANGELOG.md`](CHANGELOG.md).

CI (`.github/workflows/ci.yml`) runs ruff, mypy, pytest and a Docker build with a smoke test on every
push and pull request. `docker.yml` publishes to GHCR from `main` and from `v*` tags only when CI is green.
Tags: `latest` (main), the short commit SHA, and semver (`1.2.3`, `1.2`) for version tags.
Release tags also build `linux/arm64`; `main` builds `linux/amd64` to keep CI fast.
