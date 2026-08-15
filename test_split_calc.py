import unittest
from datetime import date

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

    def test_jcb_official_fee_upper_estimate(self):
        payments = simulate(100_000, 10, date(2026, 8, 1), "jcb")

        self.assertEqual(sum(p.amount for p in payments), 108_430)
        self.assertEqual(sum(p.principal for p in payments), 100_000)
        self.assertEqual(sum(p.fee for p in payments), 8_430)
        self.assertEqual([p.amount for p in payments], [10_843] * 10)
        self.assertEqual(payments[-1].balance, 0)

    def test_jcb_supports_each_installment_from_three_through_twenty_four(self):
        self.assertEqual(
            tuple(CARD_PLANS["jcb"].rates),
            (*range(3, 25), 30, 36, 42, 48, 54, 60),
        )

    def test_rejects_unknown_card(self):
        with self.assertRaisesRegex(ValueError, "カード会社"):
            simulate(10_000, 3, card="unknown")


if __name__ == "__main__":
    unittest.main()
