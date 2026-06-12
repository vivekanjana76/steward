"""The policy engine: every action is classified before it can execute.

This is the heart of Steward's bounded autonomy (CLAUDE.md §1/§3). Any tool
call that would mutate the outside world is expressed as a typed
:class:`Action` and classified into exactly one of three lists **before**
execution:

* **whitelist** — read-only or fully sandboxed work; allowed.
* **greylist** — reversible, clearly-labeled mutations (comments, labels,
  branches, draft PRs); requires explicit human approval (wired in the
  approval mechanism, issue #11).
* **blacklist** — merge, force-push, writing to the default branch, deleting
  branches, or acting on any repository other than the configured target;
  denied, always.

Two properties are enforced structurally, not by convention:

* :func:`classify` is a pure, deterministic function with **no override
  parameter** — there is no "just this once" path, and the kind→list mapping
  is module-level and frozen.
* Executors take an :class:`AuthorizedAction`, which only
  :meth:`PolicyEngine.authorize` produces, and it raises for anything but an
  ``allow`` verdict. A blacklisted action therefore has no code path to an
  executor.

Every decision carries the rule that fired and a human-readable reason, so it
can be audit-logged and replayed (CLAUDE.md §11).
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from steward.config import Settings


class ActionKind(StrEnum):
    """Every kind of action Steward can propose, mutating or not.

    New action types MUST be added here and to :data:`_KIND_TO_LIST` (the
    exhaustiveness check at import time fails otherwise), so no action can
    exist without a classification.
    """

    # Read-only / sandboxed (whitelist candidates).
    READ_ISSUE = "read_issue"
    SEARCH_CODE = "search_code"
    FIND_DUPLICATES = "find_duplicates"
    RUN_SANDBOXED_TESTS = "run_sandboxed_tests"

    # Reversible, labeled mutations (greylist candidates).
    POST_ISSUE_COMMENT = "post_issue_comment"
    APPLY_LABELS = "apply_labels"
    CREATE_BRANCH = "create_branch"
    PUSH_BRANCH = "push_branch"
    OPEN_DRAFT_PR = "open_draft_pr"

    # Irreversible or trust-breaking operations (blacklist).
    MERGE_PR = "merge_pr"
    FORCE_PUSH = "force_push"
    PUSH_TO_DEFAULT_BRANCH = "push_to_default_branch"
    DELETE_BRANCH = "delete_branch"


class PolicyList(StrEnum):
    """The three policy lists an :class:`ActionKind` can belong to."""

    WHITELIST = "whitelist"
    GREYLIST = "greylist"
    BLACKLIST = "blacklist"


class PolicyVerdict(StrEnum):
    """The decision the engine returns for one proposed action."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


# The single source of truth for classification. Module-level, read-only, and
# checked for exhaustiveness at import time — an ActionKind without an entry
# is a startup error, never a runtime surprise.
_KIND_TO_LIST: MappingProxyType[ActionKind, PolicyList] = MappingProxyType(
    {
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
)

if set(_KIND_TO_LIST) != set(ActionKind):  # pragma: no cover - import-time guard
    _missing = sorted(k.value for k in set(ActionKind) - set(_KIND_TO_LIST))
    raise RuntimeError(f"ActionKind(s) without a policy classification: {_missing}")


def list_for(kind: ActionKind) -> PolicyList:
    """Return the policy list ``kind`` belongs to."""
    return _KIND_TO_LIST[kind]


class Action(BaseModel):
    """One proposed action, the unit the policy engine reasons about.

    ``repo`` is the ``owner/name`` target; the engine denies anything aimed at
    a repository other than the configured target (CLAUDE.md §5). ``summary``
    is the human-readable intent shown in the approval queue and audit log.
    """

    model_config = ConfigDict(frozen=True)

    kind: ActionKind
    repo: str = Field(min_length=3, pattern=r"^[^/\s]+/[^/\s]+$")
    summary: str = Field(min_length=1)
    detail: dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    """The auditable outcome of classifying one :class:`Action`.

    Carries the verdict, the rule that fired, and a human-readable reason —
    everything the audit log needs to make the decision replayable.
    """

    model_config = ConfigDict(frozen=True)

    action: Action
    verdict: PolicyVerdict
    rule: str
    reason: str


class PolicyViolationError(RuntimeError):
    """Raised when something asks to execute an action the policy forbids."""


class AuthorizedAction(BaseModel):
    """Proof that an action passed the policy engine with an ``allow`` verdict.

    Executors require this type, and :meth:`PolicyEngine.authorize` is its
    only producer — that is what makes blacklist execution structurally
    impossible rather than merely discouraged.
    """

    model_config = ConfigDict(frozen=True)

    action: Action
    decision: PolicyDecision


def _normalize_repo(repo: str) -> str:
    return repo.strip().lower()


def classify(action: Action, *, target_repo: str) -> PolicyDecision:
    """Classify ``action`` against the policy. Pure and deterministic.

    ``target_repo`` is the only repository Steward may act on (CLAUDE.md §5);
    any other target is denied regardless of the action kind. There is no
    override parameter by design.
    """
    if _normalize_repo(action.repo) != _normalize_repo(target_repo):
        return PolicyDecision(
            action=action,
            verdict=PolicyVerdict.DENY,
            rule="repo-scope",
            reason=(
                f"action targets {action.repo!r} but Steward is scoped to "
                f"{target_repo!r}; acting outside the configured repository is denied"
            ),
        )

    policy_list = list_for(action.kind)
    if policy_list is PolicyList.BLACKLIST:
        return PolicyDecision(
            action=action,
            verdict=PolicyVerdict.DENY,
            rule="blacklist",
            reason=f"{action.kind.value} is blacklisted and can never execute",
        )
    if policy_list is PolicyList.GREYLIST:
        return PolicyDecision(
            action=action,
            verdict=PolicyVerdict.REQUIRE_APPROVAL,
            rule="greylist",
            reason=f"{action.kind.value} mutates the world and requires human approval",
        )
    return PolicyDecision(
        action=action,
        verdict=PolicyVerdict.ALLOW,
        rule="whitelist",
        reason=f"{action.kind.value} is read-only or sandboxed and is allowed",
    )


class PolicyEngine:
    """Classifies actions against one configured target repository.

    The engine is the sole producer of :class:`AuthorizedAction`; executors
    must demand that type so nothing can run without passing through
    :func:`classify` first.
    """

    def __init__(self, *, target_repo: str) -> None:
        if "/" not in target_repo:
            raise ValueError("target_repo must be 'owner/name'")
        self._target_repo = target_repo

    @property
    def target_repo(self) -> str:
        """The only repository this engine will ever authorize actions on."""
        return self._target_repo

    def classify(self, action: Action) -> PolicyDecision:
        """Classify ``action``; see :func:`classify`."""
        return classify(action, target_repo=self._target_repo)

    def authorize(self, action: Action) -> AuthorizedAction:
        """Return execution proof for ``action``, or raise.

        Only an ``allow`` verdict yields an :class:`AuthorizedAction`. A
        greylist action must instead go through the human-approval mechanism
        (issue #11); a deny verdict has no execution path at all.
        """
        decision = self.classify(action)
        if decision.verdict is not PolicyVerdict.ALLOW:
            raise PolicyViolationError(
                f"cannot authorize {action.kind.value} on {action.repo}: "
                f"{decision.verdict.value} ({decision.reason})"
            )
        return AuthorizedAction(action=action, decision=decision)


def build_policy_engine(settings: Settings) -> PolicyEngine:
    """Construct a :class:`PolicyEngine` scoped to the configured target repo.

    Raises :class:`PolicyViolationError` when ``STEWARD_GITHUB_REPO`` is not
    set — an unscoped engine must never exist (CLAUDE.md §5).
    """
    if not settings.github_repo:
        raise PolicyViolationError(
            "STEWARD_GITHUB_REPO is not set; the policy engine requires an "
            "explicit target repository"
        )
    return PolicyEngine(target_repo=settings.github_repo)
