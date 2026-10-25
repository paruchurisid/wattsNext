# Automatic Vercel deployments

After CI succeeds, the `Watt'sNext CI/CD` workflow deploys automatically:

| Run | Destination |
| --- | --- |
| Push to `main`, or manual run on `main` | Production, after migrations |
| Push of a `v*.*.*` tag | Production, after migrations |
| Push to `backend-section` or `master`, or manual run on another branch | Preview |
| Same-repository pull request | Preview |
| Fork pull request or Dependabot pull request | CI only; deployment credentials are unavailable |

Deployment URLs appear in the Actions job summary and the GitHub environment.
Production runs are serialized, so a new push cannot cancel a running migration
or deployment. Previews never run production migrations.

## One-time GitHub setup

1. Create a Vercel access token at <https://vercel.com/account/tokens> with
   access to the team that owns `watts-next`.
2. Open <https://github.com/paruchurisid/wattsNext/settings/secrets/actions>.
   Add these **repository secrets** using **New repository secret**:

   | Secret | Value |
   | --- | --- |
   | `VERCEL_TOKEN` | The Vercel access token |
   | `DATABASE_URL_UNPOOLED` | The direct production Neon connection string, without `-pooler` in its hostname |

   Keep tokens and database URLs in the secrets UI; do not commit them.
3. Open <https://github.com/paruchurisid/wattsNext/settings/variables/actions>.
   Add these **repository variables**, taken from the existing local
   `.vercel/project.json`:

   | Variable | Value |
   | --- | --- |
   | `VERCEL_ORG_ID` | `team_gose5Pk77paKh6nbV43VMxdr` |
   | `VERCEL_PROJECT_ID` | `prj_0EpFffMUFynWNVIVttbz79728Dgj` |

   Existing secrets with these names also work and take precedence over variables.
4. In Vercel's `watts-next` project settings, configure the app's runtime
   environment variables for **Production** and **Preview** separately:
   `DATABASE_URL`, `WATTSNEXT_USE_NEON=true`, and any optional model-provider
   settings. Use a separate non-production database for Preview. These runtime
   values belong in Vercel; GitHub's direct database secret is for migrations.
5. In <https://github.com/paruchurisid/wattsNext/settings/environments>, review
   the `production` and `preview` environments. Required reviewers or deployment
   branch restrictions can pause or block automatic deployments. Remove required
   reviewers if production must deploy without a manual approval.

If the Vercel Git integration is also enabled, disable its automatic deployments
for this project if you want GitHub Actions to be the sole deployment path. This
avoids duplicate deployments and ensures deployments wait for CI.

## Run after setup

Open <https://github.com/paruchurisid/wattsNext/actions/workflows/ci-cd.yml>,
choose **Run workflow**, select `main`, and run it. CI must pass before the
workflow validates deployment credentials, applies versioned migrations, and
deploys production. Subsequent pushes to `main` repeat this automatically.

Missing configuration fails with an explicit Actions annotation before any
production migrations are applied. If the migration or deployment fails, fix the
cause and rerun the failed jobs. Previously applied migrations are checksum
verified and skipped on a repeat run.

Vercel reference: <https://vercel.com/kb/guide/how-can-i-use-github-actions-with-vercel>.
