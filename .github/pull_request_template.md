<!-- Title: use Conventional Commit style, e.g. "feat(policy): add greylist approval" -->

Closes #

## What & why
<!-- What changed and WHY (not just what). -->

## How it was tested
- [ ] Unit (network / model / Docker mocked)
- [ ] Integration

## Eval impact
<!-- Paste before/after scores whenever agent, policy, triage, repro, or fix
behavior changed. Otherwise: n/a. -->

## Definition of Done
- [ ] Implements the acceptance criteria
- [ ] Unit tests cover new logic; network/model/Docker calls mocked
- [ ] Any new world-mutating action is classified in the policy engine and defaults to dry-run
- [ ] `ruff`, `pyright`, `pytest` pass locally and in CI
- [ ] Public functions / tools / Pydantic models documented
- [ ] README / docs / ADRs updated if behavior or setup changed
- [ ] Opened as **draft**; human reviews and squash-merges (Steward never merges)

## Trace links / screenshots
<!-- Langfuse trace links for behavior changes; screenshots for UI changes. -->
