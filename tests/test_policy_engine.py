"""Unit tests for the policy engine — safety-critical (CLAUDE.md §9).

These tests exhaustively pin the whitelist/greylist/blacklist partition and
prove the structural guarantees: blacklisted actions and off-target
repositories can never be authorized, greylist actions always require
approval, and there is no override path. Treat a failure here as a release
blocker.
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from steward.config import Settings
from steward.policy import (
    Action,
    ActionKind,
    AuthorizedAction,
    PolicyEngine,
    PolicyList,
    PolicyVerdict,
    PolicyViolationError,
    build_policy_engine,
    classify,
    list_for,
)

TARGET = "vivekanjana76/steward-demo"

# The golden partition. Changing a kind's list is a conscious, reviewed edit
# here — never an accident.
EXPECTED_LIST: dict[ActionKind, PolicyList] = {
    ActionKind.READ_ISSUE: PolicyList.WHITELIST,
    ActionKind.SEARCH_CODE: PolicyList.WHITELIST,
    ActionKind.FIND_DUPLICATES: PolicyList.WHITELIST,
    ActionKind.RUN_SANDBOXED_TESTS: PolicyList.WHITELIST,
    ActionKind.POST_ISSUE_COMMENT: PolicyList.GREYLIST,
    ActionKind.APPLY_LABELS: PolicyList.GREYLIST,
    ActionKind.CREATE_BRANCH: PolicyList.GREYLIST,
    ActionKind.PUSH_BRANCH: PolicyList.GREYLIST,
    ActionKind.OPEN_DRAFT_PR: PolicyList.GREYLIST,
    ActionKind.MERGE_PR: PolicyList.BLACKLIST,
    ActionKind.FORCE_PUSH: PolicyList.BLACKLIST,
    ActionKind.PUSH_TO_DEFAULT_BRANCH: PolicyList.BLACKLIST,
    ActionKind.DELETE_BRANCH: PolicyList.BLACKLIST,
}

LIST_TO_VERDICT: dict[PolicyList, PolicyVerdict] = {
    PolicyList.WHITELIST: PolicyVerdict.ALLOW,
    PolicyList.GREYLIST: PolicyVerdict.REQUIRE_APPROVAL,
    PolicyList.BLACKLIST: PolicyVerdict.DENY,
}


def _action(kind: ActionKind, repo: str = TARGET) -> Action:
    return Action(kind=kind, repo=repo, summary=f"test {kind.value}")


class TestPartition:
    def test_every_kind_is_classified(self) -> None:
        assert set(EXPECTED_LIST) == set(ActionKind)
        for kind in ActionKind:
            assert list_for(kind) is EXPECTED_LIST[kind]

    @pytest.mark.parametrize("kind", list(ActionKind))
    def test_verdict_matches_list_on_target_repo(self, kind: ActionKind) -> None:
        decision = classify(_action(kind), target_repo=TARGET)
        assert decision.verdict is LIST_TO_VERDICT[EXPECTED_LIST[kind]]
        assert decision.rule == EXPECTED_LIST[kind].value
        assert decision.reason
        assert decision.action.kind is kind


class TestRepoScope:
    @pytest.mark.parametrize("kind", list(ActionKind))
    def test_any_action_on_another_repo_is_denied(self, kind: ActionKind) -> None:
        decision = classify(_action(kind, repo="someone-else/their-repo"), target_repo=TARGET)
        assert decision.verdict is PolicyVerdict.DENY
        assert decision.rule == "repo-scope"

    def test_repo_comparison_ignores_case_and_whitespace(self) -> None:
        decision = classify(
            _action(ActionKind.READ_ISSUE, repo=TARGET.upper()),
            target_repo=f"  {TARGET}  ",
        )
        assert decision.verdict is PolicyVerdict.ALLOW


class TestNoOverride:
    def test_classify_has_no_override_parameter(self) -> None:
        # The "no just-this-once" rule, pinned structurally: classify accepts
        # the action and the target repo, nothing else.
        params = set(inspect.signature(classify).parameters)
        assert params == {"action", "target_repo"}

    def test_classify_is_deterministic(self) -> None:
        action = _action(ActionKind.MERGE_PR)
        first = classify(action, target_repo=TARGET)
        second = classify(action, target_repo=TARGET)
        assert first == second


class TestAuthorize:
    def test_whitelist_action_yields_authorization(self) -> None:
        engine = PolicyEngine(target_repo=TARGET)
        authorized = engine.authorize(_action(ActionKind.READ_ISSUE))
        assert isinstance(authorized, AuthorizedAction)
        assert authorized.decision.verdict is PolicyVerdict.ALLOW

    @pytest.mark.parametrize(
        "kind",
        [k for k, lst in EXPECTED_LIST.items() if lst is not PolicyList.WHITELIST],
    )
    def test_non_whitelist_action_raises(self, kind: ActionKind) -> None:
        engine = PolicyEngine(target_repo=TARGET)
        with pytest.raises(PolicyViolationError):
            engine.authorize(_action(kind))

    def test_whitelist_action_on_foreign_repo_raises(self) -> None:
        engine = PolicyEngine(target_repo=TARGET)
        with pytest.raises(PolicyViolationError):
            engine.authorize(_action(ActionKind.READ_ISSUE, repo="other/repo"))

    def test_engine_rejects_malformed_target_repo(self) -> None:
        with pytest.raises(ValueError):
            PolicyEngine(target_repo="not-a-repo")

    def test_build_requires_configured_target_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("STEWARD_GITHUB_REPO", raising=False)
        unscoped = Settings(_env_file=None)  # type: ignore[call-arg]
        with pytest.raises(PolicyViolationError):
            build_policy_engine(unscoped)

    def test_build_scopes_engine_to_configured_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STEWARD_GITHUB_REPO", TARGET)
        scoped = Settings(_env_file=None)  # type: ignore[call-arg]
        assert build_policy_engine(scoped).target_repo == TARGET


class TestModels:
    def test_action_is_frozen(self) -> None:
        action = _action(ActionKind.READ_ISSUE)
        with pytest.raises(ValidationError):
            action.repo = "other/repo"  # type: ignore[misc]

    def test_decision_is_frozen(self) -> None:
        decision = classify(_action(ActionKind.READ_ISSUE), target_repo=TARGET)
        with pytest.raises(ValidationError):
            decision.verdict = PolicyVerdict.ALLOW  # type: ignore[misc]

    @pytest.mark.parametrize("repo", ["", "norepo", "owner/", "/name", "a b/c"])
    def test_malformed_repo_rejected(self, repo: str) -> None:
        with pytest.raises(ValidationError):
            Action(kind=ActionKind.READ_ISSUE, repo=repo, summary="x")

    def test_empty_summary_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Action(kind=ActionKind.READ_ISSUE, repo=TARGET, summary="")
