#!/usr/bin/env python3
"""クレジットカードの「あとから分割」月別支払いシミュレーター。"""

from __future__ import annotations

import argparse
import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_DOWN
from typing import Sequence


@dataclass(frozen=True)
class Rate:
    annual_rate: Decimal
    fee_per_100_yen: Decimal


@dataclass(frozen=True)
class Payment:
    number: int
    month: str
    amount: int
    principal: int
    fee: int
    balance: int


@dataclass(frozen=True)
class CardPlan:
    name: str
    rates: dict[int, Rate]
    note: str


# 2025年4月1日改定後の三井住友カード「あとから分割」手数料率。
RATES: dict[int, Rate] = {
    3: Rate(Decimal("14.70"), Decimal("2.46")),
    4: Rate(Decimal("15.64"), Decimal("3.28")),
    5: Rate(Decimal("16.25"), Decimal("4.10")),
    6: Rate(Decimal("16.68"), Decimal("4.92")),
    10: Rate(Decimal("17.51"), Decimal("8.20")),
    12: Rate(Decimal("17.69"), Decimal("9.84")),
    15: Rate(Decimal("17.84"), Decimal("12.30")),
    18: Rate(Decimal("17.90"), Decimal("14.76")),
    20: Rate(Decimal("17.91"), Decimal("16.40")),
    24: Rate(Decimal("17.88"), Decimal("19.68")),
    30: Rate(Decimal("17.79"), Decimal("24.60")),
    36: Rate(Decimal("17.65"), Decimal("29.52")),
    40: Rate(Decimal("17.55"), Decimal("32.80")),
    42: Rate(Decimal("17.50"), Decimal("34.44")),
    48: Rate(Decimal("17.35"), Decimal("39.36")),
    50: Rate(Decimal("17.29"), Decimal("41.00")),
    54: Rate(Decimal("17.19"), Decimal("44.28")),
    60: Rate(Decimal("17.03"), Decimal("49.20")),
}


JCB_INSTALLMENTS = (*range(3, 25), 30, 36, 42, 48, 54, 60)


def installment_coefficient(annual_rate: Decimal, installments: int) -> Decimal:
    """元利均等払いの割賦係数を小数点以下2桁で返す。"""
    monthly_rate = annual_rate / Decimal(1200)
    coefficient = (
        Decimal(installments)
        * monthly_rate
        / (Decimal(1) - (Decimal(1) + monthly_rate) ** -installments)
        - Decimal(1)
    ) * Decimal(100)
    return coefficient.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


# JCBが掲載する実質年率18.00%の場合の割賦係数。初回の日割計算前の上限目安。
JCB_RATES: dict[int, Rate] = {
    installments: Rate(
        Decimal("18.00"),
        installment_coefficient(Decimal("18.00"), installments),
    )
    for installments in JCB_INSTALLMENTS
}

CARD_PLANS: dict[str, CardPlan] = {
    "smbc": CardPlan(
        "三井住友カード",
        RATES,
        "定額分割方式（総額均等割）による表示です。繰り上げ返済時の精算額とは異なります。",
    ),
    "jcb": CardPlan(
        "JCB",
        JCB_RATES,
        "年率18.00%の割賦係数による上限目安です。初回の日割計算などにより実際の請求とは異なります。",
    ),
}


def add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def simulate(
    amount: int,
    installments: int,
    start_month: date | None = None,
    card: str = "smbc",
) -> list[Payment]:
    """月別支払予定を返す。start_month の翌月を第1回支払月とする。"""
    if amount < 1_000:
        raise ValueError("支払金額は1,000円以上で入力してください。")
    try:
        plan = CARD_PLANS[card]
    except KeyError as error:
        choices = ", ".join(CARD_PLANS)
        raise ValueError(f"カード会社は次から選んでください: {choices}") from error
    if installments not in plan.rates:
        choices = ", ".join(str(value) for value in plan.rates)
        raise ValueError(f"分割回数は次から選んでください: {choices}")

    start_month = start_month or date.today().replace(day=1)
    rate = plan.rates[installments]
    total_fee = int(
        (Decimal(amount) * rate.fee_per_100_yen / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_DOWN
        )
    )
    total = amount + total_fee
    regular_payment, first_remainder = divmod(total, installments)
    regular_principal, first_principal_remainder = divmod(amount, installments)

    balance = amount
    allocated_fee = 0
    result: list[Payment] = []
    for number in range(1, installments + 1):
        payment_amount = regular_payment + (first_remainder if number == 1 else 0)
        if card == "smbc":
            # 定額分割方式（総額均等割）。元金と確定済みの手数料を
            # 支払回数で均等に分け、端数は初回へ加える。
            principal = regular_principal + (
                first_principal_remainder if number == 1 else 0
            )
            monthly_fee = payment_amount - principal
        elif number == installments:
            monthly_fee = total_fee - allocated_fee
            principal = balance
            payment_amount = principal + monthly_fee
        else:
            monthly_fee = int(
                (Decimal(balance) * rate.annual_rate / Decimal(1200)).quantize(
                    Decimal("1"), rounding=ROUND_DOWN
                )
            )
            # 丸めの累積で公式総手数料を超えないようにする。
            monthly_fee = min(monthly_fee, total_fee - allocated_fee)
            principal = payment_amount - monthly_fee

        balance -= principal
        allocated_fee += monthly_fee
        payment_month = add_months(start_month, number)
        result.append(
            Payment(
                number,
                payment_month.strftime("%Y-%m"),
                payment_amount,
                principal,
                monthly_fee,
                balance,
            )
        )
    return result


def yen(value: int) -> str:
    return f"{value:,}円"


def print_result(
    amount: int,
    installments: int,
    payments: Sequence[Payment],
    card: str = "smbc",
) -> None:
    plan = CARD_PLANS[card]
    rate = plan.rates[installments]
    total_fee = sum(item.fee for item in payments)
    print(f"\n{plan.name} あとから分割シミュレーション")
    print(f"利用金額: {yen(amount)} / {installments}回 / 実質年率: {rate.annual_rate}%")
    print(f"手数料: {yen(total_fee)} / 支払総額: {yen(amount + total_fee)}\n")

    headers = ("回", "支払月", "支払金額", "元金", "手数料", "残元金")
    rows = [
        (str(p.number), p.month, yen(p.amount), yen(p.principal), yen(p.fee), yen(p.balance))
        for p in payments
    ]
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    print("  ".join(headers[i].rjust(widths[i]) for i in range(len(headers))))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(row[i].rjust(widths[i]) for i in range(len(row))))
    print(f"\n※{plan.note}")


def positive_integer(value: str) -> int:
    try:
        number = int(value.replace(",", ""))
    except ValueError as error:
        raise argparse.ArgumentTypeError("整数で入力してください。") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("1以上で入力してください。")
    return number


def parse_month(value: str) -> date:
    try:
        year_text, month_text = value.split("-", maxsplit=1)
        return date(int(year_text), int(month_text), 1)
    except (ValueError, TypeError) as error:
        raise argparse.ArgumentTypeError("YYYY-MM 形式で入力してください。") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="あとから分割の月別支払額を計算します。")
    parser.add_argument("amount", nargs="?", type=positive_integer, help="利用金額（円）")
    parser.add_argument("installments", nargs="?", type=positive_integer, help="分割回数")
    parser.add_argument(
        "--card",
        choices=CARD_PLANS,
        default="smbc",
        help="カード会社（既定: smbc）",
    )
    parser.add_argument("--start", type=parse_month, metavar="YYYY-MM", help="申込月（省略時は今月）")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        amount = args.amount or positive_integer(input("支払金額（円）: ").strip())
        installments = args.installments or positive_integer(input("分割回数: ").strip())
        payments = simulate(amount, installments, args.start, args.card)
    except (ValueError, argparse.ArgumentTypeError) as error:
        print(f"エラー: {error}")
        return 2
    print_result(amount, installments, payments, args.card)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
