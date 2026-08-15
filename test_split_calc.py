import unittest
from datetime import date
from decimal import Decimal

from split_calc import CARD_PLANS, simulate


class SimulateTest(unittest.TestCase):
    def test_official_60000_yen_three_installment_example(self):
        payments = simulate(60_000, 3, date(2026, 8, 1))

        self.assertEqual(sum(p.amount for p in payments), 61_476)
        self.assertEqual(sum(p.principal for p in payments), 60_000)
        self.assertEqual(sum(p.fee for p in payments), 1_476)
        self.assertEqual([p.amount for p in payments], [20_492] * 3)
        self.assertEqual([p.month for p in payments], ["2026-09", "2026-10", "2026-11"])
        self.assertEqual(payments[-1].balance, 0)

    def test_payment_remainder_is_added_to_first_payment(self):
        payments = simulate(10_001, 3, date(2026, 12, 1))

        self.assertGreaterEqual(payments[0].amount, payments[1].amount)
        self.assertEqual(payments[1].amount, payments[2].amount)
        self.assertEqual(sum(p.principal for p in payments), 10_001)
        self.assertEqual(payments[0].month, "2027-01")

    def test_smbc_uses_equal_total_installments(self):
        payments = simulate(122_970, 3, date(2026, 8, 1))

        self.assertEqual(sum(p.fee for p in payments), 3_025)
        self.assertEqual([p.amount for p in payments], [41_999, 41_998, 41_998])
        self.assertEqual([p.principal for p in payments], [40_990, 40_990, 40_990])
        self.assertEqual([p.fee for p in payments], [1_009, 1_008, 1_008])
        self.assertEqual([p.balance for p in payments], [81_980, 40_990, 0])

    def test_rejects_amount_below_service_minimum(self):
        with self.assertRaisesRegex(ValueError, "1,000円以上"):
            simulate(999, 3)

    def test_rejects_unsupported_installment_count(self):
        with self.assertRaisesRegex(ValueError, "分割回数"):
            simulate(10_000, 7)

    def test_jcb_official_ten_installment_example(self):
        payments = simulate(
            100_000, 10, date(2026, 8, 1), "jcb", Decimal("18.00")
        )

        self.assertEqual(sum(p.amount for p in payments), 108_211)
        self.assertEqual(sum(p.principal for p in payments), 100_000)
        self.assertEqual(sum(p.fee for p in payments), 8_211)
        self.assertEqual(payments[0].amount, 10_625)
        self.assertEqual([p.amount for p in payments[1:9]], [10_843] * 8)
        self.assertEqual(payments[-1].amount, 10_842)
        self.assertEqual(payments[-1].balance, 0)

    def test_jcb_sixty_installment_actual_schedule(self):
        payments = simulate(
            502_700, 60, date(2026, 8, 1), "jcb", Decimal("18.00")
        )

        self.assertEqual(
            [(p.amount, p.fee, p.balance) for p in payments[:11]],
            [
                (11_669, 6_445, 497_476),
                (12_764, 7_462, 492_174),
                (12_764, 7_382, 486_792),
                (12_764, 7_301, 481_329),
                (12_764, 7_219, 475_784),
                (12_764, 7_136, 470_156),
                (12_764, 7_052, 464_444),
                (12_764, 6_966, 458_646),
                (12_764, 6_879, 452_761),
                (12_764, 6_791, 446_788),
                (12_764, 6_701, 440_725),
            ],
        )

    def test_jcb_supports_each_installment_from_three_through_twenty_four(self):
        self.assertEqual(
            tuple(CARD_PLANS["jcb"].rates),
            (*range(3, 25), 30, 36, 42, 48, 54, 60),
        )

    def test_rejects_unknown_card(self):
        with self.assertRaisesRegex(ValueError, "カード会社"):
            simulate(10_000, 3, card="unknown")

    def test_jcb_defaults_to_fifteen_percent(self):
        payments = simulate(100_000, 10, date(2026, 8, 1), "jcb")

        self.assertEqual(payments[0].amount, 10_518)
        self.assertEqual(payments[0].fee, 1_068)
        self.assertEqual(payments[1].amount, 10_700)

    def test_rejects_jcb_annual_rate_outside_supported_range(self):
        with self.assertRaisesRegex(ValueError, "7.92%～18.00%"):
            simulate(100_000, 10, card="jcb", annual_rate=Decimal("18.01"))

    def test_rejects_annual_rate_for_smbc(self):
        with self.assertRaisesRegex(ValueError, "JCBでのみ"):
            simulate(100_000, 10, annual_rate=Decimal("15.00"))


if __name__ == "__main__":
    unittest.main()
