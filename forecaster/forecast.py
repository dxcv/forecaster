""" This module provides a Forecast class for use in forecasts.

This is where most of the financial forecasting logic of the Forecaster
package lives. It applies Scenario, Strategy, and Tax information to
determine how account balances will grow or shrink year-over-year.
"""

from collections import defaultdict
from decimal import Decimal
from forecaster.ledger import Money
from forecaster.utility import when_conv

# pylint: disable=too-many-instance-attributes
# This object has a complex state. We could store the records for each
# year in some sort of pandas-style frame or table, but for now each
# data column is its own named attribute.
class Forecast(object):
    """ A financial forecast spanning multiple years.

    A `Forecast` contains various `Account` objects with balances that
    grow (or shrink) from year to year. The `Forecast` object also
    contains `Person` objects describing the plannees, `Scenario`
    information describing economic conditions over the course of the
    forecast, and `Strategy` objects to describe the plannee's behaviour.

    The `Forecast` manages inflows to and outflows from (or between)
    accounts based on `Strategy` and `Scenario` information.

    The `Forecast` can be built around any number of people, but is
    ordinarily built around either a single person or a spousal
    couple (since spouses have specific tax treatment). Otherwise, it's
    better practice to build separate `Forecast` objects for separate
    people.

    Attributes:
        people (Iterable[Person]): The people for whom the financial
            forecast is being generated. Typically a single person or a
            person and their spouse.

            Note that all `Person` objects must have the same
            `this_year` attribute, as must their various accounts.
        assets (Iterable[Account]): Assets of the `people`.
        debts (Iterable[Debt]): Debts of the `people`.

        scenario (Scenario): Economic information for the forecast
            (e.g. inflation and stock market returns for each year)

        contribution_strategy (ContributionStrategy): A callable
            object that determines the gross contribution for a
            year. See the documentation for `ContributionStrategy` for
            acceptable args when calling this object.
        withdrawal_strategy (WithdrawalStrategy): A callable
            object that determines the amount to withdraw for a
            year. See the documentation for `WithdrawalStrategy` for
            acceptable args when calling this object.
        contribution_transaction_strategy (TransactionStrategy): A
            callable object that determines the schedule of
            transactions for any contributions during the year.
            See the documentation for `TransactionStrategy` for
            acceptable args when calling this object.
        withdrawal_transaction_strategy
            (WithdrawalTransactionStrategy):
            A callable object that determines the schedule of
            transactions for any contributions during the year.
            See the documentation for `TransactionStrategy` for
            acceptable args when calling this object.
        debt_payment_strategy (DebtPaymentStrategy): A callable object
            that determines the schedule of debt payments, including
            accelerated debt payments drawn from gross contributions.
            See the documentation for `DebtPaymentStrategy` for
            acceptable args when calling this object.

        tax_treatment (Tax): A callable object that determines the total
            amount of tax owing in a year. See the documentation for
            `Tax` for acceptable args when calling this object.

        gross_income (dict[int, Money]): The gross income for the
            family.
        tax_withheld_on_income (dict[int, Money]): Taxes deducted at
            source (or paid by installment during the year) on
            employment income.
        net_income (dict[int, Money]): The net income for the family.

        tax_carryover (dict[int, Money]): The amount of any refund or
            outstanding tax payable, based on the previous year's
            tax withholdings.
        other_carryover (dict[int, Money]): The amount of inter-year
            carryover (other than tax refunds), such as excess
            withdrawals being recontributed.
        contributions_from_income (dict[int, Money]): The amount to be
            contributed to savings from employment income in each year.
        contributions_from_carryover (dict[int, Money]): The amount to
            be contributed to savings from tax_carryover and
            other_carryover.
        contributions_from_asset_sales (dict[int, Money]): The amount to
            be contributed to savings from asset sales in each year.
        gross_contributions (dict[int, Money]): The amount available to
            contribute to savings, before any reductions. This is the
            sum of net income and various contributions_from_* values.
        reduction_from_debt (dict[int, Money]): The amount to be
            diverted from contributions to debt repayment in each year.
        reduction_from_other (dict[int, Money]): The amount to be
            diverted from contributions for other spending purposes in
            each year.
        contribution_reductions (dict[int, Money]): Amounts diverted
            from savings, such as certain debt repayments or childcare.
        net_contributions (dict[int, Money]): The total amount
            contributed to savings accounts.

        principal (dict[int, Money]): The total value of all savings
            accounts (but not other property) at the start of each year.
        gross_return (dict[int, Money]): The total return on principal
            (only for the amounts included in `principal`) by the end of
            the year.
        tax_withheld_on_return (dict[int, Money]): Taxes deducted at
            source on the returns on investments.
        net_return (dict[int, Money]): The total return on principal
            (only for the amounts included in `principal`) by the end of
            the year, net of withholding taxes.

        withdrawals_from_retirement_accounts (dict[int, Money]): The
            total value of all withdrawals from retirement savings
            accounts over the year.
        withdrawals_from_other_accounts (dict[int, Money]): The total
            value of all withdrawals from other savings accounts (e.g.
            education or health accounts, if provided) over the year.
        gross_withdrawals (dict[int, Money]): The total amount withdrawn
            from all accounts.
        tax_withheld_on_withdrawals (dict[int, Money]): Taxes deducted
            at source on withdrawals from savings.
        net_withdrawals (dict[int, Money]): The total amount withdrawn
            from all accounts, net of withholding taxes.

        total_tax_withheld (dict[int, Money]): The total amount of tax
            owing for this year which was paid during this year (as
            opposed to being paid in the following year the next year).

            Note that this is not necessarily the same as the sum of
            other `tax_withheld_on_\\*` attributes, since the tax
            authority may require additional withholding taxes (or
            payment by installments) based on the person's overall
            circumstances.
        total_tax_owing (dict[int, Money]): The total amount of tax
            owing for this year (some of which may be paid in the
            following year). Does not include outstanding amounts which
            became owing but were not paid in the previous year.

        living_standard (dict[int, Money]): The total amount of money
            available for spending, net of taxes, contributions, debt
            payments, etc.
    """

    # pylint: disable=too-many-arguments
    # NOTE: Consider combining the various strategy objects into a dict
    # or something (although it's not clear how this benefits the code.)
    def __init__(
        self, people, assets, debts, scenario, contribution_strategy,
        withdrawal_strategy, contribution_trans_strategy,
        withdrawal_trans_strategy, debt_payment_strategy, tax_treatment
    ):
        """ Constructs an instance of class Forecast.

        Iteratively advances `people` and various accounts to the next
        year until all years of the `scenario` have been modelled.

        Args:
            people (Iterable[Person]): The people for whom a forecast
                is being generated.
            assets (Iterable[Account]): The assets of the people.
            debts (Iterable[Account]): The debts of the people.
            scenario (Scenario): Economic information for the forecast
                (e.g. inflation and stock market returns for each year)
            contribution_strategy (ContributionStrategy): A callable
                object that determines the gross contribution for a
                year. See the documentation for ContributionStrategy for
                acceptable args when calling this object.
            withdrawal_strategy (WithdrawalStrategy): A callable
                object that determines the amount to withdraw for a
                year. See the documentation for WithdrawalStrategy for
                acceptable args when calling this object.
            contribution_transaction_strategy (TransactionStrategy): A
                callable object that determines the schedule of
                transactions for any contributions during the year.
                See the documentation for TransactionStrategy for
                acceptable args when calling this object.
            withdrawal_transaction_strategy
                (WithdrawalTransactionStrategy):
                A callable object that determines the schedule of
                transactions for any contributions during the year.
                See the documentation for TransactionStrategy for
                acceptable args when calling this object.
            debt_payment_strategy (DebtPaymentStrategy): A callable
                object that determines the schedule of debt payments,
                including accelerated debt payments drawn from gross
                contributions. See the documentation for
                `DebtPaymentStrategy` for acceptable args when calling
                this object.
            tax_treatment (Tax): A callable object that determines the
                total amount of tax owing in a year. See documentation
                for `Tax` for acceptable args when calling this object.
        """
        # Store input values
        self.people = people
        self.assets = assets
        self.debts = debts
        self.scenario = scenario
        self.contribution_strategy = contribution_strategy
        self.withdrawal_strategy = withdrawal_strategy
        self.contribution_trans_strategy = contribution_trans_strategy
        self.withdrawal_trans_strategy = withdrawal_trans_strategy
        self.debt_payment_strategy = debt_payment_strategy
        self.tax_treatment = tax_treatment

        # Prepare output dicts:
        # Income
        self.gross_income = {}
        self.tax_withheld_on_income = {}
        self.net_income = {}

        # Gross contribution
        self.tax_carryover = {}
        self.other_carryover = {}
        self.asset_sale = {}
        self.gross_contributions = {}

        # Contribution reductions
        self.reduction_from_debt = {}
        self.reduction_from_tax = {}
        self.reduction_from_other = {}
        self.contribution_reductions = {}
        self.net_contributions = {}

        # Principal (and return on principal)
        self.principal = {}
        self.gross_return = {}
        self.tax_withheld_on_return = {}
        self.net_return = {}

        # Withdrawals
        self.withdrawals_for_retirement = {}
        self.withdrawals_for_tax = {}
        self.withdrawals_for_other = {}
        self.gross_withdrawals = {}
        self.tax_withheld_on_withdrawals = {}
        self.net_withdrawals = {}

        # Total tax
        self.total_tax_withheld = {}
        self.total_tax_owing = {}

        # Living standard
        self.living_standard = {}

        last_year = max(self.scenario)
        # Build the forecast year-by-year:
        for year in self.scenario:
            # Track flows of money into and out of savings:
            # This maps time values (in `when` format) to net flows:
            # `dict[Decimal, Money]`
            self._transactions = defaultdict(lambda: Money(0))
            # Do the actual work of forecasting:
            self.record_year(year)
            # Don't advance to the next year if this is the last one:
            if year < last_year:
                self.next_year(year)

    def next_year(self, year):
        """ Adds a year to the forecast. """
        for person in self.people:
            while person.this_year <= year:
                person.next_year()

        for account in self.assets.union(self.debts):
            while account.this_year <= year:
                account.next_year()

    def retirement_year(self):
        """ Determines the retirement year for the plannees.

        TODO: This approach forces `Forecast` to assume that all
        plannees retire at the same time, which is often inaccurate.
        We should use per-retiree retirement dates, meaning that this
        method should be removed and the calling code refactored.
        """
        return max(
            (
                person.retirement_date for person in self.people
                if person.retirement_date is not None
            ),
            default=None
        ).year

    def _add_transaction(
        self, transaction, when, account=None, account_transaction=None
    ):
        """ Helper method for `add_transaction`. """
        # Record to the dict:
        self._transactions[when] += transaction
        # Also add to the account, if passed:
        if account is not None:
            # Use the account_transaction amount, if passed,
            # otherwise fall back to `transaction`
            if account_transaction is None:
                account_transaction = transaction
            account.add_transaction(
                transaction,
                when=when)

    def add_transaction(
        self, transaction, when, account=None, account_transaction=None
    ):
        """ Records a transaction at a time that balances the books.
        
        Args:
            transaction (Money): The transaction to be added.
                Positive for inflows, negative for outflows.
            when (Decimal): The time at which the transaction occurs.
                Expressed as a value in [0,1].
            account (Account): An account to which the transaction
                is to be added. Optional.
            account_transaction (Money): If provided, this amount
                will be added to `Account` instead of `transaction`.

        Example:
            `f.add_transaction(Money(10), Decimal(0.5))`
            `# f._transactions = {0.5: Money(10)}`
            `f.add_transaction(Money(-10), Decimal(0.5))`
            `# f._transactions = {0.5: Money(0)}`
        """
        # Sanitize input:
        when = when_conv(when)

        # Inflows are easy: We can accept those any time:
        if transaction >= 0:
            self._add_transaction(
                transaction, when,
                account=account, account_transaction=account_transaction)
            return

        # Outflows are a bit trickier.
        # First, figure out how much money is available (i.e.
        # the excess of inflows over outflows to date):
        net_to_date = sum(
            self._transactions[t]
            for t in self._transactions if t <= when)
        # If we have enough to spare, we're done!
        if net_to_date >= transaction:
            self._add_transaction(
                transaction, when,
                account=account, account_transaction=account_transaction)
            return
        # Otherwise, iterate over the remaining transactions
        # until we find a time where we can afford the outflow:
        for t in sorted(self._transactions):
            # Ignore the times we summed above:
            if t <= when:
                continue
            # Otherwise, keep adding them up and checking to
            # see whether we have enough money yet:
            net_to_date += self._transactions[t]
            if net_to_date >= transaction:
                # We found it! Record the transaction and end
                self._add_transaction(
                    transaction, when,
                    account=account,
                    account_transaction=account_transaction)
                return

        # If we haven't found it yet, then there isn't enough
        # money available at _any_ time. We could reasonably do
        # one of two things:
        # (1) Use the originally-specified `when`
        # (2) Push the transaction to the end of the year
        # In this case, we'll use `when`
        self._add_transaction(
            transaction, when,
            account=account, account_transaction=account_transaction)

    def record_income(self, year):
        """ Records gross and net income, as well as taxes withheld. """
        # Determine gross/net income for the family:
        self.gross_income[year] = sum(
            (person.gross_income for person in self.people),
            Money(0))
        self.tax_withheld_on_income[year] = sum(
            (person.tax_withheld for person in self.people),
            Money(0))
        self.net_income[year] = sum(
            (person.net_income for person in self.people),
            Money(0))

    def record_gross_contribution(self, year):
        """ Records gross contributions for the year. """
        # Determine gross contributions:
        if year == self.scenario.initial_year:
            self.tax_carryover[year] = Money(0)
            self.other_carryover[year] = Money(0)
        else:
            # If more was withheld than was owed, we have a refund
            # (positive), otherwise we have an amount owing (negative)
            self.tax_carryover[year] = (
                self.total_tax_withheld[year - 1]
                - self.total_tax_owing[year - 1]
            )
            # TODO: Determine timing of tax refunds/payments:
            self.add_transaction(self.tax_carryover[year], 0)

            self.other_carryover[year] = Money(0)  # TODO #30
            self.add_transaction(self.other_carryover[year], 0)

        self.asset_sale[year] = Money(0)  # TODO #32
        # TODO: Determine timing of asset sale
        self.add_transaction(self.asset_sale[year], 0)

        # Prepare arguments for ContributionStrategy __call__ method:
        # (This determines gross contributions from income)
        retirement_year = self.retirement_year()
        if self.tax_carryover[year] > 0:
            refund = self.tax_carryover[year]
        else:
            refund = Money(0)
        other_contributions = (
            self.other_carryover[year] + self.asset_sale[year]
        )
        self.gross_contributions[year] = self.contribution_strategy(
            year=year,
            refund=refund,
            other_contributions=other_contributions,
            net_income=self.net_income[year],
            gross_income=self.gross_income[year],
            retirement_year=retirement_year
        )

        # Assume income is set aside for savings in equal amounts
        # at the start of each month:
        for i in range(12):
            self._transactions[Decimal(i)/12] += (
                self.gross_contributions[year]/12)

    def record_contribution_reductions(self, year):
        """ Records contribution reductions for the year.

        This method determines total debt payments and applies per-debt
        payments to debt accounts.
        """
        # Determine contribution reductions:
        # TODO: Include reduced contributions to pay for last year's
        # outstanding taxes?
        # NOTE: We'll add another reduction dict for childcare expenses
        # in a future version.
        # First determine miscellaneous other reductions (these take
        # priority because they're generally user-input):
        self.reduction_from_other[year] = Money(0)  # TODO
        # Assume we make `other` reductions at the end of the year:
        self._transactions[1] -= self.reduction_from_other[year]

        # Then determine reductions due to debt payments:
        # Start with gross debt payments:
        debt_payments = self.debt_payment_strategy(
            self.debts,
            self.gross_contributions[year] - self.reduction_from_other[year]
        )
        # Then determine what portion was drawn from savings:
        debt_payments_from_savings = {
            debt: debt.payment_from_savings(
                amount=debt_payments[debt],
                base=debt.inflows
            ) for debt in debt_payments
        }
        # Then reduce savings by that amount (simple, right?):
        self.reduction_from_debt[year] = sum(
            debt_payments_from_savings.values(),
            Money(0)
        )
        # Apply (gross) debt payment transactions
        for debt in debt_payments:
            debt.add_transaction(
                debt_payments[debt],
                self.debt_payment_strategy.timing
            )
            # Track the savings portion against net savings in/outflows:
            # (Currently we model all debt payments as lump sums
            # at a time given by the `DebtPaymentStrategy` class.)
            # TODO: Enable debt payments to be split up between multiple
            # timings:
            self._transactions[self.debt_payment_strategy.timing] -= (
                debt_payments_from_savings[debt])

        # Now determine the total reductions across all reduction dicts:
        self.contribution_reductions[year] = (
            self.reduction_from_debt[year] +
            self.reduction_from_other[year]
        )

        # If there's contribution room left, use it to pay for any taxes
        # outstanding:
        # TODO: Determine whether tax liability should be assessed first.
        # And should it always come 100% from savings? Should this be 
        # configurable behaviour (e.g. via a `reinvest_tax_refund` value
        # stored... somewhere)?
        if self.tax_carryover[year] < 0:
            available = (
                self.gross_contributions[year]
                - self.contribution_reductions[year]
            )
            reduction = min(-self.tax_carryover[year], available)
            self.reduction_from_tax[year] = max(reduction, Money(0))
            # Update contribution reductions:
            self.contribution_reductions[year] += self.reduction_from_tax[year]
            # Add the net transaction:
            # NOTE: In addition to the TODO comment above re: allowing for
            # tax amounts from savings to be configured, we should allow
            # tax _timing_ to be configurable (presumably via the `Tax` class
            # and its subclasses, likely with a corresponding setting)
            # Currently, we record it as owing on the first day of the year.
            self._transactions[0] += self.reduction_from_tax[year]
        else:
            self.reduction_from_tax[year] = Money(0)

    def record_net_contributions(self, year):
        """ Records net contributions.

        This method determines total net (i.e. actual) contributions and
        adds inflows to the appropriate accounts.
        """
        # Reductions can potentially exceed gross_contributions (e.g.
        # due to minimum debt payments or childcare expenses).
        # Ensure the net_contributions is not negative:
        self.net_contributions[year] = max(
            self.gross_contributions[year] -
            self.contribution_reductions[year],
            Money(0)
        )

        # Add inflow transactions to debts and accounts based on our
        # net contributions and debt payments:
        contributions = self.contribution_trans_strategy(
            self.net_contributions[year],
            self.assets
        )
        for account in contributions:
            account.add_transaction(
                contributions[account],
                self.contribution_trans_strategy.timing
            )

    def record_principal(self, year):
        """ Records principal balance for the year. """
        self.principal[year] = sum(
            (account.balance for account in self.assets),
            Money(0))

    def record_returns(self, year):
        """ Records gross and net returns, as well as tax withheld. """
        self.gross_return[year] = sum(
            (a.returns for a in self.assets),
            Money(0))
        # TODO: Figure out what to do with tax_withheld_on_return.
        # Right now there's no way to distinguish between tax withheld
        # in an account due to returns vs. due to withdrawals.
        # IDEA: Eliminate disctinction between tax withheld on returns
        # vs. withdrawals and only consider tax withheld on accounts?
        # This will generally be paid from the accounts themselves, so
        # it probably makes sense to consider it all together.
        self.tax_withheld_on_return[year] = Money(0)  # TODO
        self.net_return[year] = (
            self.gross_return[year] - self.tax_withheld_on_return[year]
        )

    def record_withdrawals(self, year):
        """ Records withdrawals for the year.

        Withdrawals are divided into retirement and other withdrawals.
        Taxes on withdrawals are determined to produce a figure for
        net withdrawals.
        """
        retirement_year = self.retirement_year()

        self.withdrawals_for_retirement[year] = (
            self.withdrawal_strategy(
                benefits=Money(0),
                net_income=self.net_income[year],
                gross_income=self.gross_income[year],
                principal=self.principal[year],
                retirement_year=retirement_year,
                year=year
            )
        )

        # If we have a tax balance to pay off, add that here.
        if self.tax_carryover[year] < 0:
            self.withdrawals_for_tax[year] = -(
                self.reduction_from_tax[year] + self.tax_carryover[year]
            )
        else:
            self.withdrawals_for_tax[year] = Money(0)

        self.withdrawals_for_other[year] = Money(0)  # TODO
        self.gross_withdrawals[year] = (
            self.withdrawals_for_retirement[year]
            + self.withdrawals_for_tax[year]
            + self.withdrawals_for_other[year]
        )

        self.tax_withheld_on_withdrawals[year] = sum(
            (account.tax_withheld for account in self.assets),
            Money(0)
        )
        # TODO: Lumping net withdrawals together doesn't seem very
        # useful. Consider splitting apart tax withholdings by
        # withdrawal type and finding net withdrawals independently.
        self.net_withdrawals[year] = (
            self.gross_withdrawals[year] -
            self.tax_withheld_on_withdrawals[year]
        )

    def record_total_tax(self, year):
        """ Records total tax withheld and payable in the year.

        TODO: Deal with tax owing but not withheld - arrange to pay this
        in the following year? Apply against investment balances? Draw
        a portion from income (i.e. as a living expense)?

        Note that in Canada, if more than $3000 or so of tax is owing
        but not withheld, the CRA will put you on an instalments plan,
        so you can't really defer your total tax liability into the next
        year.
        """
        self.total_tax_withheld[year] = (
            self.tax_withheld_on_income[year] +
            self.tax_withheld_on_return[year] +
            self.tax_withheld_on_withdrawals[year]
        )
        self.total_tax_owing[year] = self.tax_treatment(self.people, year)

    def record_living_standard(self, year):
        """ Records the living standard for each year.

        The living standard is the money available to spend after all
        taxes, debt repayments (other than debts included in living
        expenses), and savings are deducted.
        """
        # TODO: Check Excel spreadsheet for calculation of this.
        # As currently shown, this deducts all taxes owing from the
        # living standard - even if some of those taxes are attributable
        # to activity within a savings account (and not withdrawal/etc.
        # activity that funds the living standard)

        # Determine whether we are adding a tax refund to our living
        # standard or deducting a tax liability.
        if self.tax_carryover[year] >= 0:
            tax_refund = (
                self.tax_carryover[year] *
                (1 - self.contribution_strategy.refund_reinvestment_rate)
            )
            tax_bill = Money(0)
        else:
            tax_refund = Money(0)
            tax_bill = (
                -self.tax_carryover[year] - self.reduction_from_tax[year]
            )
        # Living standard is all inflows to personal (non-investment)
        # accounts (from employment, withdrawals, tax refunds, benefits,
        # etc.) minus any outflows for non-living-expense liabilities
        # (from savings, tax withholding or amounts payable, and other
        # non-living-expense items deducted from our savings rate).
        # NOTE: contribution_reductions can exceed gross_contributions,
        # in which case living_expenses will take a hit.
        self.living_standard[year] = (  # inflows
            self.gross_income[year]
            + self.gross_withdrawals[year]
            + tax_refund
        ) - (  # outflows
            self.total_tax_withheld[year]
            + self.net_contributions[year]
            + self.contribution_reductions[year]
            + tax_bill
        )

    def record_year(self, year):
        """ Stores high-level values across accounts for this year."""
        # NOTE: Order is important here. This method is only split into
        # its various sub-methods for readability - it really is just
        # one long chain of procedural logic.
        self.record_income(year)
        self.record_gross_contribution(year)
        self.record_contribution_reductions(year)
        self.record_net_contributions(year)
        self.record_principal(year)
        self.record_withdrawals(year)
        self.record_returns(year)
        self.record_total_tax(year)
        self.record_living_standard(year)
