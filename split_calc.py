#!/usr/bin/env python3
"""クレジットカードの「あとから分割」月別支払いシミュレーター。"""

from __future__ import annotations

import argparse
import calendar
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_DOWN
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
    default_annual_rate: Decimal | None = None


SMBC_CARD = "smbc"
JCB_CARD = "jcb"
DEFAULT_CARD = SMBC_CARD


# 2025年4月1日改定後の三井住友カード「あとから分割」手数料率。
SMBC_RATES: dict[int, Rate] = {
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


JCB_DEFAULT_ANNUAL_RATE = Decimal("15.00")
JCB_MIN_ANNUAL_RATE = Decimal("7.92")
JCB_MAX_ANNUAL_RATE = Decimal("18.00")


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


# JCBの既定実質年率の場合の割賦係数。初回の日割計算前の上限目安。
JCB_RATES: dict[int, Rate] = {
    installments: Rate(
        JCB_DEFAULT_ANNUAL_RATE,
        installment_coefficient(JCB_DEFAULT_ANNUAL_RATE, installments),
    )
    for installments in (*range(3, 25), 30, 36, 42, 48, 54, 60)
}

# JCB公式返済シミュレーターの月額算出では、60回払いについて
# 公開割賦係数52.36%の上限額より1bp低い係数相当の端数調整が入る。
JCB_PAYMENT_COEFFICIENT_OVERRIDES: dict[int, Decimal] = {
    60: Decimal("52.35"),
}

CARD_PLANS: dict[str, CardPlan] = {
    SMBC_CARD: CardPlan(
        "三井住友カード",
        SMBC_RATES,
        "定額分割方式（総額均等割）による表示です。繰り上げ返済時の精算額とは異なります。",
    ),
    JCB_CARD: CardPlan(
        "JCB",
        JCB_RATES,
        "指定年率、15日締め翌月10日払いとして計算しています。実際の請求とは異なる場合があります。",
        default_annual_rate=JCB_DEFAULT_ANNUAL_RATE,
    ),
}


class InstallmentCalculator(ABC):
    """カード会社ごとの分割払い計算ロジックが実装するインターフェース。"""

    def __init__(self, plan: CardPlan) -> None:
        self.plan = plan

    def calculate(
        self,
        amount: int,
        installments: int,
        start_month: date,
        annual_rate: Decimal | None = None,
    ) -> list[Payment]:
        """入力を検証し、カード会社固有の月別支払予定を返す。"""
        if installments not in self.plan.rates:
            choices = ", ".join(str(value) for value in self.plan.rates)
            raise ValueError(f"分割回数は次から選んでください: {choices}")
        if annual_rate is None:
            annual_rate = self.plan.default_annual_rate
        return self._calculate(amount, installments, start_month, annual_rate)

    @abstractmethod
    def _calculate(
        self,
        amount: int,
        installments: int,
        start_month: date,
        annual_rate: Decimal | None,
    ) -> list[Payment]:
        """カード会社固有の計算を行う。"""


class SmbcInstallmentCalculator(InstallmentCalculator):
    """三井住友カードの定額分割方式を計算する。"""

    def _calculate(
        self,
        amount: int,
        installments: int,
        start_month: date,
        annual_rate: Decimal | None,
    ) -> list[Payment]:
        if annual_rate is not None:
            raise ValueError("年率の指定はJCBでのみ利用できます。")

        rate = self.plan.rates[installments]
        total_fee = int(
            (Decimal(amount) * rate.fee_per_100_yen / Decimal(100)).quantize(
                Decimal("1"), rounding=ROUND_DOWN
            )
        )
        total = amount + total_fee
        regular_payment, first_remainder = divmod(total, installments)
        regular_principal, first_principal_remainder = divmod(amount, installments)

        balance = amount
        result: list[Payment] = []
        for number in range(1, installments + 1):
            payment_amount = regular_payment + (first_remainder if number == 1 else 0)
            principal = regular_principal + (
                first_principal_remainder if number == 1 else 0
            )
            monthly_fee = payment_amount - principal
            balance -= principal
            result.append(
                Payment(
                    number,
                    add_months(start_month, number).strftime("%Y-%m"),
                    payment_amount,
                    principal,
                    monthly_fee,
                    balance,
                )
            )
        return result


class JcbInstallmentCalculator(InstallmentCalculator):
    """JCBの初回日割り・2回目以降月利方式を計算する。"""

    def _calculate(
        self,
        amount: int,
        installments: int,
        start_month: date,
        annual_rate: Decimal | None,
    ) -> list[Payment]:
        if annual_rate is None:
            raise RuntimeError("JCBの既定年率が設定されていません。")
        if not annual_rate.is_finite() or not (
            JCB_MIN_ANNUAL_RATE <= annual_rate <= JCB_MAX_ANNUAL_RATE
        ):
            raise ValueError(
                f"JCBの年率は{JCB_MIN_ANNUAL_RATE}%～{JCB_MAX_ANNUAL_RATE}%で入力してください。"
            )
        rate = Rate(
            annual_rate,
            installment_coefficient(annual_rate, installments),
        )
        monthly_rate = rate.annual_rate / Decimal(1200)
        payment_coefficient = rate.fee_per_100_yen
        if rate.annual_rate == Decimal("18.00"):
            payment_coefficient = JCB_PAYMENT_COEFFICIENT_OVERRIDES.get(
                installments, payment_coefficient
            )
        fee_upper_estimate = int(
            (Decimal(amount) * payment_coefficient / Decimal(100)).quantize(
                Decimal("1"), rounding=ROUND_DOWN
            )
        )
        regular_payment = (amount + fee_upper_estimate) // installments
        first_payment_month = add_months(start_month, 1)
        first_period_start = date(start_month.year, start_month.month, 16)
        first_payment_date = date(
            first_payment_month.year, first_payment_month.month, 10
        )
        first_period_days = (first_payment_date - first_period_start).days + 1

        balance = amount
        result: list[Payment] = []
        for number in range(1, installments + 1):
            standard_fee = int(
                (Decimal(balance) * monthly_rate).quantize(
                    Decimal("1"), rounding=ROUND_DOWN
                )
            )
            if number == installments:
                principal = balance
            else:
                principal = regular_payment - standard_fee

            if number == 1:
                monthly_fee = int(
                    (
                        Decimal(balance)
                        * rate.annual_rate
                        / Decimal(100)
                        * Decimal(first_period_days)
                        / Decimal(365)
                    ).quantize(Decimal("1"), rounding=ROUND_DOWN)
                )
            else:
                monthly_fee = standard_fee

            payment_amount = principal + monthly_fee
            balance -= principal
            result.append(
                Payment(
                    number,
                    add_months(start_month, number).strftime("%Y-%m"),
                    payment_amount,
                    principal,
                    monthly_fee,
                    balance,
                )
            )
        return result


CALCULATORS: dict[str, InstallmentCalculator] = {
    SMBC_CARD: SmbcInstallmentCalculator(CARD_PLANS[SMBC_CARD]),
    JCB_CARD: JcbInstallmentCalculator(CARD_PLANS[JCB_CARD]),
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
    card: str = DEFAULT_CARD,
    annual_rate: Decimal | None = None,
) -> list[Payment]:
    """月別支払予定を返す。start_month の翌月を第1回支払月とする。"""
    if amount < 1_000:
        raise ValueError("支払金額は1,000円以上で入力してください。")
    try:
        calculator = CALCULATORS[card]
    except KeyError as error:
        choices = ", ".join(CALCULATORS)
        raise ValueError(f"カード会社は次から選んでください: {choices}") from error
    start_month = start_month or date.today().replace(day=1)
    return calculator.calculate(amount, installments, start_month, annual_rate)


def yen(value: int) -> str:
    return f"{value:,}円"


def display_width(value: str) -> int:
    """端末に表示したときの文字列の幅を返す。"""
    return sum(
        0
        if unicodedata.combining(character)
        else 2
        if unicodedata.east_asian_width(character) in {"F", "W"}
        else 1
        for character in value
    )


def display_rjust(value: str, width: int) -> str:
    """全角文字の表示幅を考慮して文字列を右寄せする。"""
    return " " * max(0, width - display_width(value)) + value


def print_result(
    amount: int,
    installments: int,
    payments: Sequence[Payment],
    card: str = DEFAULT_CARD,
    annual_rate: Decimal | None = None,
) -> None:
    plan = CARD_PLANS[card]
    displayed_annual_rate = annual_rate or plan.rates[installments].annual_rate
    total_fee = sum(item.fee for item in payments)
    print(f"\n{plan.name} あとから分割シミュレーション")
    print(f"利用金額: {yen(amount)} / {installments}回 / 実質年率: {displayed_annual_rate}%")
    print(f"手数料: {yen(total_fee)} / 支払総額: {yen(amount + total_fee)}\n")

    headers = ("回", "支払月", "支払金額", "元金", "手数料", "残元金")
    rows = [
        (str(p.number), p.month, yen(p.amount), yen(p.principal), yen(p.fee), yen(p.balance))
        for p in payments
    ]
    widths = [
        max(display_width(headers[i]), *(display_width(row[i]) for row in rows))
        for i in range(len(headers))
    ]
    print("  ".join(display_rjust(headers[i], widths[i]) for i in range(len(headers))))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(display_rjust(row[i], widths[i]) for i in range(len(row))))
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


def annual_rate_value(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("年率は数値で入力してください。") from error
    if not result.is_finite():
        raise argparse.ArgumentTypeError("年率は有限の数値で入力してください。")
    if not JCB_MIN_ANNUAL_RATE <= result <= JCB_MAX_ANNUAL_RATE:
        raise argparse.ArgumentTypeError(
            f"JCBの年率は{JCB_MIN_ANNUAL_RATE}%～{JCB_MAX_ANNUAL_RATE}%で入力してください。"
        )
    return result


def card_value(value: str) -> str:
    if value not in CARD_PLANS:
        choices = ", ".join(CARD_PLANS)
        raise argparse.ArgumentTypeError(
            f"カード会社は次から選んでください: {choices}"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="あとから分割の月別支払額を計算します。")
    parser.add_argument("amount", nargs="?", type=positive_integer, help="利用金額（円）")
    parser.add_argument("installments", nargs="?", type=positive_integer, help="分割回数")
    parser.add_argument(
        "--card",
        type=card_value,
        metavar="CARD",
        help=f"カード会社（省略時は対話入力、既定: {DEFAULT_CARD}）",
    )
    parser.add_argument(
        "--annual-rate",
        type=annual_rate_value,
        metavar="PERCENT",
        help=f"JCBの実質年率（既定: {JCB_DEFAULT_ANNUAL_RATE}）",
    )
    parser.add_argument("--start", type=parse_month, metavar="YYYY-MM", help="申込月（省略時は今月）")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        amount = args.amount or positive_integer(input("支払金額（円）: ").strip())
        installments = args.installments or positive_integer(input("分割回数: ").strip())
        card_choices = "/".join(CARD_PLANS)
        card = args.card or card_value(
            input(f"カード会社（{card_choices}） [{DEFAULT_CARD}]: ").strip()
            or DEFAULT_CARD
        )

        annual_rate = args.annual_rate
        if card == JCB_CARD:
            annual_rate = args.annual_rate or annual_rate_value(
                input(
                    f"実質年率（%） [{JCB_DEFAULT_ANNUAL_RATE}]: "
                ).strip()
                or format(JCB_DEFAULT_ANNUAL_RATE, "f")
            )

        payments = simulate(
            amount,
            installments,
            args.start,
            card,
            annual_rate,
        )
    except KeyboardInterrupt:
        print("\n中断しました。")
        return 130
    except EOFError:
        print("\nエラー: 入力が終了しました。")
        return 2
    except (ValueError, argparse.ArgumentTypeError) as error:
        print(f"エラー: {error}")
        return 2
    print_result(amount, installments, payments, card, annual_rate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
