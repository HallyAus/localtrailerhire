# HACS default submission checklist

This how-to is for maintainers preparing Local Trailer Hire for inclusion in
HACS's default integration list. It does not create a release or submit an
external pull request.

HACS requires its validation action to pass with no errors **and no ignored
checks**. Complete the steps in order and submit only after every prerequisite
is green.

## 1. Verify repository eligibility

- [ ] The repository is public, active, and hosted on GitHub.
- [ ] GitHub Issues are enabled.
- [ ] The repository has a concise description and relevant topics.
- [ ] `README.md` explains installation, configuration, use, and support.
- [ ] `hacs.json` has a display name and the AU country restriction.
- [ ] `custom_components/` contains only `localtrailerhire/`.
- [ ] `manifest.json` contains `domain`, `documentation`, `issue_tracker`,
      `codeowners`, `name`, and `version`.

## 2. Verify branding

HACS accepts local custom-integration branding. The required minimum is
`custom_components/localtrailerhire/brand/icon.png`; no separate
`home-assistant/brands` pull request is needed when this local icon exists.

- [ ] `icon.png` is a valid square PNG (currently 256×256).
- [ ] `logo.png` is a valid landscape PNG for light backgrounds.
- [ ] `dark_logo.png` is a valid landscape PNG for dark backgrounds.
- [ ] The files use only Home Assistant's supported brand filenames.

See the [Home Assistant brand-image documentation](https://developers.home-assistant.io/docs/core/integration/brand_images/)
and [HACS integration requirements](https://hacs.xyz/docs/publish/integration/).

## 3. Run local validation

From `D:\Claude\Projects\Localtrailerhire`:

```powershell
.\.venv\Scripts\python.exe -m pytest repo/tests -q
.\.venv\Scripts\python.exe -m ruff check repo/custom_components repo/tests
.\.venv\Scripts\python.exe -m ruff format --check repo/custom_components repo/tests
```

Also validate `hacs.json` as JSON and all workflow files as YAML. Do not publish
if any local check fails.

## 4. Obtain clean GitHub Actions results

- [ ] Push the release candidate through the normal review process.
- [ ] Confirm both jobs in `.github/workflows/validate.yml` pass.
- [ ] Confirm the HACS action ran without an `ignore` setting.
- [ ] Confirm the test workflow passes for the exact release commit.

Do not rely on an older green run: HACS requires the repository state being
submitted to pass current validation.

## 5. Publish the release

HACS currently installs this repository from the tag's GitHub source archive.
`hacs.json` intentionally does not set `zip_release` because the published
releases do not contain a consistently named integration asset.

- [ ] Update the manifest version in a separately reviewed release change.
- [ ] Run the manual **Release** workflow from `main` only after the Tests,
      Hassfest, and HACS checks pass for that exact commit.
- [ ] Create a full GitHub release after validation passes; a tag alone is not
      sufficient.
- [ ] Confirm the release tag exactly matches `v<manifest version>`.
- [ ] Confirm the release points to the exact validated commit.
- [ ] Confirm the released `hacs.json` still includes `country: ["AU"]`.
- [ ] Test installing that release through HACS as a custom repository.

If distribution later switches to `localtrailerhire.zip`, first verify the
asset is attached to every new release, then add both `"zip_release": true` and
`"filename": "localtrailerhire.zip"` to `hacs.json`. Never enable that mode
before the matching asset exists.

## 6. Submit to `hacs/default`

Only the repository owner or a major contributor may submit the pull request.

- [ ] Fork `hacs/default` under a personal account.
- [ ] Create a new branch from the upstream `master` branch.
- [ ] Add `HallyAus/localtrailerhire` alphabetically to the `integration` file.
- [ ] Complete the pull-request template accurately and allow maintainer edits.
- [ ] Link the clean HACS, Hassfest, and test workflow runs and the new full
      release.
- [ ] Submit the pull request and respond to automated or maintainer feedback.

HACS may take months to review a new default repository. Until the pull request
is merged and the next scheduled scan completes, users must keep adding Local
Trailer Hire as a custom repository.

Source: [HACS default-repository requirements](https://hacs.xyz/docs/publish/include/).
