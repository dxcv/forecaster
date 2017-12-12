""" Unit tests for `Forecast`. """

import unittest
from decimal import Decimal
import context  # pylint: disable=unused-import
from forecaster.ledger import Money
from forecaster.person import Person
from forecaster.accounts import Account, Debt
from forecaster.scenario import Scenario
from forecaster.strategy import ContributionStrategy, WithdrawalStrategy, \
    TransactionStrategy, AllocationStrategy, DebtPaymentStrategy
from forecaster.tax import Tax
from forecaster.forecast import Forecast
from forecaster.forecaster import Forecaster  # Import for convenience
from tests.test_helper import type_check


class TestForecast(unittest.TestCase):
    """ Tests Forecast. """

    def test_basic(self):
        """ Test with one account, one debt, and constant Scenario.

        For simplicity, this Scenario extends over 4 years: an initial
        year, a second year, a retirement year, and a final year.
        There is no inflation in this example.
        """
        initial_year = 2000
        scenario = Scenario(
            initial_year=initial_year,
            num_years=4,
            inflation=Decimal(0),  # No inflation
            stock_return=Decimal(2),  # 200% growth in stocks
            bond_return=Decimal(0),  # 0% growth in bonds
            other_return=0,  # No growth in other assets
            management_fees=Decimal(0),  # TODO: Refactor this attribute
        )
        tax = Tax(
            {
                initial_year: {
                    # 0% tax from $0 to $50,000
                    Decimal(0): Decimal(0),
                    # 50% bracket on income over $50,000
                    Decimal(50000): Decimal('0.5')
                }
            },
            personal_deduction={initial_year: Decimal(0)},
            credit_rate={initial_year: 0.5},
            inflation_adjust=scenario.inflation_adjust
        )
        contribution_strategy = ContributionStrategy(
            strategy=ContributionStrategy.strategy_const_contribution,
            base_amount=Money('50000'),
            rate=Decimal(0),
            refund_reinvestment_rate=1,
            inflation_adjust=scenario.inflation_adjust
        )
        withdrawal_strategy = WithdrawalStrategy(
            strategy=WithdrawalStrategy.strategy_const_withdrawal,
            base_amount=Money('50000'),
            timing='end',
            income_adjusted=False,
            inflation_adjust=scenario.inflation_adjust
        )
        contribution_trans_strategy = TransactionStrategy(
            strategy=TransactionStrategy.strategy_ordered,
            weights={'Account': 1},
            timing='end'
        )
        withdrawal_trans_strategy = TransactionStrategy(
            strategy=TransactionStrategy.strategy_ordered,
            weights={'Account': 1},
            timing='end'
        )
        # Constant 50-50 split between stocks and bonds
        # (100% growth of 50-50 portfolio):
        allocation_strategy = AllocationStrategy(
            strategy=AllocationStrategy.strategy_n_minus_age,
            min_equity=Decimal(0.5),
            max_equity=Decimal(0.5),
            target=Decimal(0.5),
            standard_retirement_age=65,
            risk_transition_period=20,
            adjust_for_retirement_plan=True
        )
        debt_payment_strategy = DebtPaymentStrategy(
            strategy=DebtPaymentStrategy.strategy_avalanche,
            timing='end'
        )
        person = Person(
            initial_year, 'Test', 1980,
            retirement_date=2002,
            gross_income=Money(100000),
            raise_rate=Decimal(0.5),
            tax_treatment=tax
        )
        account = Account(
            person,
            balance=1000,
            # 100% growth rate (50-50 portfolio with 200% growth of
            # stocks and 0% growth of bonds)
            rate=allocation_strategy.rate_function(person, scenario),
            nper=1
        )
        debt = Debt(
            person,
            balance=-1000,
            rate=1,  # 100% interest rate
            minimum_payment=Money(100),
            reduction_rate=1,
            accelerate_payment=True
        )

        forecast = Forecast(
            {person}, {account}, {debt}, scenario, contribution_strategy,
            withdrawal_strategy, contribution_trans_strategy,
            withdrawal_trans_strategy,
            debt_payment_strategy, tax
        )

        # Calculate the expected results for the values of principal
        # importance in each year and test them here.
        # Year 1:
        year = initial_year
        # Gross income: $100,000, taxes: $25,000
        self.assertEqual(forecast.net_income[year], Money(75000))
        # Gross contribution: $50,000, debt payments: $2000 (this will
        # pay off the debt's $1000 principal and $1000 interest)
        self.assertEqual(forecast.net_contributions[year],
                         Money(48000))
        # Account initial balance: $1000
        self.assertEqual(forecast.principal[year], Money(1000))
        # Growth: 100%
        # NOTE: We should implement growth based on allocation (in this
        # case 100% for stocks, 50% for bonds, portfolio split evenly),
        # which would yield $750. No taxes/etc.
        self.assertEqual(forecast.net_return[year], Money(1000))
        # No withdrawals
        self.assertEqual(forecast.net_withdrawals[year], Money(0))
        # Taxable income: $100,000 + $1000. All income over $50,000 is
        # taxable at 50%, for a total of $25500
        self.assertEqual(forecast.total_tax_owing[year],
                         Money(25500))
        # Living standard: $100,000 - $25,500 - $50,000 = $24,500
        self.assertEqual(forecast.living_standard[year], Money(24500))

        # Year 2:
        year += 1
        # Gross income: $150,000 (50% raise), taxes: $50,000
        self.assertEqual(forecast.net_income[year], Money(100000))
        # Gross contribution: $50,000, debt payments: $0
        self.assertEqual(forecast.net_contributions[year],
                         Money(50000))
        # Account initial balance: $50000 ($48000 contribution, plus
        # $1000 initial balance and $1000 return last year)
        self.assertEqual(forecast.principal[year], Money(50000))
        # Growth: 100%
        # NOTE: We should set growth based on allocation (see above)
        self.assertEqual(forecast.net_return[year], Money(50000))
        # No withdrawals - retirement is next year
        self.assertEqual(forecast.net_withdrawals[year], Money(0))
        # Taxable income: $150,000 + $50000. All income over $50,000 is
        # taxable at 50%, for a total of $75000
        self.assertEqual(forecast.total_tax_owing[year],
                         Money(75000))
        # Living standard: $150,000 - $75000 - $50,000 = $25,000
        # TODO: Review Excel sheet; the living standard formula needs
        # to be updated so that all taxes owing aren't held against
        # it. (Any taxes paid out of accounts shouldn't be - perhaps
        # only deduct taxes withheld?)
        self.assertEqual(forecast.living_standard[year], Money(25000))

        # Year 3:
        year += 1
        # Gross income: $225,000 (50% raise), taxes: $87,500
        self.assertEqual(forecast.net_income[year], Money(137500))
        # Gross contribution: $50,000, debt payments: $0
        self.assertEqual(forecast.net_contributions[year],
                         Money(50000))
        # Account initial balance: $150000 ($50000 contribution, plus
        # $50000 initial balance and $50000 return last year)
        self.assertEqual(forecast.principal[year], Money(150000))
        # Growth: 100%
        # NOTE: We should set growth based on allocation (see above)
        self.assertEqual(forecast.net_return[year], Money(150000))
        # No withdrawals - retirement is this year, so withdrawals start
        # next year.
        self.assertEqual(forecast.net_withdrawals[year], Money(0))
        # Taxable income: $225000 + $150000. All income over $50,000 is
        # taxable at 50%, for a total of $162500
        self.assertEqual(forecast.total_tax_owing[year],
                         Money(162500))
        # Living standard: $225,000 - $162,500 - $50,000 = $12,500
        # TODO: Review Excel sheet; the living standard formula needs
        # to be updated so that all taxes owing aren't held against
        # it. (Any taxes paid out of accounts shouldn't be - perhaps
        # only deduct taxes withheld?)
        self.assertEqual(forecast.living_standard[year], Money(12500))

        # Year 4:
        year += 1
        # Gross income: $0 (retired), taxes: $0
        self.assertEqual(forecast.net_income[year], Money(0))
        # Gross contribution: $0, debt payments: $0
        self.assertEqual(forecast.net_contributions[year],
                         Money(0))
        # Account initial balance: $350000 ($50000 contribution, plus
        # $150000 initial balance and $150000 return last year)
        self.assertEqual(forecast.principal[year], Money(350000))
        # Growth: 100%
        # NOTE: We should set growth based on allocation (see above)
        self.assertEqual(forecast.net_return[year], Money(350000))
        # $50,000 withdrawal
        self.assertEqual(forecast.net_withdrawals[year], Money(50000))
        # Taxable income: $350000. All income over $50,000 is
        # taxable at 50%, for a total of $150,000
        self.assertEqual(forecast.total_tax_owing[year],
                         Money(150000))
        # Living standard: $0 + $50000 - $150000 = -$100,000
        # TODO: Review Excel sheet; the living standard formula needs
        # to be updated so that all taxes owing aren't held against
        # it. (Any taxes paid out of accounts shouldn't be - perhaps
        # only deduct taxes withheld?)
        self.assertEqual(forecast.living_standard[year], Money(-100000))

    def test_types(self):
        """ Tests types of objects in Forecast attribute dicts. """
        # Use Forecaster to build a Forecast easily:
        forecaster = Forecaster()
        forecaster.add_asset(owner=forecaster.person1)
        forecaster.add_debt(owner=forecaster.person1)
        forecast = forecaster.forecast()

        self.assertTrue(
            type_check(forecast.asset_sale, {int: Money}))
        self.assertTrue(
            type_check(forecast.carryover, {int: Money}))
        self.assertTrue(
            type_check(forecast.contribution_reductions, {int: Money}))
        self.assertTrue(
            type_check(forecast.gross_contributions, {int: Money}))
        self.assertTrue(
            type_check(forecast.gross_income, {int: Money}))
        self.assertTrue(
            type_check(forecast.gross_return, {int: Money}))
        self.assertTrue(
            type_check(forecast.gross_withdrawals, {int: Money}))
        self.assertTrue(
            type_check(forecast.living_standard, {int: Money}))
        self.assertTrue(
            type_check(forecast.net_contributions, {int: Money}))
        self.assertTrue(
            type_check(forecast.net_income, {int: Money}))
        self.assertTrue(
            type_check(forecast.net_return, {int: Money}))
        self.assertTrue(
            type_check(forecast.net_withdrawals, {int: Money}))
        self.assertTrue(
            type_check(forecast.principal, {int: Money}))
        self.assertTrue(
            type_check(forecast.reduction_from_debt, {int: Money}))
        self.assertTrue(
            type_check(forecast.reduction_from_other, {int: Money}))
        self.assertTrue(
            type_check(forecast.refund, {int: Money}))
        self.assertTrue(
            type_check(forecast.tax_withheld_on_return, {int: Money}))
        self.assertTrue(
            type_check(forecast.tax_withheld_on_withdrawals, {int: Money}))
        self.assertTrue(
            type_check(forecast.taxes_withheld_on_income, {int: Money}))
        self.assertTrue(
            type_check(forecast.total_tax_owing, {int: Money}))
        self.assertTrue(
            type_check(forecast.total_tax_withheld, {int: Money}))
        self.assertTrue(
            type_check(forecast.withdrawals_for_other, {int: Money}))
        self.assertTrue(
            type_check(
                forecast.withdrawals_for_retirement, {int: Money}))

if __name__ == '__main__':
    unittest.main()