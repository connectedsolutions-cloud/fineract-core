from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .accounting import (
    BLOCK as ACCOUNTING_BLOCK, AccountingContract, accounting_retry_keys,
    apply_accounting_plan, build_accounting_plan, inspect_accounting, reconcile_accounting,
)
from .aml_alerts import (
    BLOCK as AML_ALERT_BLOCK, AmlAlertContract, apply_aml_alert_plan,
    build_aml_alert_plan, inspect_aml_alerts, reconcile_aml_alerts,
)
from .client_staff_assignments import (
    BLOCK as CLIENT_STAFF_ASSIGNMENT_BLOCK, ClientStaffAssignmentContract,
    apply_client_staff_assignment_plan, build_client_staff_assignment_plan,
    inspect_client_staff_assignments, reconcile_client_staff_assignments,
)
from .clients import ClientContract
from .config import ROOT, Settings
from .employees import (
    BLOCK as EMPLOYEE_BLOCK, EmployeeContract, apply_employee_plan,
    build_employee_plan, inspect_employees, reconcile_employees,
)
from .dte_history import (
    BLOCK as DTE_HISTORY_BLOCK, DteApplyControls, DteHistoryContract, apply_dte_history_plan,
    build_dte_history_plan, inspect_dte_history, prepare_dte_history_target,
    reconcile_dte_history,
)
from .engine import apply_plan, build_plan, inspect_clients, reconcile
from .family_references import (
    BLOCK as FAMILY_REFERENCES_BLOCK, FamilyReferenceContract,
    PERSONAL_FAMILY_REFERENCES_BLOCK, PersonalFamilyReferenceContract,
    apply_family_reference_plan, build_family_reference_plan,
    inspect_family_references, reconcile_family_references,
)
from .loans import (
    BLOCK as LOANS_BLOCK, LoanApplyControls, LoanContract, apply_loan_plan, build_loan_plan,
    inspect_loans, loan_retry_keys, reconcile_loans,
)
from .membership import (
    BLOCK as MEMBERSHIP_BLOCK, MembershipContract, apply_membership_plan,
    build_membership_plan, inspect_membership, reconcile_membership,
)
from .mobile_collections import (
    BLOCK as MOBILE_COLLECTION_BLOCK, MobileCollectionContract,
    apply_mobile_collection_plan, build_mobile_collection_plan,
    inspect_mobile_collections, reconcile_mobile_collections,
)
from .native_share_engine import (
    apply_native_share_plan, build_native_share_plan, native_share_execution_blockers,
    prepare_native_share_target, reconcile_native_shares,
)
from .native_shares import BLOCK as NATIVE_SHARES_BLOCK, NativeShareContract, inspect_native_shares
from .share_yield import (
    BLOCK as SHARE_YIELD_BLOCK, ShareYieldContract, apply_share_yield_plan,
    build_share_yield_plan, inspect_share_yields, prepare_share_yield_target,
    reconcile_share_yields,
)
from .pep import BLOCK as PEP_BLOCK, PepContract, apply_pep_plan, build_pep_plan, inspect_pep, reconcile_pep
from .savings import BLOCK as SAVINGS_BLOCK, SavingsContract, inspect_savings
from .savings_account_parties import (
    BLOCK as SAVINGS_ACCOUNT_PARTIES_BLOCK, SavingsAccountPartyContract,
    apply_savings_account_party_plan, build_savings_account_party_plan,
    inspect_savings_account_parties, reconcile_savings_account_parties,
)
from .savings_engine import apply_savings_plan, build_savings_plan, reconcile_savings
from .state import State

ACCOUNTING_SERVICE = "accounting-journal-entries"


@dataclass
class ServiceRuntime:
    """In-process adapter over the independently implemented sync blocks."""

    settings: Settings
    state: State
    loan_controls: LoanApplyControls | None = None
    dte_controls: DteApplyControls | None = None
    accounting_periods: tuple[str, ...] = ()
    run_mode: str | None = None

    def __post_init__(self) -> None:
        self.contracts: dict[str, Any] = {
            "clients": ClientContract.load(self.settings.mapping_path),
            PEP_BLOCK: PepContract.load(self.settings.pep_mapping_path),
            FAMILY_REFERENCES_BLOCK: FamilyReferenceContract.load(self.settings.family_reference_mapping_path),
            PERSONAL_FAMILY_REFERENCES_BLOCK: PersonalFamilyReferenceContract.load(
                self.settings.personal_family_reference_mapping_path
            ),
            EMPLOYEE_BLOCK: EmployeeContract.load(self.settings.employee_mapping_path),
            CLIENT_STAFF_ASSIGNMENT_BLOCK: ClientStaffAssignmentContract.load(
                self.settings.client_staff_assignment_mapping_path
            ),
            MEMBERSHIP_BLOCK: MembershipContract.load(self.settings.membership_mapping_path),
            NATIVE_SHARES_BLOCK: NativeShareContract.load(self.settings.native_share_mapping_path),
            SHARE_YIELD_BLOCK: ShareYieldContract.load(ROOT / "config/native_share_yield.json"),
            AML_ALERT_BLOCK: AmlAlertContract.load(self.settings.aml_alert_mapping_path),
            SAVINGS_BLOCK: SavingsContract.load(self.settings.savings_mapping_path),
            SAVINGS_ACCOUNT_PARTIES_BLOCK: SavingsAccountPartyContract.load(ROOT / "config/savings_account_parties.json"),
            LOANS_BLOCK: LoanContract.load(ROOT / "config/loans.json"),
            MOBILE_COLLECTION_BLOCK: MobileCollectionContract.load(
                self.settings.mobile_collection_mapping_path
            ),
            DTE_HISTORY_BLOCK: DteHistoryContract.load(self.settings.dte_history_mapping_path),
            ACCOUNTING_SERVICE: AccountingContract.load(ROOT / "config/accounting.json"),
        }

    def inspect(self, block: str) -> dict[str, Any]:
        contract = self.contracts[block]
        if block == ACCOUNTING_SERVICE:
            return inspect_accounting(
                self.settings.source, contract, self.state.accounting_cutoff["date"],
                target_pg_url=self.settings.target.pg_url,
            )
        if block == LOANS_BLOCK:
            return inspect_loans(
                self.settings.source, contract, source_key=None, target_pg_url=self.settings.target.pg_url
            )
        if block == MOBILE_COLLECTION_BLOCK:
            return inspect_mobile_collections(self.settings, contract)
        if block == DTE_HISTORY_BLOCK:
            return inspect_dte_history(self.settings, contract)
        if block == NATIVE_SHARES_BLOCK:
            report = inspect_native_shares(self.settings, contract, None)
            report["strict_ready"] = report["ready"]
            report["execution_blockers"] = native_share_execution_blockers(report)
            report["ready"] = not report["execution_blockers"]
            return report
        if block == SHARE_YIELD_BLOCK:
            return inspect_share_yields(self.settings, contract)
        if block == SAVINGS_BLOCK:
            return inspect_savings(self.settings, contract)
        if block == SAVINGS_ACCOUNT_PARTIES_BLOCK:
            return inspect_savings_account_parties(self.settings, contract)
        if block == AML_ALERT_BLOCK:
            return inspect_aml_alerts(self.settings, contract)
        if block == MEMBERSHIP_BLOCK:
            return inspect_membership(self.settings, contract)
        if block == CLIENT_STAFF_ASSIGNMENT_BLOCK:
            return inspect_client_staff_assignments(self.settings, contract)
        if block == EMPLOYEE_BLOCK:
            return inspect_employees(self.settings, contract)
        if block in {FAMILY_REFERENCES_BLOCK, PERSONAL_FAMILY_REFERENCES_BLOCK}:
            return inspect_family_references(self.settings, contract)
        if block == PEP_BLOCK:
            return inspect_pep(self.settings, contract)
        if block == "clients":
            return inspect_clients(self.settings, contract)
        raise ValueError(f"No runtime adapter for service: {block}")

    def prepare(self, block: str) -> dict[str, Any]:
        """Provision reviewed service prerequisites before strict workflow inspection."""
        if block == NATIVE_SHARES_BLOCK:
            return prepare_native_share_target(self.settings, self.contracts[block])
        if block == SHARE_YIELD_BLOCK:
            return prepare_share_yield_target(self.settings, self.contracts[block])
        if block == DTE_HISTORY_BLOCK:
            return prepare_dte_history_target(self.settings, self.contracts[block])
        return {"performed": False}

    def plan(self, block: str) -> tuple[str, dict[str, Any]]:
        contract = self.contracts[block]
        if block == ACCOUNTING_SERVICE:
            return build_accounting_plan(
                self.settings, self.state, contract, None,
                source_periods=list(self.accounting_periods),
                full_scope=not self.accounting_periods,
            )
        if block == LOANS_BLOCK:
            return build_loan_plan(
                self.settings,
                self.state,
                contract,
                None,
                None,
                self.state.accounting_cutoff["date"],
                skip_unchanged=self.run_mode == "full-resync",
            )
        if block == MOBILE_COLLECTION_BLOCK:
            return build_mobile_collection_plan(self.settings, self.state, contract, None)
        if block == DTE_HISTORY_BLOCK:
            return build_dte_history_plan(self.settings, self.state, contract, None)
        if block == NATIVE_SHARES_BLOCK:
            return build_native_share_plan(self.settings, self.state, contract, None)
        if block == SHARE_YIELD_BLOCK:
            return build_share_yield_plan(self.settings, self.state, contract, None)
        if block == SAVINGS_BLOCK:
            return build_savings_plan(self.settings, self.state, contract, None, False)
        if block == SAVINGS_ACCOUNT_PARTIES_BLOCK:
            return build_savings_account_party_plan(self.settings, self.state, contract, None)
        if block == AML_ALERT_BLOCK:
            return build_aml_alert_plan(self.settings, self.state, contract, None)
        if block == MEMBERSHIP_BLOCK:
            return build_membership_plan(self.settings, self.state, contract, None)
        if block == CLIENT_STAFF_ASSIGNMENT_BLOCK:
            return build_client_staff_assignment_plan(self.settings, self.state, contract, None)
        if block == EMPLOYEE_BLOCK:
            return build_employee_plan(self.settings, self.state, contract, None)
        if block in {FAMILY_REFERENCES_BLOCK, PERSONAL_FAMILY_REFERENCES_BLOCK}:
            return build_family_reference_plan(self.settings, self.state, contract, None)
        if block == PEP_BLOCK:
            return build_pep_plan(self.settings, self.state, contract, None)
        if block == "clients":
            return build_plan(self.settings, self.state, contract, None)
        raise ValueError(f"No runtime adapter for service: {block}")

    def apply(
        self, block: str, plan_id: str, production_confirmation: str | None = None
    ) -> tuple[str, dict[str, Any]]:
        contract = self.contracts[block]
        if block == ACCOUNTING_SERVICE:
            return apply_accounting_plan(
                self.settings, self.state, contract, plan_id, production_confirmation,
            )
        if block == AML_ALERT_BLOCK:
            return apply_aml_alert_plan(self.settings, self.state, contract, plan_id, production_confirmation)
        if block == SAVINGS_BLOCK:
            return apply_savings_plan(self.settings, self.state, contract, plan_id, production_confirmation)
        if block == SAVINGS_ACCOUNT_PARTIES_BLOCK:
            return apply_savings_account_party_plan(self.settings, self.state, contract, plan_id, production_confirmation)
        if block == NATIVE_SHARES_BLOCK:
            return apply_native_share_plan(self.settings, self.state, contract, plan_id, production_confirmation)
        if block == SHARE_YIELD_BLOCK:
            return apply_share_yield_plan(self.settings, self.state, contract, plan_id, production_confirmation)
        if block == MEMBERSHIP_BLOCK:
            return apply_membership_plan(self.settings, self.state, contract, plan_id, production_confirmation)
        if block == EMPLOYEE_BLOCK:
            return apply_employee_plan(self.settings, self.state, contract, plan_id, production_confirmation)
        if block == CLIENT_STAFF_ASSIGNMENT_BLOCK:
            return apply_client_staff_assignment_plan(
                self.settings, self.state, contract, plan_id, production_confirmation
            )
        if block in {FAMILY_REFERENCES_BLOCK, PERSONAL_FAMILY_REFERENCES_BLOCK}:
            return apply_family_reference_plan(self.settings, self.state, contract, plan_id, production_confirmation)
        if block == PEP_BLOCK:
            return apply_pep_plan(self.settings, self.state, contract, plan_id, production_confirmation)
        if block == LOANS_BLOCK:
            return apply_loan_plan(
                self.settings, self.state, contract, plan_id, production_confirmation,
                controls=self.loan_controls,
            )
        if block == MOBILE_COLLECTION_BLOCK:
            return apply_mobile_collection_plan(
                self.settings, self.state, contract, plan_id, production_confirmation
            )
        if block == DTE_HISTORY_BLOCK:
            return apply_dte_history_plan(
                self.settings, self.state, contract, plan_id, production_confirmation,
                controls=self.dte_controls,
            )
        if block == "clients":
            return apply_plan(self.settings, self.state, contract, plan_id, production_confirmation)
        raise ValueError(f"No runtime adapter for service: {block}")

    def reconcile(self, block: str, run_id: str) -> dict[str, Any]:
        contract = self.contracts[block]
        if block == ACCOUNTING_SERVICE:
            return reconcile_accounting(self.settings, self.state, contract, run_id)
        if block == AML_ALERT_BLOCK:
            return reconcile_aml_alerts(self.settings, self.state, contract, run_id)
        if block == SAVINGS_BLOCK:
            return reconcile_savings(self.settings, self.state, contract, run_id)
        if block == SAVINGS_ACCOUNT_PARTIES_BLOCK:
            return reconcile_savings_account_parties(self.settings, self.state, contract, run_id)
        if block == NATIVE_SHARES_BLOCK:
            return reconcile_native_shares(self.settings, self.state, contract, run_id)
        if block == SHARE_YIELD_BLOCK:
            return reconcile_share_yields(self.settings, self.state, contract, run_id)
        if block == MEMBERSHIP_BLOCK:
            return reconcile_membership(self.settings, self.state, contract, run_id)
        if block == EMPLOYEE_BLOCK:
            return reconcile_employees(self.settings, self.state, contract, run_id)
        if block == CLIENT_STAFF_ASSIGNMENT_BLOCK:
            return reconcile_client_staff_assignments(self.settings, self.state, contract, run_id)
        if block in {FAMILY_REFERENCES_BLOCK, PERSONAL_FAMILY_REFERENCES_BLOCK}:
            return reconcile_family_references(self.settings, self.state, contract, run_id)
        if block == PEP_BLOCK:
            return reconcile_pep(self.settings, self.state, contract, run_id)
        if block == LOANS_BLOCK:
            return reconcile_loans(self.settings, self.state, contract, run_id)
        if block == MOBILE_COLLECTION_BLOCK:
            return reconcile_mobile_collections(self.settings, self.state, contract, run_id)
        if block == DTE_HISTORY_BLOCK:
            return reconcile_dte_history(self.settings, self.state, contract, run_id)
        if block == "clients":
            return reconcile(self.settings, self.state, contract, run_id)
        raise ValueError(f"No runtime adapter for service: {block}")

    def retry(
        self, block: str, previous_run_id: str,
        production_confirmation: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Retry the failed portion of an existing child run using its frozen plan."""
        previous = self.state.run(previous_run_id)
        expected_block = ACCOUNTING_BLOCK if block == ACCOUNTING_SERVICE else block
        if previous["block"] != expected_block:
            raise RuntimeError(
                f"Child run {previous_run_id} belongs to {previous['block']}, not {block}"
            )
        plan_id = previous["plan_id"]
        contract = self.contracts[block]
        if block == ACCOUNTING_SERVICE:
            keys = accounting_retry_keys(self.state, previous_run_id)
            if not keys:
                # The apply phase is already terminal and only strict
                # reconciliation remains. Keep the exact child identity; the
                # accounting reconciler reads durable outcomes across its
                # frozen plan's retry chain.
                return previous_run_id, dict(previous.get("summary", {}))
            return apply_accounting_plan(
                self.settings, self.state, contract, plan_id, production_confirmation,
                keys, retry_from_run=previous_run_id,
            )
        if block == LOANS_BLOCK:
            loan_plan = self.state.plan(plan_id)
            keys = loan_retry_keys(
                loan_plan["document"]["actions"], self.state.plan_run_items(plan_id)
            )
            if not keys:
                # Apply already recovered every planned loan and only strict
                # reconciliation remains. Reuse the exact child run so the
                # workflow cannot mistake an empty retry for a successful one.
                return previous_run_id, dict(previous.get("summary", {}))
            return apply_loan_plan(
                self.settings, self.state, contract, plan_id, production_confirmation,
                keys, controls=self.loan_controls,
            )

        failed_items = self.state.run_items(previous_run_id, failed_only=True)
        keys = {item["source_key"] for item in failed_items}
        if not keys:
            # Apply already completed and the workflow failed while reconciling.
            # Reconcile that exact child run again instead of creating an empty
            # retry run that could be mistaken for successful recovery.
            return previous_run_id, dict(previous.get("summary", {}))
        if block == DTE_HISTORY_BLOCK:
            return apply_dte_history_plan(
                self.settings, self.state, contract, plan_id, production_confirmation,
                keys, controls=self.dte_controls,
            )
        apply_functions = {
            AML_ALERT_BLOCK: apply_aml_alert_plan,
            SAVINGS_BLOCK: apply_savings_plan,
            SAVINGS_ACCOUNT_PARTIES_BLOCK: apply_savings_account_party_plan,
            NATIVE_SHARES_BLOCK: apply_native_share_plan,
            SHARE_YIELD_BLOCK: apply_share_yield_plan,
            MEMBERSHIP_BLOCK: apply_membership_plan,
            EMPLOYEE_BLOCK: apply_employee_plan,
            CLIENT_STAFF_ASSIGNMENT_BLOCK: apply_client_staff_assignment_plan,
            FAMILY_REFERENCES_BLOCK: apply_family_reference_plan,
            PERSONAL_FAMILY_REFERENCES_BLOCK: apply_family_reference_plan,
            PEP_BLOCK: apply_pep_plan,
            MOBILE_COLLECTION_BLOCK: apply_mobile_collection_plan,
            "clients": apply_plan,
        }
        try:
            apply_function = apply_functions[block]
        except KeyError as exc:
            raise ValueError(f"No retry adapter for service: {block}") from exc
        return apply_function(
            self.settings, self.state, contract, plan_id, production_confirmation, keys
        )
