import unittest
from contextlib import redirect_stdout
from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from split_calc import (
    CALCULATORS,
    CARD_PLANS,
    InterestFreeInstallmentCalculator,
    InstallmentCalculator,
    JcbInstallmentCalculator,
    OptimizationResult,
    Payment,
    PaymentPlan,
    Payoff,
    SavingEntry,
    SmbcInstallmentCalculator,
    display_width,
    main,
    optimize_payoffs,
    payment_plan_value,
    print_optimization,
    print_result,
    simulate,
)


class SimulateTest(unittest.TestCase):
    def test_each_card_uses_installment_calculator_interface(self):
        self.assertIsInstance(CALCULATORS["smbc"], SmbcInstallmentCalculator)
        self.assertIsInstance(CALCULATORS["jcb"], JcbInstallmentCalculator)
        self.assertIsInstance(
            CALCULATORS["interest-free"], InterestFreeInstallmentCalculator
        )
        self.assertTrue(
            all(
                isinstance(calculator, InstallmentCalculator)
                for calculator in CALCULATORS.values()
            )
        )

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

    def test_rejects_zero_jcb_annual_rate_instead_of_using_default(self):
        with self.assertRaisesRegex(ValueError, "7.92%～18.00%"):
            simulate(100_000, 10, card="jcb", annual_rate=Decimal("0"))

    def test_rejects_annual_rate_for_smbc(self):
        with self.assertRaisesRegex(ValueError, "JCBでのみ"):
            simulate(100_000, 10, annual_rate=Decimal("15.00"))

    def test_interest_free_supports_arbitrary_installments(self):
        payments = simulate(
            1_000_000, 180, date(2026, 8, 1), card="interest-free"
        )

        self.assertEqual(len(payments), 180)
        self.assertEqual(payments[0].month, "2026-09")
        self.assertEqual(payments[0].amount, 5_655)
        self.assertEqual(payments[1].amount, 5_555)
        self.assertEqual(sum(payment.principal for payment in payments), 1_000_000)
        self.assertEqual(sum(payment.fee for payment in payments), 0)
        self.assertEqual(payments[-1].balance, 0)


class OptimizePayoffsTest(unittest.TestCase):
    def test_selects_order_with_lowest_remaining_fees(self):
        plans = [
            PaymentPlan("高金利", 100, 2, date(2026, 8, 1)),
            PaymentPlan("低金利", 100, 2, date(2026, 8, 1)),
        ]
        schedules = {
            "high": [
                Payment(1, "2026-09", 70, 50, 20, 50),
                Payment(2, "2026-10", 60, 50, 10, 0),
            ],
            "low": [
                Payment(1, "2026-09", 55, 50, 5, 50),
                Payment(2, "2026-10", 52, 50, 2, 0),
            ],
        }

        with patch(
            "split_calc.simulate",
            side_effect=[schedules["high"], schedules["low"]],
        ):
            result = optimize_payoffs(plans, 50)

        self.assertEqual(result.order, ("高金利", "低金利"))
        self.assertEqual(result.baseline_fee, 37)
        self.assertEqual(result.optimized_fee, 27)
        self.assertEqual(result.saved_fee, 10)
        self.assertEqual(result.payoffs[0].name, "高金利")
        self.assertEqual(result.payoffs[0].month, "2026-09")
        self.assertEqual(result.payoffs[0].fund_before, 50)
        self.assertEqual(result.payoffs[0].fund_after, 0)
        self.assertEqual(result.payoffs[0].saving_month, 1)
        self.assertEqual(
            [(entry.number, entry.deposit, entry.withdrawal, entry.balance) for entry in result.saving_entries],
            [(1, 50, 0, 50), (None, 0, 50, 0), (2, 50, 0, 50)],
        )
        self.assertEqual(result.saving_entries[0].regular_payments, (70, 55))
        self.assertEqual(result.saving_entries[2].regular_payments, (0, 52))

    def test_prints_saving_balance_before_and_after_payoff(self):
        result = OptimizationResult(
            ("家電",),
            10_000,
            5_000,
            (Payoff("2027-04", "家電", 223_282, 240_000, 16_718, 8),),
            (
                SavingEntry(
                    8,
                    "2027-04",
                    "積立",
                    30_000,
                    0,
                    240_000,
                    (12_345,),
                ),
                SavingEntry(
                    None,
                    "2027-04",
                    "繰上返済（家電）",
                    0,
                    223_282,
                    16_718,
                    (0,),
                ),
            ),
            "2026-09",
        )
        output = StringIO()

        with redirect_stdout(output):
            print_optimization(result, 30_000)

        lines = output.getvalue().splitlines()
        header, separator, saving_row, payoff_row = lines[7:11]
        self.assertEqual(display_width(header), display_width(separator))
        self.assertEqual(display_width(saving_row), display_width(separator))
        self.assertEqual(display_width(payoff_row), display_width(separator))
        self.assertIn("返済", header)
        self.assertIn("積立", header)
        self.assertIn("繰上返済", header)
        self.assertLess(header.index("返済"), header.index("積立"))
        self.assertTrue(header.lstrip().startswith("回"))
        self.assertTrue(saving_row.lstrip().startswith("8"))
        self.assertIn("積立", saving_row)
        self.assertIn("繰上返済（家電）", payoff_row)
        self.assertIn("***********", saving_row)
        self.assertIn("***********", payoff_row)
        self.assertIn("223,282円", payoff_row)
        self.assertIn("16,718円", payoff_row)
        self.assertEqual(saving_row.count("12,345円"), 1)
        self.assertIn("積立開始月: 2026-09", output.getvalue())

    def test_saving_can_start_after_regular_payments_begin(self):
        plan = PaymentPlan("家電", 100, 3, date(2026, 8, 1))
        schedule = [
            Payment(1, "2026-09", 30, 20, 10, 80),
            Payment(2, "2026-10", 28, 20, 8, 60),
            Payment(3, "2026-11", 66, 60, 6, 0),
        ]

        with patch("split_calc.simulate", return_value=schedule):
            result = optimize_payoffs(
                [plan], 60, saving_start=date(2026, 10, 1)
            )

        self.assertEqual(result.saving_start_month, "2026-10")
        self.assertEqual(result.optimized_fee, 18)
        self.assertEqual(
            [(entry.number, entry.month) for entry in result.saving_entries],
            [(None, "2026-09"), (1, "2026-10"), (None, "2026-10")],
        )
        self.assertEqual(result.saving_entries[0].regular_payments, (30,))
        self.assertEqual(result.saving_entries[1].regular_payments, (28,))

    def test_fixed_monthly_total_reduces_deposit_by_regular_payments(self):
        plan = PaymentPlan("家電", 100, 3, date(2026, 8, 1))
        schedule = [
            Payment(1, "2026-09", 30, 20, 10, 80),
            Payment(2, "2026-10", 28, 20, 8, 60),
            Payment(3, "2026-11", 66, 60, 6, 0),
        ]

        with patch("split_calc.simulate", return_value=schedule):
            result = optimize_payoffs([plan], 100, fixed_monthly_total=True)

        saving_entries = [
            entry for entry in result.saving_entries if entry.description == "積立"
        ]
        self.assertEqual(
            [
                (sum(entry.regular_payments), entry.deposit)
                for entry in saving_entries
            ],
            [(30, 70), (28, 72)],
        )
        self.assertTrue(
            all(sum(entry.regular_payments) + entry.deposit == 100 for entry in saving_entries)
        )

    def test_fixed_monthly_total_rejects_unavoidable_excess_payment(self):
        plan = PaymentPlan("家電", 100, 2, date(2026, 8, 1))
        schedule = [Payment(1, "2026-09", 70, 50, 20, 50)]

        with patch("split_calc.simulate", return_value=schedule):
            with self.assertRaisesRegex(ValueError, "2026-09"):
                optimize_payoffs([plan], 60, fixed_monthly_total=True)

    def test_rejects_duplicate_names(self):
        plans = [
            PaymentPlan("同じ", 10_000, 3, date(2026, 8, 1)),
            PaymentPlan("同じ", 20_000, 3, date(2026, 8, 1)),
        ]

        with self.assertRaisesRegex(ValueError, "重複"):
            optimize_payoffs(plans, 10_000)

    def test_branch_and_bound_supports_more_than_eight_payments(self):
        plans = [
            PaymentPlan(f"支払い{index}", 1_000, 3, date(2026, 8, 1))
            for index in range(9)
        ]
        schedule = [Payment(1, "2026-09", 1_000, 1_000, 0, 0)]

        with patch("split_calc.simulate", return_value=schedule):
            result = optimize_payoffs(plans, 9_000)

        self.assertEqual(result.order, tuple(plan.name for plan in plans))
        self.assertEqual(result.optimized_fee, 0)
        self.assertEqual(result.payoffs, ())

    def test_rejects_more_than_twelve_payments(self):
        plans = [
            PaymentPlan(f"支払い{index}", 1_000, 3, date(2026, 8, 1))
            for index in range(13)
        ]

        with self.assertRaisesRegex(ValueError, "12件まで"):
            optimize_payoffs(plans, 1_000)

    def test_parses_repeated_payment_option_format(self):
        plan = payment_plan_value("買い物:jcb:100000:10:18.00:2026-08")

        self.assertEqual(plan.name, "買い物")
        self.assertEqual(plan.card, "jcb")
        self.assertEqual(plan.amount, 100_000)
        self.assertEqual(plan.installments, 10)
        self.assertEqual(plan.annual_rate, Decimal("18.00"))
        self.assertEqual(plan.start_month, date(2026, 8, 1))

    def test_parses_interest_free_payment_with_arbitrary_installments(self):
        plan = payment_plan_value(
            "奨学金:interest-free:2400000:180::2026-08"
        )

        self.assertEqual(plan.card, "interest-free")
        self.assertEqual(plan.installments, 180)
        self.assertIsNone(plan.annual_rate)


class MainTest(unittest.TestCase):
    def test_fixed_monthly_total_option_is_passed_to_optimizer(self):
        result = OptimizationResult(("家電",), 1_000, 500, ())

        with (
            patch("split_calc.optimize_payoffs", return_value=result) as optimize_mock,
            patch("split_calc.print_optimization") as print_mock,
        ):
            exit_code = main(
                [
                    "--payment",
                    "家電:smbc:10000:3::2026-08",
                    "--monthly-saving",
                    "10000",
                    "--fixed-monthly-total",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertTrue(optimize_mock.call_args.kwargs["fixed_monthly_total"])
        self.assertTrue(print_mock.call_args.kwargs["fixed_monthly_total"])

    def test_result_columns_have_equal_display_widths(self):
        payments = simulate(650_000, 60, date(2026, 8, 1))
        output = StringIO()

        with redirect_stdout(output):
            print_result(650_000, 60, payments)

        lines = output.getvalue().splitlines()
        header, separator, first_row = lines[5:8]
        table_width = display_width(separator)
        self.assertEqual(display_width(header), table_width)
        self.assertEqual(display_width(first_row), table_width)

    def test_card_and_jcb_annual_rate_can_be_entered_interactively(self):
        output = StringIO()
        with (
            patch(
                "builtins.input",
                side_effect=["100000", "10", "jcb", "18.00"],
            ),
            patch("split_calc.simulate", return_value=[]) as simulate_mock,
            patch("split_calc.print_result") as print_result_mock,
            redirect_stdout(output),
        ):
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        simulate_mock.assert_called_once_with(
            100_000, 10, None, "jcb", Decimal("18.00")
        )
        print_result_mock.assert_called_once_with(
            100_000, 10, [], "jcb", Decimal("18.00")
        )

    def test_interactive_card_defaults_to_smbc_on_empty_input(self):
        with (
            patch("builtins.input", side_effect=["10000", "3", ""]),
            patch("split_calc.simulate", return_value=[]) as simulate_mock,
            patch("split_calc.print_result"),
        ):
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        simulate_mock.assert_called_once_with(10_000, 3, None, "smbc", None)

    def test_rejects_unknown_interactive_card(self):
        output = StringIO()
        with (
            patch("builtins.input", side_effect=["10000", "3", "unknown"]),
            redirect_stdout(output),
        ):
            exit_code = main([])

        self.assertEqual(exit_code, 2)
        self.assertEqual(
            output.getvalue(),
            "エラー: カード会社は次から選んでください: "
            "smbc, jcb, interest-free\n",
        )

    def test_interactive_jcb_annual_rate_defaults_on_empty_input(self):
        with (
            patch("builtins.input", side_effect=["100000", "10", "jcb", ""]),
            patch("split_calc.simulate", return_value=[]) as simulate_mock,
            patch("split_calc.print_result"),
        ):
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        simulate_mock.assert_called_once_with(
            100_000, 10, None, "jcb", Decimal("15.00")
        )

    def test_payoff_optimization_can_be_entered_interactively(self):
        result = OptimizationResult(("家電", "家具"), 10_000, 5_000, ())
        output = StringIO()
        with (
            patch(
                "builtins.input",
                side_effect=[
                    "30000",
                    "2026-07",
                    "",
                    "jcb",
                    "18.00",
                    "家電",
                    "300000",
                    "24",
                    "2026-08",
                    "y",
                    "y",
                    "",
                    "",
                    "家具",
                    "200000",
                    "20",
                    "2026-08",
                    "y",
                    "n",
                ],
            ),
            patch("split_calc.optimize_payoffs", return_value=result) as optimize_mock,
            patch("split_calc.print_optimization") as print_mock,
            redirect_stdout(output),
        ):
            exit_code = main(["--optimize"])

        self.assertEqual(exit_code, 0)
        plans = optimize_mock.call_args.args[0]
        self.assertEqual(optimize_mock.call_args.args[1], 30_000)
        self.assertEqual(optimize_mock.call_args.args[2], date(2026, 7, 1))
        self.assertEqual(
            plans,
            [
                PaymentPlan(
                    "家電",
                    300_000,
                    24,
                    date(2026, 8, 1),
                    "jcb",
                    Decimal("18.00"),
                ),
                PaymentPlan("家具", 200_000, 20, date(2026, 8, 1)),
            ],
        )
        print_mock.assert_called_once_with(result, 30_000)
        self.assertIn(
            "\n--payment '家電:jcb:300000:24:18.00:2026-08'\n\n",
            output.getvalue(),
        )
        self.assertIn(
            "\n--payment '家具:smbc:200000:20::2026-08'\n\n",
            output.getvalue(),
        )

    def test_invalid_interactive_value_is_retried_immediately(self):
        result = OptimizationResult(("家具",), 1_000, 500, ())
        output = StringIO()
        with (
            patch(
                "builtins.input",
                side_effect=[
                    "0",
                    "30000",
                    "invalid",
                    "2026-07",
                    "",
                    "invalid",
                    "",
                    "家具",
                    "999",
                    "200000",
                    "7",
                    "20",
                    "invalid",
                    "2026-08",
                    "maybe",
                    "y",
                    "",
                ],
            ),
            patch("split_calc.optimize_payoffs", return_value=result),
            patch("split_calc.print_optimization"),
            redirect_stdout(output),
        ):
            exit_code = main(["--optimize"])

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("エラー: 1以上で入力してください。", text)
        self.assertIn("エラー: カード会社は次から選んでください", text)
        self.assertIn("エラー: 支払金額は1,000円以上", text)
        self.assertIn("エラー: 分割回数は次から選んでください", text)
        self.assertIn("エラー: YYYY-MM 形式で入力してください。", text)
        self.assertIn("エラー: y または n で入力してください。", text)

    def test_payment_argument_can_shorten_interactive_input(self):
        result = OptimizationResult(("家電",), 10_000, 5_000, ())
        output = StringIO()
        with (
            patch(
                "builtins.input",
                side_effect=[
                    "30000",
                    "2026-07",
                    "invalid",
                    "家電:jcb:300000:24:18.00:2026-08",
                    "y",
                    "n",
                ],
            ),
            patch("split_calc.optimize_payoffs", return_value=result) as optimize_mock,
            patch("split_calc.print_optimization"),
            redirect_stdout(output),
        ):
            exit_code = main(["--optimize"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            optimize_mock.call_args.args,
            (
                [
                    PaymentPlan(
                        "家電",
                        300_000,
                        24,
                        date(2026, 8, 1),
                        "jcb",
                        Decimal("18.00"),
                    )
                ],
                30_000,
                date(2026, 7, 1),
            ),
        )
        self.assertIn("エラー: 支払いは", output.getvalue())

    def test_unconfirmed_payment_can_be_discarded_before_calculation(self):
        result = OptimizationResult(("家電",), 10_000, 5_000, ())
        output = StringIO()
        with (
            patch(
                "builtins.input",
                side_effect=[
                    "30000",
                    "2026-07",
                    "家電:jcb:300000:24:18.00:2026-08",
                    "y",
                    "y",
                    "家具:smbc:200000:20::2026-08",
                    "n",
                    "y",
                ],
            ),
            patch("split_calc.optimize_payoffs", return_value=result) as optimize_mock,
            patch("split_calc.print_optimization"),
            redirect_stdout(output),
        ):
            exit_code = main(["--optimize"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            optimize_mock.call_args.args,
            (
                [
                    PaymentPlan(
                        "家電",
                        300_000,
                        24,
                        date(2026, 8, 1),
                        "jcb",
                        Decimal("18.00"),
                    )
                ],
                30_000,
                date(2026, 7, 1),
            ),
        )
        self.assertNotIn(
            "--payment '家具:smbc:200000:20::2026-08'",
            output.getvalue(),
        )

    def test_keyboard_interrupt_exits_without_traceback(self):
        output = StringIO()
        with patch("builtins.input", side_effect=KeyboardInterrupt), redirect_stdout(output):
            exit_code = main(["--card", "jcb"])

        self.assertEqual(exit_code, 130)
        self.assertEqual(output.getvalue(), "\n中断しました。\n")

    def test_end_of_input_returns_input_error(self):
        output = StringIO()
        with patch("builtins.input", side_effect=EOFError), redirect_stdout(output):
            exit_code = main(["--card", "jcb"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(output.getvalue(), "\nエラー: 入力が終了しました。\n")


if __name__ == "__main__":
    unittest.main()
