#!/usr/bin/env python3
"""クレジットカードの「あとから分割」月別支払いシミュレーター。"""

from __future__ import annotations

import argparse
import calendar
import shlex
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
    arbitrary_installments: bool = False


@dataclass(frozen=True)
class PaymentPlan:
    """繰り上げ返済の比較対象となる1件の分割払い。"""

    name: str
    amount: int
    installments: int
    start_month: date
    card: str = "smbc"
    annual_rate: Decimal | None = None


@dataclass(frozen=True)
class Payoff:
    month: str
    name: str
    amount: int
    fund_before: int
    fund_after: int
    saving_month: int


@dataclass(frozen=True)
class SavingEntry:
    number: int | None
    month: str
    description: str
    deposit: int
    withdrawal: int
    balance: int
    regular_payments: tuple[int, ...] = ()


@dataclass(frozen=True)
class OptimizationResult:
    order: tuple[str, ...]
    baseline_fee: int
    optimized_fee: int
    payoffs: tuple[Payoff, ...]
    saving_entries: tuple[SavingEntry, ...] = ()
    saving_start_month: str | None = None

    @property
    def saved_fee(self) -> int:
        return self.baseline_fee - self.optimized_fee


SMBC_CARD = "smbc"
JCB_CARD = "jcb"
INTEREST_FREE = "interest-free"
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
    INTEREST_FREE: CardPlan(
        "無利子",
        {},
        "手数料なしで元金を均等に返済し、1円未満の端数は初回に加えます。",
        default_annual_rate=Decimal("0"),
        arbitrary_installments=True,
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
        if installments <= 0:
            raise ValueError("分割回数は1回以上で入力してください。")
        if (
            not self.plan.arbitrary_installments
            and installments not in self.plan.rates
        ):
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


class InterestFreeInstallmentCalculator(InstallmentCalculator):
    """奨学金など、手数料のない均等返済を計算する。"""

    def _calculate(
        self,
        amount: int,
        installments: int,
        start_month: date,
        annual_rate: Decimal | None,
    ) -> list[Payment]:
        if annual_rate not in {None, Decimal("0")}:
            raise ValueError("無利子の支払いでは年率を指定できません。")

        regular_principal, first_remainder = divmod(amount, installments)
        balance = amount
        result: list[Payment] = []
        for number in range(1, installments + 1):
            principal = regular_principal + (first_remainder if number == 1 else 0)
            balance -= principal
            result.append(
                Payment(
                    number,
                    add_months(start_month, number).strftime("%Y-%m"),
                    principal,
                    principal,
                    0,
                    balance,
                )
            )
        return result


CALCULATORS: dict[str, InstallmentCalculator] = {
    SMBC_CARD: SmbcInstallmentCalculator(CARD_PLANS[SMBC_CARD]),
    JCB_CARD: JcbInstallmentCalculator(CARD_PLANS[JCB_CARD]),
    INTEREST_FREE: InterestFreeInstallmentCalculator(CARD_PLANS[INTEREST_FREE]),
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


def optimize_payoffs(
    plans: Sequence[PaymentPlan],
    monthly_saving: int,
    saving_start: date | None = None,
    fixed_monthly_total: bool = False,
) -> OptimizationResult:
    """毎月の積立で一括返済する順序を総手数料が最小になるよう選ぶ。

    各月の積立後に対象の残元金を払える場合は一括返済し、足りない場合は
    その月の通常支払いを行った後にも再判定する。fixed_monthly_total が真なら、
    通常支払いと積立の合計が monthly_saving になるよう積立額を調整する。
    """
    if not plans:
        raise ValueError("支払いを1件以上指定してください。")
    if monthly_saving <= 0:
        raise ValueError("毎月の積立額は1円以上で入力してください。")
    if len(plans) > 12:
        raise ValueError("比較できる支払いは12件までです。")
    names = [plan.name for plan in plans]
    if any(not name.strip() for name in names):
        raise ValueError("支払い名を入力してください。")
    if len(set(names)) != len(names):
        raise ValueError("支払い名は重複しないようにしてください。")

    schedules = [
        simulate(
            plan.amount,
            plan.installments,
            plan.start_month,
            plan.card,
            plan.annual_rate,
        )
        for plan in plans
    ]
    baseline_fee = sum(payment.fee for schedule in schedules for payment in schedule)
    first_payment_month = parse_month(min(schedule[0].month for schedule in schedules))
    first_saving_month = saving_start or first_payment_month
    timeline_start = min(first_payment_month, first_saving_month)

    best_order: tuple[int, ...] | None = None
    best_fee: int | None = None
    best_payoffs: tuple[Payoff, ...] = ()
    best_saving_entries: tuple[SavingEntry, ...] = ()
    excessive_month: str | None = None
    # 同一状態へより高い手数料で到達した枝は、その後も逆転できない。
    lowest_fee_by_state: dict[tuple[object, ...], int] = {}

    def search(
        order: tuple[int, ...],
        remaining: tuple[int, ...],
        current: date,
        before_payments: bool,
        positions: tuple[int, ...],
        balances: tuple[int, ...],
        fund: int,
        incurred_fee: int,
        payoffs: tuple[Payoff, ...],
        saving_entries: tuple[SavingEntry, ...],
    ) -> None:
        nonlocal best_order, best_fee, best_payoffs, best_saving_entries
        nonlocal excessive_month

        # 将来の手数料は負にならないため、ここまでで最良値以上なら枝刈りできる。
        if best_fee is not None and incurred_fee >= best_fee:
            return

        completed = tuple(index for index in remaining if balances[index] == 0)
        if completed:
            order += completed
            completed_set = set(completed)
            remaining = tuple(
                index for index in remaining if index not in completed_set
            )
        if not remaining:
            best_order = order
            best_fee = incurred_fee
            best_payoffs = payoffs
            best_saving_entries = saving_entries
            return

        state_key = (
            remaining,
            current,
            before_payments,
            positions,
            balances,
            fund,
        )
        previous_fee = lowest_fee_by_state.get(state_key)
        if previous_fee is not None and previous_fee <= incurred_fee:
            return
        lowest_fee_by_state[state_key] = incurred_fee

        for target in remaining:
            next_current = current
            next_before_payments = before_payments
            next_positions = list(positions)
            next_balances = list(balances)
            next_fund = fund
            next_fee = incurred_fee
            next_payoffs = payoffs
            next_saving_entries = saving_entries

            while next_before_payments or next_balances[target] > next_fund:
                if next_before_payments:
                    month = next_current.strftime("%Y-%m")
                    regular_payments = [0] * len(plans)
                    for index, schedule in enumerate(schedules):
                        position = next_positions[index]
                        if next_balances[index] == 0 or position >= len(schedule):
                            continue
                        payment = schedule[position]
                        if payment.month != month:
                            continue
                        next_balances[index] = payment.balance
                        next_fee += payment.fee
                        next_positions[index] += 1
                        regular_payments[index] = payment.amount
                    regular_total = sum(regular_payments)
                    if (
                        fixed_monthly_total
                        and next_current >= first_saving_month
                        and regular_total > monthly_saving
                    ):
                        excessive_month = month
                        return
                    for entry_index in range(
                        len(next_saving_entries) - 1, -1, -1
                    ):
                        entry = next_saving_entries[entry_index]
                        if entry.month == month and entry.description in {
                            "積立",
                            "積立開始前",
                        }:
                            deposit = entry.deposit
                            balance = entry.balance
                            if fixed_monthly_total and entry.description == "積立":
                                deposit -= regular_total
                                balance -= regular_total
                                next_fund -= regular_total
                            next_saving_entries = (
                                next_saving_entries[:entry_index]
                                + (
                                    SavingEntry(
                                        entry.number,
                                        entry.month,
                                        entry.description,
                                        deposit,
                                        entry.withdrawal,
                                        balance,
                                        tuple(regular_payments),
                                    ),
                                )
                                + next_saving_entries[entry_index + 1 :]
                            )
                            break
                    next_before_payments = False
                else:
                    next_current = add_months(next_current, 1)
                    next_before_payments = True
                    if next_current >= first_saving_month:
                        next_fund += monthly_saving
                        saving_month = (
                            (next_current.year - first_saving_month.year) * 12
                            + next_current.month
                            - first_saving_month.month
                            + 1
                        )
                        next_saving_entries += (
                            SavingEntry(
                                saving_month,
                                next_current.strftime("%Y-%m"),
                                "積立",
                                monthly_saving,
                                0,
                                next_fund,
                                (0,) * len(plans),
                            ),
                        )
                    else:
                        next_saving_entries += (
                            SavingEntry(
                                None,
                                next_current.strftime("%Y-%m"),
                                "積立開始前",
                                0,
                                0,
                                next_fund,
                                (0,) * len(plans),
                            ),
                        )
                if next_balances[target] == 0:
                    break

            if next_balances[target] > 0:
                payoff_amount = next_balances[target]
                fund_before = next_fund
                next_fund -= payoff_amount
                next_balances[target] = 0
                next_payoffs += (
                    Payoff(
                        next_current.strftime("%Y-%m"),
                        plans[target].name,
                        payoff_amount,
                        fund_before,
                        next_fund,
                        (next_current.year - first_saving_month.year) * 12
                        + next_current.month
                        - first_saving_month.month
                        + 1,
                    ),
                )
                next_saving_entries += (
                    SavingEntry(
                        None,
                        next_current.strftime("%Y-%m"),
                        f"繰上返済（{plans[target].name}）",
                        0,
                        payoff_amount,
                        next_fund,
                        (0,) * len(plans),
                    ),
                )

            search(
                order + (target,),
                tuple(index for index in remaining if index != target),
                next_current,
                next_before_payments,
                tuple(next_positions),
                tuple(next_balances),
                next_fund,
                next_fee,
                next_payoffs,
                next_saving_entries,
            )

    search(
        (),
        tuple(range(len(plans))),
        timeline_start,
        True,
        (0,) * len(plans),
        tuple(plan.amount for plan in plans),
        monthly_saving if timeline_start == first_saving_month else 0,
        0,
        (),
        (
            SavingEntry(
                1,
                first_saving_month.strftime("%Y-%m"),
                "積立",
                monthly_saving,
                0,
                monthly_saving,
                (0,) * len(plans),
            ),
        )
        if timeline_start == first_saving_month
        else (
            SavingEntry(
                None,
                timeline_start.strftime("%Y-%m"),
                "積立開始前",
                0,
                0,
                0,
                (0,) * len(plans),
            ),
        ),
    )
    if best_order is None or best_fee is None:
        if excessive_month is not None:
            raise ValueError(
                f"{excessive_month} の通常返済額が毎月の合計額を超えています。"
            )
        raise RuntimeError("返済順を決定できませんでした。")
    return OptimizationResult(
        tuple(plans[index].name for index in best_order),
        baseline_fee,
        best_fee,
        best_payoffs,
        best_saving_entries,
        first_saving_month.strftime("%Y-%m"),
    )


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


def display_ljust(value: str, width: int) -> str:
    """全角文字の表示幅を考慮して文字列を左寄せする。"""
    return value + " " * max(0, width - display_width(value))


def print_result(
    amount: int,
    installments: int,
    payments: Sequence[Payment],
    card: str = DEFAULT_CARD,
    annual_rate: Decimal | None = None,
) -> None:
    plan = CARD_PLANS[card]
    displayed_annual_rate = annual_rate
    if displayed_annual_rate is None:
        displayed_annual_rate = plan.default_annual_rate
    if displayed_annual_rate is None:
        displayed_annual_rate = plan.rates[installments].annual_rate
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


def payment_plan_value(value: str) -> PaymentPlan:
    """NAME:CARD:AMOUNT:INSTALLMENTS[:RATE[:START]] を解析する。"""
    parts = value.split(":")
    if not 4 <= len(parts) <= 6:
        raise argparse.ArgumentTypeError(
            "支払いは NAME:CARD:AMOUNT:INSTALLMENTS[:RATE[:START]] 形式で入力してください。"
        )
    name, card_text, amount_text, installments_text = parts[:4]
    if not name.strip():
        raise argparse.ArgumentTypeError("支払い名を入力してください。")
    card = card_value(card_text)
    amount = positive_integer(amount_text)
    if amount < 1_000:
        raise argparse.ArgumentTypeError(
            "支払金額は1,000円以上で入力してください。"
        )
    installments = positive_integer(installments_text)
    if (
        not CARD_PLANS[card].arbitrary_installments
        and installments not in CARD_PLANS[card].rates
    ):
        choices = ", ".join(str(item) for item in CARD_PLANS[card].rates)
        raise argparse.ArgumentTypeError(
            f"分割回数は次から選んでください: {choices}"
        )
    rate = annual_rate_value(parts[4]) if len(parts) >= 5 and parts[4] else None
    start = (
        parse_month(parts[5])
        if len(parts) == 6
        else date.today().replace(day=1)
    )
    if card != JCB_CARD and rate is not None:
        raise argparse.ArgumentTypeError("年率の指定はJCBでのみ利用できます。")
    return PaymentPlan(name, amount, installments, start, card, rate)


def print_optimization(
    result: OptimizationResult,
    monthly_saving: int,
    fixed_monthly_total: bool = False,
) -> None:
    print("\n繰り上げ返済の最適化（概算）")
    label = "毎月の返済・積立合計額" if fixed_monthly_total else "毎月の積立額"
    print(f"{label}: {yen(monthly_saving)}")
    if result.saving_start_month is not None:
        print(f"積立開始月: {result.saving_start_month}")
    print(f"推奨順序: {' → '.join(result.order)}")
    print(
        f"手数料: {yen(result.baseline_fee)} → {yen(result.optimized_fee)} "
        f"（{yen(result.saved_fee)}削減）"
    )
    if result.saving_entries:
        headers = (
            "回",
            "月",
            "摘要",
            "返済",
            "積立",
            "繰上返済",
            "積立残高",
        )
        rows = [
            (
                str(entry.number) if entry.number is not None else "",
                entry.month,
                entry.description,
                yen(sum(entry.regular_payments))
                if any(entry.regular_payments)
                else "*",
                yen(entry.deposit) if entry.deposit else "*",
                yen(entry.withdrawal) if entry.withdrawal else "*",
                yen(entry.balance),
            )
            for entry in result.saving_entries
        ]
        widths = [
            max(display_width(headers[i]), *(display_width(row[i]) for row in rows))
            for i in range(len(headers))
        ]
        million_yen_width = display_width(yen(9_999_999))
        for index in range(3, len(headers)):
            widths[index] = max(widths[index], million_yen_width)
        print()
        print(
            "  ".join(
                display_ljust(headers[i], widths[i])
                if i in {1, 2}
                else display_rjust(headers[i], widths[i])
                for i in range(len(headers))
            )
        )
        print("  ".join("-" * width for width in widths))
        for row in rows:
            print(
                "  ".join(
                    "*" * widths[i]
                    if row[i] == "*"
                    else display_ljust(row[i], widths[i])
                    if i in {1, 2}
                    else display_rjust(row[i], widths[i])
                    for i in range(len(row))
                )
            )
    if fixed_monthly_total:
        print("\n※通常支払いとの差額を積み立て、毎月の返済・積立合計額を一定にした概算です。")
    else:
        print("\n※通常支払いとは別に積み立て、残元金を一括返済できる月で比較した概算です。")
    print("※実際の精算額・手数料はカード会社に確認してください。")


def input_value(prompt: str, converter, default: str | None = None):
    """値が妥当になるまで同じ項目を入力させる。"""
    while True:
        value = input(prompt).strip()
        if not value and default is not None:
            value = default
        try:
            return converter(value)
        except (ValueError, argparse.ArgumentTypeError) as error:
            print(f"エラー: {error}")


def confirmation_value(prompt: str) -> bool:
    """yes/noを妥当な形式で入力させる。"""
    while True:
        value = input(prompt).strip().lower()
        if value in {"y", "yes"}:
            return True
        if value in {"", "n", "no"}:
            return False
        print("エラー: y または n で入力してください。")


def payment_plan_option(plan: PaymentPlan) -> str:
    """PaymentPlanを再利用可能な--payment引数へ変換する。"""
    rate = format(plan.annual_rate, "f") if plan.annual_rate is not None else ""
    value = ":".join(
        (
            plan.name,
            plan.card,
            str(plan.amount),
            str(plan.installments),
            rate,
            plan.start_month.strftime("%Y-%m"),
        )
    )
    return f"--payment {shlex.quote(value)}"


def input_payment_plans() -> tuple[list[PaymentPlan], int, date | None]:
    """繰り上げ返済の条件を対話形式で入力する。"""
    monthly_saving = input_value(
        "毎月の繰り上げ返済積立額（円）: ", positive_integer
    )
    while True:
        saving_start_text = input(
            "積立開始月（YYYY-MM、省略時は最初の支払月）: "
        ).strip()
        if not saving_start_text:
            saving_start = None
            break
        try:
            saving_start = parse_month(saving_start_text)
            break
        except argparse.ArgumentTypeError as error:
            print(f"エラー: {error}")
    card_choices = "/".join(CARD_PLANS)
    default_start = date.today().replace(day=1)
    plans: list[PaymentPlan] = []
    finish_input = False
    while len(plans) < 12:
        index = len(plans) + 1
        print(f"\n--- 支払い {index} ---")
        while True:
            shortcut = input(
                "--payment の引数部分（個別入力は空Enter）: "
            ).strip()
            if shortcut:
                try:
                    plan = payment_plan_value(shortcut)
                    if plan.name in {item.name for item in plans}:
                        raise ValueError(
                            "支払い名は重複しないようにしてください。"
                        )
                except (ValueError, argparse.ArgumentTypeError) as error:
                    print(f"エラー: {error}")
                    continue
            else:
                card = input_value(
                    f"カード会社（{card_choices}） [{DEFAULT_CARD}]: ",
                    card_value,
                    DEFAULT_CARD,
                )
                annual_rate = None
                if card == JCB_CARD:
                    annual_rate = input_value(
                        f"実質年率（%） [{JCB_DEFAULT_ANNUAL_RATE}]: ",
                        annual_rate_value,
                        format(JCB_DEFAULT_ANNUAL_RATE, "f"),
                    )
                default_name = f"支払い{index}"

                def name_value(value: str) -> str:
                    if ":" in value:
                        raise ValueError("支払い名にコロン（:）は使用できません。")
                    if value in {plan.name for plan in plans}:
                        raise ValueError("支払い名は重複しないようにしてください。")
                    return value

                name = input_value(
                    f"支払い名 [{default_name}]: ", name_value, default_name
                )

                def amount_value(value: str) -> int:
                    amount = positive_integer(value)
                    if amount < 1_000:
                        raise ValueError("支払金額は1,000円以上で入力してください。")
                    return amount

                amount = input_value("利用金額（円）: ", amount_value)

                def installments_value(value: str) -> int:
                    installments = positive_integer(value)
                    if (
                        not CARD_PLANS[card].arbitrary_installments
                        and installments not in CARD_PLANS[card].rates
                    ):
                        choices = ", ".join(
                            str(item) for item in CARD_PLANS[card].rates
                        )
                        raise ValueError(
                            f"分割回数は次から選んでください: {choices}"
                        )
                    return installments

                installments = input_value("分割回数: ", installments_value)
                start_month = input_value(
                    f"申込月（YYYY-MM） [{default_start.strftime('%Y-%m')}]: ",
                    parse_month,
                    default_start.strftime("%Y-%m"),
                )
                plan = PaymentPlan(
                    name,
                    amount,
                    installments,
                    start_month,
                    card,
                    annual_rate,
                )
            rate_text = (
                f" / 実質年率: {plan.annual_rate}%"
                if plan.annual_rate is not None
                else ""
            )
            print("\n入力内容")
            print(f"カード会社: {CARD_PLANS[plan.card].name}{rate_text}")
            print(f"支払い名: {plan.name}")
            print(
                f"利用金額: {yen(plan.amount)} / 分割回数: {plan.installments}回"
            )
            print(f"申込月: {plan.start_month.strftime('%Y-%m')}")
            if confirmation_value("この内容でよろしいですか？ [y/N]: "):
                break
            if confirmation_value(
                "この支払いを破棄して計算に進みますか？ [y/N]: "
            ):
                if plans:
                    finish_input = True
                    break
                print("エラー: 計算には確定済みの支払いが1件以上必要です。")
            print("入力内容を破棄して、この支払いを入力し直します。")
        if finish_input:
            break
        plans.append(plan)
        print(f"\n{payment_plan_option(plan)}\n")
        if len(plans) == 12:
            print("\n最大件数の12件に達したため、計算を開始します。")
            break
        if not confirmation_value("支払いを追加しますか？ [y/N]: "):
            break
    return plans, monthly_saving, saving_start


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
    parser.add_argument(
        "--optimize",
        action="store_true",
        help="繰り上げ返済の条件を対話形式で入力して最適化する",
    )
    parser.add_argument(
        "--payment",
        action="append",
        type=payment_plan_value,
        metavar="SPEC",
        help="最適化する支払い。NAME:CARD:AMOUNT:INSTALLMENTS[:RATE[:START]]（複数指定可）",
    )
    parser.add_argument(
        "--monthly-saving",
        type=positive_integer,
        metavar="YEN",
        help="毎月の繰り上げ返済積立額",
    )
    parser.add_argument(
        "--saving-start",
        type=parse_month,
        metavar="YYYY-MM",
        help="積立開始月（既定: 最初の支払月）",
    )
    parser.add_argument(
        "--fixed-monthly-total",
        action="store_true",
        help="--monthly-saving の額を返済と積立の毎月の合計額として扱う",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.optimize:
            if any(
                value is not None
                for value in (
                    args.amount,
                    args.installments,
                    args.card,
                    args.annual_rate,
                    args.start,
                    args.payment,
                    args.monthly_saving,
                    args.saving_start,
                )
            ):
                raise ValueError("--optimize は他の入力オプションと同時に指定できません。")
            plans, monthly_saving, saving_start = input_payment_plans()
            if args.fixed_monthly_total:
                result = optimize_payoffs(
                    plans, monthly_saving, saving_start, fixed_monthly_total=True
                )
                print_optimization(result, monthly_saving, fixed_monthly_total=True)
            else:
                result = optimize_payoffs(plans, monthly_saving, saving_start)
                print_optimization(result, monthly_saving)
            return 0
        if args.payment:
            if args.monthly_saving is None:
                raise ValueError("--payment には --monthly-saving が必要です。")
            if any(
                value is not None
                for value in (
                    args.amount,
                    args.installments,
                    args.card,
                    args.annual_rate,
                    args.start,
                )
            ):
                raise ValueError(
                    "最適化では位置引数および --card、--annual-rate、--start を指定できません。"
                )
            if args.fixed_monthly_total:
                result = optimize_payoffs(
                    args.payment,
                    args.monthly_saving,
                    args.saving_start,
                    fixed_monthly_total=True,
                )
                print_optimization(
                    result, args.monthly_saving, fixed_monthly_total=True
                )
            else:
                result = optimize_payoffs(
                    args.payment, args.monthly_saving, args.saving_start
                )
                print_optimization(result, args.monthly_saving)
            return 0
        if (
            args.monthly_saving is not None
            or args.saving_start is not None
            or args.fixed_monthly_total
        ):
            raise ValueError(
                "--monthly-saving、--saving-start、--fixed-monthly-total には "
                "--payment または --optimize が必要です。"
            )
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
