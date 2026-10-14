/**
 * Railway deployment for the coursefind data API.
 *
 * WHY .railway/railway.ts AND NOT railway.json
 * --------------------------------------------
 * Railway's Config as Code (railway.json / railway.toml) is deprecated:
 * existing files keep working until 2026-12-01 and NEW SERVICES CANNOT
 * USE IT AT ALL. Infrastructure as Code, this file, is the supported
 * path, so a railway.json written today would simply be ignored.
 *
 * WHAT THIS DEPLOYS, AND WHAT IT DELIBERATELY DOES NOT
 * ----------------------------------------------------
 * It runs the IMAGE CI ALREADY BUILT AND TESTED, pulled from GHCR, and
 * does not build from this repo. The image only exists after
 * `uv sync --locked`, a --verified-only export, schema validation and
 * the full test suite have passed (.github/workflows/build-data-image.yml).
 * Letting Railway build from the Dockerfile would skip every one of
 * those gates and could serve data no test ever saw.
 *
 * THE TAG IS PINNED, AND AUTO-UPDATES ARE OFF
 * -------------------------------------------
 * api/Dockerfile bakes programmes.json in at build time and says why:
 * "new data means a new image tag, not a live reload". Railway can
 * follow a tag automatically; that is turned off on purpose, because it
 * would change what learners are served the moment anyone pushes a
 * release, which is the opposite of the discipline the rest of this
 * pipeline is built on.
 *
 * To ship new data: change the tag below, commit, apply. That commit is
 * the record of when it went live, and a rollback is changing it back.
 *
 * THE PORT
 * --------
 * The image's CMD listens on 8000 and takes no argument for it. PORT is
 * declared rather than overriding the command to interpolate Railway's
 * own value, so the container runs the exact command it runs locally
 * and under the Docker smoke test -- no deploy-only invocation to get
 * wrong.
 */
import { defineRailway, image, project, service } from "railway/iac"

export default defineRailway(() => {
  const api = service("coursefind-api", {
    source: image("ghcr.io/itumeleng-itu/coursefind-api:2027.1", {
      autoUpdates: { type: "disabled" },
    }),

    // /healthz is served by api/src/app/main.py. Railway holds a new
    // deploy back until it answers, so a broken image never replaces a
    // working one.
    healthcheck: "/healthz",

    env: {
      PORT: "8000",
    },

    // Amsterdam: the closest region Railway offers to South Africa, and
    // this service is one request per search, so the ~150-200ms is paid
    // once rather than per course. One replica -- the API is read-only
    // and serves from memory.
    replicas: { "europe-west4-drams3a": 1 },
  })

  return project("coursefind", { resources: [api] })
})
