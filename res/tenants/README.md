# Tenants (multi-tenant builds)

Each file here (`<slug>.json`) describes one reseller/tenant whose branded apps
this repo can build. `exelixis.json` is the platform owner's own tenant and is
the default; building with no tenant selected uses it and is unchanged.

A tenant is fully isolated: its apps talk to **its own** RustDesk server and key,
and enroll into **its own** workspace on the support panel. One tenant's apps can
never see or connect to another tenant's computers.

## The config file (committed, non-secret)

```jsonc
{
  "slug": "acme",                       // URL-safe id; must match the file name and the panel workspace
  "name": "Acme Remote Care",           // shown in release titles / notes
  "id_server": "rd.acme.example",       // the tenant's own RustDesk ID/rendezvous server
  "pub_key": "....=",                   // that server's PUBLIC key (not secret)
  "app_name": "AcmeSupport",            // internal name + URI scheme base (letters/digits only)
  "app_uri": "acmesupport",             // = app_name lower-cased; must match the panel's app link scheme
  "panel_url": "https://rustdesk.exelixisnet.gr",   // the shared panel (same host for every tenant)
  "exe_full": "AcmeSupport",            // download file name for the technician build
  "exe_quick": "AcmeQuickSupport",      // customer build file name — MUST contain "quick"
  "phone": "+30 210 000 0000",
  "email": "help@acme.example",
  "website": "https://acme.example",
  "color_primary": "#1D7A3A",
  "color_accent": "#E2642A"
}
```

The **enrollment token is the only secret** and is never stored here. Put it in the
repo secret `TENANT_ENROLL_TOKENS`, a JSON map of slug → token, e.g.
`{"acme":"<enroll token from the panel's Platform page>"}`. (The default tenant
keeps using the existing `EXELIXIS_ENROLL_TOKEN` secret.)

## Onboarding a tenant

1. In the panel: **Platform → Add workspace**. Set its RustDesk server/key, branding,
   logo and download links. Copy its **enrollment token** and **build config**.
2. Add `res/tenants/<slug>.json` here from the build config (copy `_example-acme.json`).
3. Add the token to the `TENANT_ENROLL_TOKENS` secret.
4. Run **Actions → "Exelixisnet IT Support - build" → Run workflow** with `tenant = <slug>`.
   It publishes a release tagged `v<version>-<slug>` with that tenant's apps.
5. Set the tenant's download links (on their Platform page) to that release's asset URLs.

## Known follow-up

`app_name`/`id_server`/`pub_key`/`panel_url`/`enroll token` are compiled in and give
full isolation. Per-tenant **app icons** (currently the Exelixisnet icon is used for
every build) and the in-app **contact strings** are a later branding pass — validate
them against a real tenant CI build before shipping to that tenant's customers.
