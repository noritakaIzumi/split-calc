# split-calc

三井住友カードとJCBの「あとから分割」について、利用金額と分割回数から毎月の支払金額・元金・手数料・残元金を表示する Python CLI です。外部パッケージは使いません。

## 環境構築

Python 3.12と[uv](https://docs.astral.sh/uv/)を使用します。uvをインストールしたうえで、リポジトリのルートで環境を同期してください。

```console
uv sync
```

uvは `.python-version` に指定したPython 3.12を選択し、必要に応じてPython本体を取得して `.venv` を作成します。生成される `.venv` はGitの管理対象外です。

コミットメッセージの検査を有効にするため、初回のみpre-commitの`commit-msg`フックをインストールしてください。

```console
uvx pre-commit install --hook-type commit-msg
```

以後のコミットでは、`feat(cli): add monthly installment breakdown`のようなConventional Commits形式が必須になります。使用できるtypeは`feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`, `style`, `revert`です。破壊的変更ではsubjectの`!`と`BREAKING CHANGE:` footerの両方が必要です。

## 使い方

```console
uv run split_calc.py 60000 3
```

カード会社は `--card` で指定します。省略時は対話形式で入力でき、空のままEnterを押すと三井住友カード（`smbc`）になります。

```console
uv run split_calc.py 100000 10 --card jcb
```

JCBの実質年率は既定で15.00%です。カードに適用される年率を指定する場合は `--annual-rate` を使います。JCBを対話形式で選び、`--annual-rate` を省略した場合は年率も対話形式で入力できます。

```console
uv run split_calc.py 100000 10 --card jcb --annual-rate 18.00
```

引数を省略すると対話形式で入力できます。

```console
uv run split_calc.py
支払金額（円）: 60000
分割回数: 3
カード会社（smbc/jcb） [smbc]:
```

JCBと年率を対話形式で指定する例です。

```console
uv run split_calc.py
支払金額（円）: 100000
分割回数: 10
カード会社（smbc/jcb） [smbc]: jcb
実質年率（%） [15.00]: 18.00
```

対話入力は `Ctrl+C` で中断できます。

申込月を指定する場合は `--start YYYY-MM` を使います。第1回はその翌月として表示されます。

```console
uv run split_calc.py 60000 3 --start 2026-08
```

三井住友カードの対応回数は `3, 4, 5, 6, 10, 12, 15, 18, 20, 24, 30, 36, 40, 42, 48, 50, 54, 60` 回です。JCBは3～24回の各回と `30, 36, 42, 48, 54, 60` 回に対応します。利用金額は1,000円以上です。

## 計算方法

- 三井住友カードは2025年4月1日改定後の公式の実質年率と「利用金額100円当たりの手数料」を使用します。
- JCBは指定した実質年率（既定15.00%、指定可能範囲7.92～18.00%）を前提に元利均等払いで計算します。初回手数料は締切翌日の16日から翌月10日までを年365日で日割りし、2回目以降は指定年率の12分の1に相当する月利で計算します。
- 総手数料は `利用金額 × 100円当たりの手数料 ÷ 100` の1円未満を切り捨てます。
- 支払総額を回数で均等に分け、1円未満の端数は公式案内どおり初回に加えます。
- 三井住友カードの月別元金も回数で均等に分け、端数を初回に加えます。各回の支払額との差を月別手数料として表示します。
- JCBの月別手数料は1円未満を切り捨て、最終回は残元金を全額支払うよう調整します。

三井住友カードの月別内訳は、定額分割方式（総額均等割）に基づく表示です。繰り上げ返済時の精算額は、78分法またはそれに準ずる所定の方法で計算されるため、この残元金とは異なります。一部カード・加盟店やボーナス併用払いでは条件が異なる場合があります。

JCBの手数料率はカードの種類により異なります。本ツールのJCBモードは毎月15日締め・翌月10日払いとして計算します。金融機関休業日やカード固有の条件などにより、実際の請求額とは異なる場合があります。

公式情報: [三井住友カード「あとから分割」](https://www.smbc-card.com/mem/revo/atokarabunkatsu.jsp)

公式情報: [JCB「ショッピング利用後分割払い」](https://www.jcb.co.jp/payment/installment/later/)、[JCBショッピング分割払い「ご利用にあたって」](https://www.jcb.co.jp/payment/pop/kappan-goriyou.html)

## テスト

```console
uv run python -m unittest -v
scripts/test-check-commit-message.sh
```
